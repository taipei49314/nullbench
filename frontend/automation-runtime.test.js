import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { afterEach, describe, expect, it } from "vitest";

import {
  createSyncCoordinator,
  readAutomationStatus,
} from "./automation-runtime";

const temporaryDirectories = [];

function workspace() {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "lotto-auto-"));
  temporaryDirectories.push(directory);
  return {
    directory,
    statusFile: path.join(directory, "status.json"),
  };
}

function writeStatus(statusFile, payload) {
  fs.writeFileSync(statusFile, JSON.stringify(payload), "utf8");
}

afterEach(() => {
  for (const directory of temporaryDirectories.splice(0)) {
    fs.rmSync(directory, { recursive: true, force: true });
  }
});

describe("desktop automation coordinator", () => {
  it("queues one atomic wake request and waits for its own cycle", () => {
    const { directory, statusFile } = workspace();
    const coordinator = createSyncCoordinator({
      automationDir: directory,
      statusFile,
      isOnline: () => true,
      requestIdFactory: () => "wake-1",
    });

    const queued = coordinator.request();
    const wake = JSON.parse(
      fs.readFileSync(path.join(directory, "wake-request.json"), "utf8"),
    );

    expect(queued).toMatchObject({
      status: "running",
      phase: "queued",
      pending_request_id: "wake-1",
      supervisor_online: true,
    });
    expect(wake.request_id).toBe("wake-1");
    expect(
      fs.readdirSync(directory).filter((name) => name.endsWith(".tmp")),
    ).toEqual([]);
  });

  it("returns live progress then the result after watcher acknowledgement", () => {
    const { directory, statusFile } = workspace();
    const coordinator = createSyncCoordinator({
      automationDir: directory,
      statusFile,
      isOnline: () => true,
      requestIdFactory: () => "wake-2",
    });
    coordinator.request();
    writeStatus(statusFile, {
      status: "running",
      phase: "checking",
      message: "正在比對",
      handled_request_id: "wake-2",
    });

    expect(coordinator.status()).toMatchObject({
      status: "running",
      phase: "checking",
      pending_request_id: null,
    });

    writeStatus(statusFile, {
      status: "done",
      phase: "ready",
      handled_request_id: "wake-2",
      result: { new_draws_total: 1 },
    });
    expect(coordinator.status()).toMatchObject({
      status: "done",
      result: { new_draws_total: 1 },
    });
  });

  it("fails visibly while offline but keeps the wake request for restart", () => {
    const { directory, statusFile } = workspace();
    const coordinator = createSyncCoordinator({
      automationDir: directory,
      statusFile,
      isOnline: () => false,
      requestIdFactory: () => "wake-offline",
    });

    expect(coordinator.request()).toMatchObject({
      status: "error",
      supervisor_online: false,
      pending_request_id: "wake-offline",
    });
    expect(
      JSON.parse(
        fs.readFileSync(
          path.join(directory, "wake-request.json"),
          "utf8",
        ),
      ).request_id,
    ).toBe("wake-offline");
  });

  it("fails closed when the persistent status JSON is corrupt", () => {
    const { statusFile } = workspace();
    fs.writeFileSync(statusFile, "{broken", "utf8");

    expect(readAutomationStatus(statusFile)).toMatchObject({
      status: "error",
      phase: "error",
    });
  });
});
