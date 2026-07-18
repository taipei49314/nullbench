import { randomUUID } from "node:crypto";
import fs from "node:fs";
import path from "node:path";

const DEFAULT_STATUS = {
  schema_version: "1",
  status: "idle",
  phase: "idle",
  message: "等待背景 Loop 啟動",
  watcher_state: "unknown",
  handled_request_id: null,
  consecutive_failures: 0,
  result: null,
  error: "",
};

export function readAutomationStatus(statusFile) {
  if (!fs.existsSync(statusFile)) return { ...DEFAULT_STATUS };
  try {
    return {
      ...DEFAULT_STATUS,
      ...JSON.parse(fs.readFileSync(statusFile, "utf8")),
    };
  } catch (error) {
    return {
      ...DEFAULT_STATUS,
      status: "error",
      phase: "error",
      message: "背景 Loop 狀態檔毀損",
      error: error.message,
    };
  }
}

export function writeWakeRequest(
  automationDir,
  requestId = randomUUID().replaceAll("-", ""),
) {
  fs.mkdirSync(automationDir, { recursive: true });
  const payload = {
    schema_version: "1",
    request_id: requestId,
    requested_at: new Date().toISOString(),
  };
  const target = path.join(automationDir, "wake-request.json");
  const temporary = path.join(
    automationDir,
    `.wake-request.${process.pid}.${requestId}.tmp`,
  );
  fs.writeFileSync(temporary, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
  fs.renameSync(temporary, target);
  return payload;
}

export function createSyncCoordinator({
  automationDir,
  statusFile,
  isOnline,
  requestIdFactory = () => randomUUID().replaceAll("-", ""),
}) {
  let pendingRequestId = null;

  const status = () => {
    const current = readAutomationStatus(statusFile);
    const supervisorOnline = Boolean(isOnline());
    if (
      pendingRequestId &&
      current.handled_request_id !== pendingRequestId
    ) {
      if (!supervisorOnline) {
        return {
          ...current,
          status: "error",
          phase: "error",
          message: "背景 Loop 監督程序離線",
          error: "桌機伺服器正在重新啟動背景 Loop，稍後會自動重試。",
          supervisor_online: false,
          pending_request_id: pendingRequestId,
        };
      }
      return {
        ...current,
        status: "running",
        phase: "queued",
        message: "已喚醒背景 Loop，等待目前交易完成",
        error: "",
        supervisor_online: true,
        pending_request_id: pendingRequestId,
      };
    }
    if (
      pendingRequestId &&
      current.handled_request_id === pendingRequestId
    ) {
      pendingRequestId = null;
    }
    return {
      ...current,
      supervisor_online: supervisorOnline,
      pending_request_id: pendingRequestId,
    };
  };

  const request = () => {
    const current = readAutomationStatus(statusFile);
    if (
      pendingRequestId &&
      current.handled_request_id !== pendingRequestId
    ) {
      return status();
    }
    pendingRequestId = requestIdFactory();
    writeWakeRequest(automationDir, pendingRequestId);
    return status();
  };

  return { request, status };
}
