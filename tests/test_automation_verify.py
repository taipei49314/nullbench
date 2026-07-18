from copy import deepcopy

import pytest

import automation_verify


def _status():
    return {
        "watcher_state": "online",
        "status": "done",
        "last_success_at": "2026-07-18T20:17:12+08:00",
        "consecutive_failures": 0,
    }


def _history():
    return {
        "chain_valid": True,
        "cycles": 2,
        "successes": 2,
        "failures": 0,
    }


def test_stage_commands_cover_automation_and_sync_contract():
    commands = automation_verify.stage_test_commands("python")
    assert [stage for stage, _ in commands] == [
        "automation_core",
        "sync_and_forward_contract",
    ]
    assert all(
        command[:6]
        == ["python", "-B", "-X", "utf8", "-m", "pytest"]
        for _, command in commands
    )


def test_runtime_requires_live_watcher_and_valid_history(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        automation_verify,
        "read_status",
        lambda base: _status(),
    )
    monkeypatch.setattr(
        automation_verify,
        "verify_history",
        lambda base: _history(),
    )

    result = automation_verify.verify_runtime(tmp_path)

    assert result["status"]["watcher_state"] == "online"
    assert result["history"]["successes"] == 2


@pytest.mark.parametrize(
    "status_change,history_change",
    [
        ({"watcher_state": "stopped"}, {}),
        ({"status": "error"}, {}),
        ({"last_success_at": None}, {}),
        ({"consecutive_failures": 2}, {}),
        ({}, {"chain_valid": False}),
        ({}, {"successes": 0}),
    ],
)
def test_runtime_rejects_incomplete_evidence(
    tmp_path,
    monkeypatch,
    status_change,
    history_change,
):
    status = deepcopy(_status())
    history = deepcopy(_history())
    status.update(status_change)
    history.update(history_change)
    monkeypatch.setattr(
        automation_verify,
        "read_status",
        lambda base: status,
    )
    monkeypatch.setattr(
        automation_verify,
        "verify_history",
        lambda base: history,
    )

    with pytest.raises(RuntimeError, match="桌機背景 Loop 驗收失敗"):
        automation_verify.verify_runtime(tmp_path)
