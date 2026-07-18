"""一鍵正式研究入口測試。"""
from copy import deepcopy
import subprocess

import pytest

import research_verify


def _formal_study():
    return {
        "replicates": 8,
        "bootstrap_samples": 1_000,
        "stage_gates": {
            name: {"status": "pass"}
            for name in research_verify.REQUIRED_GATES
        },
        "records_integrity": {
            "unchanged": True,
            "before_sha256": "a" * 64,
            "after_sha256": "a" * 64,
        },
        "decision": {"economic": "no_play"},
    }


def test_stage_commands_cover_every_gate_and_use_pytest():
    commands = research_verify.stage_test_commands("python")
    assert [stage for stage, _ in commands] == list(
        research_verify.REQUIRED_GATES
    )
    for stage, command in commands:
        assert command[:6] == ["python", "-B", "-X", "utf8", "-m", "pytest"]
        assert f"tests/test_research_{stage}.py" in command
        assert command[-3:] == ["-q", "-p", "no:cacheprovider"]


def test_formal_study_accepts_only_all_green_full_configuration():
    research_verify.verify_formal_study(_formal_study())


@pytest.mark.parametrize(
    "mutation",
    [
        lambda study: study.update({"replicates": 2}),
        lambda study: study.update({"bootstrap_samples": 20}),
        lambda study: study["stage_gates"]["strategy_search"].update(
            {"status": "fail"}
        ),
        lambda study: study["records_integrity"].update({"unchanged": False}),
        lambda study: study["decision"].update({"economic": "buy"}),
    ],
)
def test_formal_study_rejects_underpowered_or_failed_result(mutation):
    study = _formal_study()
    mutation(study)
    with pytest.raises(RuntimeError, match="正式研究驗收失敗"):
        research_verify.verify_formal_study(study)


def test_tests_only_runs_stage_full_and_diff_checks(monkeypatch):
    calls = []
    monkeypatch.setattr(
        research_verify,
        "_run",
        lambda command: calls.append(command),
    )
    assert research_verify.main(["--tests-only"]) == 0
    assert len(calls) == len(research_verify.STAGE_TESTS) + 2
    assert not any("research_backtest.py" in command for command in calls)
    assert calls[-1] == ["git", "diff", "--check"]


def test_run_failure_propagates_and_stops(monkeypatch):
    calls = []

    def fail_first(command):
        calls.append(command)
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(research_verify, "_run", fail_first)
    with pytest.raises(subprocess.CalledProcessError):
        research_verify.main(["--tests-only"])
    assert len(calls) == 1
