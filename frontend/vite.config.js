import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const frontendDir = path.dirname(fileURLToPath(import.meta.url));
const repoDir = path.resolve(frontendDir, "..");
const resultsDir = path.join(repoDir, "simulation", "results");

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

function publicManifest() {
  const manifest = readManifest();
  for (const game of Object.values(manifest.games)) {
    const decision = game.next_decision;
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
      },
    };
  }
  return manifest;
}

function simulationApi() {
  let syncProcess = null;
  let finishedAt = 0;
  let syncState = {
    status: "idle",
    phase: "idle",
    message: "等待官方資料檢查",
    details: null,
    result: null,
    error: "",
  };

  const startSync = () => {
    if (syncProcess) return syncState;
    if (syncState.status === "done" && Date.now() - finishedAt < 60_000) {
      return syncState;
    }

    syncState = {
      status: "running",
      phase: "starting",
      message: "正在啟動官方資料檢查",
      details: null,
      result: null,
      error: "",
    };
    const python = process.env.PYTHON || (process.platform === "win32" ? "python" : "python3");
    const child = spawn(
      python,
      ["-X", "utf8", "lotto.py", "sync", "--json"],
      {
        cwd: repoDir,
        windowsHide: true,
        stdio: ["ignore", "pipe", "pipe"],
      },
    );
    syncProcess = child;
    let stdout = "";
    let stderr = "";
    let result = null;

    const consumeLines = () => {
      const lines = stdout.split(/\r?\n/);
      stdout = lines.pop() ?? "";
      for (const line of lines) {
        if (!line.trim()) continue;
        try {
          const payload = JSON.parse(line);
          if (payload.type === "progress") {
            syncState = {
              ...syncState,
              phase: payload.phase,
              message: payload.message,
              details: payload.details,
            };
          } else if (payload.type === "result") {
            result = payload.result;
          }
        } catch {
          stderr += `${line}\n`;
        }
      }
    };

    child.stdout.setEncoding("utf8");
    child.stdout.on("data", (chunk) => {
      stdout += chunk;
      consumeLines();
    });
    child.stderr.setEncoding("utf8");
    child.stderr.on("data", (chunk) => {
      stderr += chunk;
    });
    child.on("error", (error) => {
      syncState = {
        ...syncState,
        status: "error",
        phase: "error",
        message: "無法啟動自動同步",
        error: error.message,
      };
      syncProcess = null;
    });
    child.on("close", (code) => {
      consumeLines();
      finishedAt = Date.now();
      if (code === 0 && result) {
        syncState = {
          status: "done",
          phase: "ready",
          message:
            result.new_draws_total > 0
              ? "新開獎已完成檢討與策略狀態更新"
              : "官方資料無新增，策略狀態已是最新",
          details: result.games,
          result,
          error: "",
        };
      } else {
        syncState = {
          ...syncState,
          status: "error",
          phase: "error",
          message: "官方資料同步失敗",
          error: stderr.trim() || `同步程序結束碼 ${code}`,
        };
      }
      syncProcess = null;
    });
    return syncState;
  };

  const middleware = (request, response, next) => {
    const url = new URL(request.url, "http://127.0.0.1");
    if (url.pathname === "/api/sync" && request.method === "POST") {
      jsonResponse(response, 202, startSync());
      return;
    }
    if (url.pathname === "/api/sync/status") {
      jsonResponse(response, 200, syncState);
      return;
    }
    if (url.pathname === "/api/manifest") {
      try {
        jsonResponse(response, 200, publicManifest());
      } catch (error) {
        jsonResponse(response, 503, {
          error: "找不到模擬結果，請先在專案根目錄執行 python lotto.py loop。",
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

export default defineConfig({
  plugins: [react(), simulationApi()],
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
