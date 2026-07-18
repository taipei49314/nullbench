"""桌機版無人值守同步 Loop。

Vite 桌機伺服器會監督一個 ``python lotto.py watch`` 程序。watcher 即使沒有
瀏覽器分頁，也會定期呼叫官方同步；頁面只會寫入一個 wake request，要求它提早
執行下一輪。

所有同步入口共用 OS 檔案鎖，所以 watcher、CLI 與頁面不會同時改寫模擬帳本。
每輪狀態以原子 replace 寫入，結果另存 append-only 雜湊鏈，程序中斷後可以從
最後一次成功狀態繼續。
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from .ledger import Ledger, TAIPEI, now_iso
from .sync_service import sync_latest


AUTOMATION_SCHEMA_VERSION = "1"
DEFAULT_INTERVAL_SECONDS = 5 * 60
DEFAULT_RETRY_SECONDS = 30
MAX_RETRY_SECONDS = 30 * 60
BUSY_RETRY_SECONDS = 5
HEARTBEAT_SECONDS = 10


class SyncBusy(RuntimeError):
    """另一個程序正在執行同一個同步交易。"""


def _canonical_hash(payload: dict) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def automation_dir(base: Path) -> Path:
    return Path(base) / "simulation" / "automation"


def status_path(base: Path) -> Path:
    return automation_dir(base) / "status.json"


def request_path(base: Path) -> Path:
    return automation_dir(base) / "wake-request.json"


def history_path(base: Path) -> Path:
    return automation_dir(base) / "history.jsonl"


def _default_status() -> dict:
    return {
        "schema_version": AUTOMATION_SCHEMA_VERSION,
        "status": "idle",
        "phase": "idle",
        "message": "等待背景 Loop 啟動",
        "watcher_state": "unknown",
        "watcher_pid": None,
        "heartbeat_at": None,
        "cycle_id": None,
        "cycle_started_at": None,
        "last_checked_at": None,
        "last_success_at": None,
        "next_check_at": None,
        "handled_request_id": None,
        "consecutive_failures": 0,
        "result": None,
        "error": "",
    }


def read_status(base: Path) -> dict:
    path = status_path(base)
    if not path.exists():
        return _default_status()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            **_default_status(),
            "status": "error",
            "phase": "error",
            "message": "背景 Loop 狀態檔毀損",
            "error": f"無法解析 {path}",
        }
    return {**_default_status(), **payload}


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temp, path)


def write_status(base: Path, payload: dict) -> dict:
    normalized = {
        **_default_status(),
        **payload,
        "schema_version": AUTOMATION_SCHEMA_VERSION,
    }
    _atomic_json(status_path(base), normalized)
    return normalized


def write_wake_request(
    base: Path,
    *,
    request_id: str | None = None,
    requested_at: str | None = None,
) -> dict:
    payload = {
        "schema_version": AUTOMATION_SCHEMA_VERSION,
        "request_id": request_id or uuid.uuid4().hex,
        "requested_at": requested_at or now_iso(),
    }
    _atomic_json(request_path(base), payload)
    return payload


def read_wake_request(base: Path) -> dict | None:
    path = request_path(base)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not payload.get("request_id"):
        return None
    return payload


class SyncLock:
    """跨平台、程序死亡即自動釋放的非阻塞檔案鎖。"""

    def __init__(self, base: Path):
        self.path = automation_dir(base) / "sync.lock"
        self.handle = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, "a+b")
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(
                    handle.fileno(),
                    fcntl.LOCK_EX | fcntl.LOCK_NB,
                )
        except (OSError, BlockingIOError):
            handle.close()
            return False
        self.handle = handle
        return True

    def release(self) -> None:
        if self.handle is None:
            return
        try:
            self.handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()
            self.handle = None

    def __enter__(self):
        if not self.acquire():
            raise SyncBusy("另一個同步交易仍在執行")
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.release()
        return False


def verify_history(base: Path) -> dict:
    ledger = Ledger(history_path(base))
    if not ledger.verify_chain():
        raise ValueError("自動化執行歷史雜湊鏈中斷")
    events = ledger.events_of("automation_cycle")
    for event in events:
        content = event.get("content")
        if not isinstance(content, dict):
            raise ValueError("自動化執行事件缺少 content")
        if event.get("content_hash") != _canonical_hash(content):
            raise ValueError("自動化執行事件 content_hash 不符")
    return {
        "chain_valid": True,
        "cycles": len(events),
        "successes": sum(
            event["content"]["outcome"] == "success" for event in events
        ),
        "failures": sum(
            event["content"]["outcome"] == "error" for event in events
        ),
    }


def _append_history(base: Path, content: dict) -> dict:
    ledger = Ledger(history_path(base))
    event = ledger.append(
        "automation_cycle",
        {
            "content": content,
            "content_hash": _canonical_hash(content),
        },
    )
    verify_history(base)
    return event


def _wait_for_lock(
    lock: SyncLock,
    *,
    wait_seconds: float,
    sleeper: Callable[[float], None],
) -> None:
    deadline = time.monotonic() + max(0.0, wait_seconds)
    while not lock.acquire():
        if time.monotonic() >= deadline:
            raise SyncBusy("另一個同步交易仍在執行")
        sleeper(min(0.1, max(0.0, deadline - time.monotonic())))


def _history_result(result: dict) -> dict:
    return {
        "new_draws_total": result.get("new_draws_total"),
        "regenerated": result.get("regenerated"),
        "manifest_hash": result.get("manifest_hash"),
        "forward_experiment": result.get("forward_experiment"),
        "shadow_research": result.get("shadow_research"),
    }


def run_sync_cycle(
    base: Path,
    *,
    syncer=sync_latest,
    progress: Callable[[str, str, dict | None], None] | None = None,
    request_id: str | None = None,
    lock_wait_seconds: float = 0,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict:
    """在單一跨程序交易中執行一次同步並持久化結果。"""
    base = Path(base)
    lock = SyncLock(base)
    _wait_for_lock(
        lock,
        wait_seconds=lock_wait_seconds,
        sleeper=sleeper,
    )
    previous = read_status(base)
    cycle_id = uuid.uuid4().hex
    started_at = now_iso()
    handled_request_id = request_id or previous.get("handled_request_id")
    running = write_status(
        base,
        {
            **previous,
            "status": "running",
            "phase": "starting",
            "message": "背景 Loop 正在啟動同步",
            "cycle_id": cycle_id,
            "cycle_started_at": started_at,
            "heartbeat_at": started_at,
            "handled_request_id": handled_request_id,
            "error": "",
        },
    )

    def on_progress(
        phase: str,
        message: str,
        details: dict | None,
    ) -> None:
        nonlocal running
        running = write_status(
            base,
            {
                **running,
                "status": "running",
                "phase": phase,
                "message": message,
                "heartbeat_at": now_iso(),
                "details": details,
            },
        )
        if progress is not None:
            progress(phase, message, details)

    try:
        result = syncer(base, progress=on_progress)
    except Exception as error:
        finished_at = now_iso()
        failures = int(previous.get("consecutive_failures", 0)) + 1
        failed = write_status(
            base,
            {
                **running,
                "status": "error",
                "phase": "error",
                "message": "背景 Loop 同步失敗，將自動重試",
                "last_checked_at": finished_at,
                "heartbeat_at": finished_at,
                "consecutive_failures": failures,
                "error": f"{type(error).__name__}: {error}",
                "result": None,
                "details": None,
            },
        )
        _append_history(
            base,
            {
                "schema_version": AUTOMATION_SCHEMA_VERSION,
                "cycle_id": cycle_id,
                "request_id": request_id,
                "started_at": started_at,
                "finished_at": finished_at,
                "outcome": "error",
                "error": failed["error"],
            },
        )
        raise
    else:
        finished_at = now_iso()
        completed = write_status(
            base,
            {
                **running,
                "status": "done",
                "phase": "ready",
                "message": (
                    "新開獎已完成檢討並凍結下一期"
                    if result.get("new_draws_total", 0) > 0
                    else "官方資料無新增，前向登記仍有效"
                ),
                "last_checked_at": finished_at,
                "last_success_at": finished_at,
                "heartbeat_at": finished_at,
                "consecutive_failures": 0,
                "error": "",
                "result": result,
                "details": None,
            },
        )
        _append_history(
            base,
            {
                "schema_version": AUTOMATION_SCHEMA_VERSION,
                "cycle_id": cycle_id,
                "request_id": request_id,
                "started_at": started_at,
                "finished_at": finished_at,
                "outcome": "success",
                "result": _history_result(result),
            },
        )
        return completed
    finally:
        lock.release()


def retry_delay(
    consecutive_failures: int,
    *,
    base_seconds: int = DEFAULT_RETRY_SECONDS,
    maximum_seconds: int = MAX_RETRY_SECONDS,
) -> int:
    if consecutive_failures <= 0:
        return base_seconds
    return min(
        maximum_seconds,
        base_seconds * (2 ** (consecutive_failures - 1)),
    )


def _future_iso(seconds: float) -> str:
    return (
        datetime.now(TAIPEI) + timedelta(seconds=max(0.0, seconds))
    ).isoformat(timespec="seconds")


def watch_forever(
    base: Path,
    *,
    interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
    syncer=sync_latest,
    once: bool = False,
    should_stop: Callable[[], bool] | None = None,
    waiter: Callable[[float], None] = time.sleep,
) -> dict:
    """持續同步；成功後固定間隔，失敗後指數退避。"""
    if interval_seconds < 1:
        raise ValueError("interval_seconds 必須至少為 1")
    base = Path(base)
    should_stop = should_stop or (lambda: False)
    watcher_started_at = now_iso()
    current = read_status(base)
    current = write_status(
        base,
        {
            **current,
            "watcher_state": "online",
            "watcher_pid": os.getpid(),
            "watcher_started_at": watcher_started_at,
            "heartbeat_at": watcher_started_at,
            "message": "背景 Loop 已上線，準備同步",
        },
    )
    next_due = 0.0
    last_heartbeat = 0.0

    while not should_stop():
        # CLI 可能在 watcher 休眠時完成一輪；每次都以持久狀態為準，
        # 避免把已處理的 wake request 再跑一次。
        current = read_status(base)
        now_monotonic = time.monotonic()
        request = read_wake_request(base)
        request_id = request.get("request_id") if request else None
        pending_request = (
            bool(request_id)
            and request_id != current.get("handled_request_id")
        )
        if pending_request or now_monotonic >= next_due:
            try:
                current = run_sync_cycle(
                    base,
                    syncer=syncer,
                    request_id=request_id if pending_request else None,
                )
            except SyncBusy:
                delay = BUSY_RETRY_SECONDS
            except Exception:
                current = read_status(base)
                delay = retry_delay(
                    int(current.get("consecutive_failures", 1))
                )
            else:
                delay = interval_seconds
            next_due = time.monotonic() + delay
            current = write_status(
                base,
                {
                    **read_status(base),
                    "watcher_state": "online",
                    "watcher_pid": os.getpid(),
                    "watcher_started_at": watcher_started_at,
                    "heartbeat_at": now_iso(),
                    "next_check_at": _future_iso(delay),
                },
            )
            last_heartbeat = time.monotonic()
            if once:
                return current
            continue

        if now_monotonic - last_heartbeat >= HEARTBEAT_SECONDS:
            current = write_status(
                base,
                {
                    **read_status(base),
                    "watcher_state": "online",
                    "watcher_pid": os.getpid(),
                    "watcher_started_at": watcher_started_at,
                    "heartbeat_at": now_iso(),
                    "next_check_at": _future_iso(next_due - now_monotonic),
                },
            )
            last_heartbeat = now_monotonic
        waiter(min(1.0, max(0.0, next_due - time.monotonic())))

    stopped = write_status(
        base,
        {
            **read_status(base),
            "watcher_state": "stopped",
            "heartbeat_at": now_iso(),
            "message": "背景 Loop 已停止",
        },
    )
    return stopped
