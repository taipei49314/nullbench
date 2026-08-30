"""Public API / maturity smoke for open-source product surface."""

from __future__ import annotations

import subprocess
import sys

from nullbench import (
    HistoryAnchor,
    OutcomePendingError,
    RegistrationMode,
    SettlementMode,
    __version__,
    add_strategy,
    build_report,
    freeze_last_n,
    freeze_latest,
    freeze_period,
    init_study,
    maturity,
    settle_period,
)
from nullbench.maturity import LEVELS, describe


def test_public_exports_present() -> None:
    assert callable(init_study)
    assert callable(add_strategy)
    assert callable(freeze_period)
    assert callable(freeze_latest)
    assert callable(freeze_last_n)
    assert callable(settle_period)
    assert callable(build_report)
    assert __version__ == "0.9.0"
    assert RegistrationMode.PRE_OUTCOME.value == "pre_outcome"
    assert SettlementMode.LEGACY_BACKTEST.value == "legacy_backtest"
    assert HistoryAnchor(count=0).count == 0
    assert issubclass(OutcomePendingError, Exception)


def test_maturity_m2_frozen() -> None:
    status = describe()
    by_id = {row["id"]: row for row in status.levels}
    assert by_id["M1"]["role"] == "done"
    assert by_id["M2"]["role"] == "frozen"
    assert by_id["M3"]["role"] == "done"
    assert by_id["M4"]["role"] == "done"
    assert LEVELS[2][0] == "M2"
    assert LEVELS[4][0] == "M4"


def test_m1_gate_collects_every_marked_test(monkeypatch, tmp_path) -> None:
    test_dir = tmp_path / "tests"
    test_dir.mkdir()
    captured: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr(maturity, "_repo_tests_dir", lambda: test_dir)
    monkeypatch.setattr(maturity.subprocess, "run", fake_run)

    ok, _log = maturity.run_m1_gate()

    assert ok is True
    assert captured["cmd"] == [
        sys.executable,
        "-m",
        "pytest",
        str(test_dir),
        "-m",
        "m1",
        "-q",
        "--tb=line",
    ]
