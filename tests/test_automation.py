import json

import pytest

from engine import automation


def _sync_result(new_draws=0):
    return {
        "new_draws_total": new_draws,
        "regenerated": new_draws > 0,
        "manifest_hash": "manifest-sha",
        "forward_experiment": {
            "evidence_status": "collecting_forward_data",
        },
        "games": {},
    }


def test_sync_cycle_persists_progress_success_and_hash_chain(tmp_path):
    phases = []

    def syncer(base, progress):
        progress("checking", "比對官方資料", None)
        progress("preregistering", "凍結下一期", {"count": 2})
        return _sync_result(1)

    state = automation.run_sync_cycle(
        tmp_path,
        syncer=syncer,
        progress=lambda phase, message, details: phases.append(phase),
        request_id="request-1",
    )

    assert state["status"] == "done"
    assert state["phase"] == "ready"
    assert state["handled_request_id"] == "request-1"
    assert state["consecutive_failures"] == 0
    assert state["result"]["new_draws_total"] == 1
    assert phases == ["checking", "preregistering"]
    assert automation.verify_history(tmp_path) == {
        "chain_valid": True,
        "cycles": 1,
        "successes": 1,
        "failures": 0,
    }


def test_sync_cycle_records_failure_and_next_success_recovers(tmp_path):
    def broken_syncer(base, progress):
        progress("checking", "開始", None)
        raise ConnectionError("offline")

    with pytest.raises(ConnectionError, match="offline"):
        automation.run_sync_cycle(tmp_path, syncer=broken_syncer)

    failed = automation.read_status(tmp_path)
    assert failed["status"] == "error"
    assert failed["consecutive_failures"] == 1
    assert "ConnectionError: offline" in failed["error"]

    recovered = automation.run_sync_cycle(
        tmp_path,
        syncer=lambda base, progress: _sync_result(),
    )
    assert recovered["status"] == "done"
    assert recovered["consecutive_failures"] == 0
    assert automation.verify_history(tmp_path)["cycles"] == 2


def test_sync_lock_prevents_overlapping_writers(tmp_path):
    first = automation.SyncLock(tmp_path)
    assert first.acquire() is True
    try:
        with pytest.raises(automation.SyncBusy):
            automation.run_sync_cycle(
                tmp_path,
                syncer=lambda base, progress: _sync_result(),
            )
    finally:
        first.release()

    assert not automation.history_path(tmp_path).exists()


def test_wake_request_is_atomic_and_readable(tmp_path):
    request = automation.write_wake_request(
        tmp_path,
        request_id="wake-123",
        requested_at="2026-07-18T20:00:00+08:00",
    )
    assert automation.read_wake_request(tmp_path) == request
    assert not list(
        automation.automation_dir(tmp_path).glob("*.tmp")
    )


def test_status_reader_fails_closed_on_corrupt_json(tmp_path):
    path = automation.status_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("{broken", encoding="utf-8")

    state = automation.read_status(tmp_path)

    assert state["status"] == "error"
    assert state["phase"] == "error"
    assert "毀損" in state["message"]


def test_retry_delay_is_bounded_exponential_backoff():
    assert automation.retry_delay(1) == 30
    assert automation.retry_delay(2) == 60
    assert automation.retry_delay(6) == 960
    assert automation.retry_delay(20) == 1800


def test_watch_once_runs_without_browser_and_sets_next_check(tmp_path):
    calls = []

    def syncer(base, progress):
        calls.append(base)
        progress("checking", "背景檢查", None)
        return _sync_result()

    state = automation.watch_forever(
        tmp_path,
        interval_seconds=37,
        syncer=syncer,
        once=True,
    )

    assert calls == [tmp_path]
    assert state["watcher_state"] == "online"
    assert state["watcher_pid"]
    assert state["next_check_at"]
    assert state["status"] == "done"


def test_history_content_tampering_is_detected(tmp_path):
    automation.run_sync_cycle(
        tmp_path,
        syncer=lambda base, progress: _sync_result(),
    )
    path = automation.history_path(tmp_path)
    event = json.loads(path.read_text(encoding="utf-8").strip())
    event["content"]["outcome"] = "error"
    path.write_text(
        json.dumps(event, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="content_hash"):
        automation.verify_history(tmp_path)
