import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

import {
  createSyncCoordinator,
  isPythonRuntimeFile,
} from "./automation-runtime.js";

const frontendDir = path.dirname(fileURLToPath(import.meta.url));
const repoDir = path.resolve(frontendDir, "..");
const resultsDir = path.join(repoDir, "simulation", "results");
const researchResultsDir = path.join(repoDir, "research", "results");
const forwardStatusFile = path.join(
  repoDir,
  "simulation",
  "forward",
  "status.json",
);
const automationDir = path.join(repoDir, "simulation", "automation");
const automationStatusFile = path.join(automationDir, "status.json");

function readRecentEvents(game, limit) {
  const file = path.join(resultsDir, `${game}.jsonl`);
  const descriptor = fs.openSync(file, "r");
  try {
    const { size } = fs.fstatSync(descriptor);
    const chunkSize = 1024 * 1024;
    let position = size;
    let text = "";
    let lineCount = 0;
    while (position > 0 && lineCount <= limit) {
      const length = Math.min(chunkSize, position);
      position -= length;
      const chunk = Buffer.allocUnsafe(length);
      fs.readSync(descriptor, chunk, 0, length, position);
      text = chunk.toString("utf8") + text;
      lineCount = (text.match(/\n/g) || []).length;
    }
    return text
      .trim()
      .split("\n")
      .slice(-limit)
      .map((line) => JSON.parse(line));
  } finally {
    fs.closeSync(descriptor);
  }
}

function jsonResponse(response, status, payload) {
  response.statusCode = status;
  response.setHeader("Content-Type", "application/json; charset=utf-8");
  response.setHeader("Cache-Control", "no-store");
  response.end(JSON.stringify(payload));
}

function readManifest() {
  return JSON.parse(
    fs.readFileSync(path.join(resultsDir, "manifest.json"), "utf8"),
  );
}

function publicManifest(automationStatus) {
  const manifest = readManifest();
  manifest.forward_experiment = fs.existsSync(forwardStatusFile)
    ? JSON.parse(fs.readFileSync(forwardStatusFile, "utf8"))
    : null;
  manifest.automation = automationStatus;
  for (const game of Object.values(manifest.games)) {
    const decision = game.next_decision;
    const feedbackProvenance =
      decision.adjudication.judge?.feedback_provenance ?? null;
    decision.critique_count = decision.critiques.length;
    decision.selected_count = decision.selected_tickets.length;
    decision.selected_tickets = [];
    decision.adjudication = {
      ...decision.adjudication,
      ranking: [],
      candidate_scores: [],
      judge: {
        source: "pending",
        requested_model:
          decision.adjudication.judge?.requested_model ?? "qwen3:8b",
        model: null,
        summary: "等待 60 次交叉評議完成後再呼叫終局裁判。",
        reasons: [],
        feedback_provenance: feedbackProvenance,
      },
    };
  }
  return manifest;
}

function createAutomationSupervisor() {
  let child = null;
  let stopping = false;
  let restartTimer = null;
  let crashCount = 0;
  let reloadRequested = false;

  const isOnline = () =>
    Boolean(child && child.exitCode === null && !child.killed);

  const start = () => {
    if (stopping || isOnline()) return;
    const python =
      process.env.PYTHON ||
      (process.platform === "win32" ? "python" : "python3");
    const startedAt = Date.now();
    child = spawn(
      python,
      [
        "-B",
        "-X",
        "utf8",
        "lotto.py",
        "watch",
        "--interval",
        "300",
        "--quiet",
      ],
      {
        cwd: repoDir,
        windowsHide: true,
        stdio: "ignore",
      },
    );
    child.on("error", () => {
      child = null;
    });
    child.on("close", () => {
      child = null;
      if (stopping) return;
      if (reloadRequested) {
        reloadRequested = false;
        crashCount = 0;
        restartTimer = setTimeout(start, 250);
        return;
      }
      crashCount =
        Date.now() - startedAt > 60_000 ? 0 : crashCount + 1;
      const delay = Math.min(30_000, 1000 * 2 ** crashCount);
      restartTimer = setTimeout(start, delay);
    });
  };

  const restart = () => {
    if (stopping || reloadRequested) return;
    if (restartTimer) clearTimeout(restartTimer);
    restartTimer = null;
    if (isOnline()) {
      reloadRequested = true;
      child.kill();
    } else {
      start();
    }
  };

  const stop = () => {
    stopping = true;
    reloadRequested = false;
    if (restartTimer) clearTimeout(restartTimer);
    restartTimer = null;
    if (child && child.exitCode === null) child.kill();
  };

  const attach = (server) => {
    if (process.env.VITEST) return;
    stopping = false;
    start();
    const reloadPythonRuntime = (file) => {
      if (isPythonRuntimeFile(file, repoDir)) restart();
    };
    if (server.watcher) {
      server.watcher.add([
        path.join(repoDir, "engine"),
        path.join(repoDir, "lotto.py"),
      ]);
      server.watcher.on("change", reloadPythonRuntime);
    }
    server.httpServer?.once("close", () => {
      server.watcher?.off("change", reloadPythonRuntime);
      stop();
    });
  };

  return {
    isOnline,
    plugin: {
      name: "lotto-automation-supervisor",
      configureServer: attach,
      configurePreviewServer: attach,
    },
  };
}

function simulationApi(supervisor) {
  const coordinator = createSyncCoordinator({
    automationDir,
    statusFile: automationStatusFile,
    isOnline: supervisor.isOnline,
  });

  const middleware = (request, response, next) => {
    const url = new URL(request.url, "http://127.0.0.1");
    if (url.pathname === "/api/sync" && request.method === "POST") {
      jsonResponse(response, 202, coordinator.request());
      return;
    }
    if (url.pathname === "/api/sync/status") {
      jsonResponse(response, 200, coordinator.status());
      return;
    }
    if (url.pathname === "/api/manifest") {
      try {
        jsonResponse(response, 200, publicManifest(coordinator.status()));
      } catch (error) {
        jsonResponse(response, 503, {
          error: "找不到模擬結果，請先在專案根目錄執行 python lotto.py loop。",
          detail: error.message,
        });
      }
      return;
    }
    if (url.pathname === "/api/research/council-quality") {
      try {
        const study = JSON.parse(
          fs.readFileSync(
            path.join(researchResultsDir, "council_quality.json"),
            "utf8",
          ),
        );
        jsonResponse(response, 200, study);
      } catch (error) {
        jsonResponse(response, 503, {
          error: "Agent 品質影子研究尚未產生。",
          detail: error.message,
        });
      }
      return;
    }

    const revealMatch = url.pathname.match(
      /^\/api\/reveal\/(super|lotto649)$/,
    );
    if (revealMatch && request.method === "POST") {
      try {
        const manifest = readManifest();
        jsonResponse(
          response,
          200,
          manifest.games[revealMatch[1]].next_decision,
        );
      } catch (error) {
        jsonResponse(response, 503, {
          error: "裁決資料尚未就緒。",
          detail: error.message,
        });
      }
      return;
    }

    const replayMatch = url.pathname.match(
      /^\/api\/replay\/(super|lotto649)$/,
    );
    if (replayMatch) {
      try {
        const requested = Number.parseInt(url.searchParams.get("limit"), 10);
        const limit = Number.isFinite(requested)
          ? Math.min(40, Math.max(1, requested))
          : 16;
        jsonResponse(response, 200, {
          game: replayMatch[1],
          events: readRecentEvents(replayMatch[1], limit),
        });
      } catch (error) {
        jsonResponse(response, 503, {
          error: "無法讀取逐期模擬帳本。",
          detail: error.message,
        });
      }
      return;
    }
    next();
  };

  return {
    name: "lotto-simulation-api",
    configureServer(server) {
      server.middlewares.use(middleware);
    },
    configurePreviewServer(server) {
      server.middlewares.use(middleware);
    },
  };
}

const automationSupervisor = createAutomationSupervisor();

export default defineConfig({
  plugins: [
    react(),
    automationSupervisor.plugin,
    simulationApi(automationSupervisor),
  ],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
  },
  preview: {
    host: "127.0.0.1",
    port: 4173,
    strictPort: true,
  },
});
