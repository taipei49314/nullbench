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

function simulationApi() {
  const middleware = (request, response, next) => {
    const url = new URL(request.url, "http://127.0.0.1");
    if (url.pathname === "/api/manifest") {
      try {
        const manifest = JSON.parse(
          fs.readFileSync(path.join(resultsDir, "manifest.json"), "utf8"),
        );
        jsonResponse(response, 200, manifest);
      } catch (error) {
        jsonResponse(response, 503, {
          error: "找不到模擬結果，請先在專案根目錄執行 python lotto.py loop。",
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
