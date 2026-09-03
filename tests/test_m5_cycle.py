"""M5.3 cycle command — ingest → settle pending → freeze next → notarize → report."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nullbench import add_strategy, cycle_study, freeze_prospective, init_study
from nullbench.core.integrity import verify_study_semantic
from nullbench.core.pipeline import load_draws
from nullbench.core.study import Study
from nullbench.core.vault import Vault
from nullbench.errors import VaultError


def _demo_study(root: Path) -> Path:
    init_study(root, experiment_id="m5-cycle", domain="demo649")
    add_strategy(root, strategy_id="random", kind="random", tickets=5, seed=1)
    return root


def _append_draw(root: Path, period: str, numbers: list[int]) -> None:
    study = Study(root)
    draws = load_draws(study.draws_path)
    rows = [json.loads(d.model_dump_json()) for d in draws]
    rows.append({"period": period, "numbers": numbers, "special": None, "date": None})
    study.draws_path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def test_cycle_refuses_without_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NULLBENCH_VAULT_DIR", str(tmp_path / "no-vault"))
    study = _demo_study(tmp_path)
    with pytest.raises(VaultError, match="no vault"):
        cycle_study(study)


def test_cycle_first_pass_freezes_next_skips_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NULLBENCH_VAULT_DIR", str(tmp_path / "no-vault"))
    study = _demo_study(tmp_path)
    result = cycle_study(study, allow_unnotarized=True)
    assert result["ingested"] is None
    assert result["settled_periods"] == []
    assert result["frozen_period"] == "P0121"
    assert result["frozen_arms"] == 1
    assert result["notarized"] is False
    assert result["reported"] is False
    assert any("ingest:" in s for s in result["skipped"])
    assert any("report:" in s for s in result["skipped"])
    assert any("notarize:" in s for s in result["skipped"])
    ok, issues = verify_study_semantic(study)
    assert ok, issues


def test_cycle_settles_after_draw_then_freezes_next(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NULLBENCH_VAULT_DIR", str(tmp_path / "no-vault"))
    study = _demo_study(tmp_path)
    freeze_prospective(study)  # P0121 pending
    _append_draw(study, "P0121", [3, 11, 19, 28, 37, 44])
    result = cycle_study(study, allow_unnotarized=True)
    assert result["settled_periods"] == ["P0121"]
    assert result["frozen_period"] == "P0122"
    assert result["reported"] is True
    ok, issues = verify_study_semantic(study)
    assert ok, issues
    settles = [e for e in Study(study).ledger().events_of("settle") if e["period"] == "P0121"]
    assert settles[0]["draw_entered_after_freeze"] is True
    report = (Study(study).reports_dir / "latest.md").read_text(encoding="utf-8")
    assert "PROSPECTIVE SETTLE" in report


def test_cycle_notarizes_when_vault_exists(tmp_path: Path) -> None:
    study = _demo_study(tmp_path)
    vault = Vault(tmp_path / "vault")
    vault.init()
    result = cycle_study(study, vault=vault)
    assert result["notarized"] is True
    assert result["receipt_id"]
    assert (Study(study).root / "vault" / "latest_receipt.json").is_file()


def test_cycle_skips_undrawn_pending_instead_of_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NULLBENCH_VAULT_DIR", str(tmp_path / "no-vault"))
    study = _demo_study(tmp_path)
    freeze_prospective(study, "P0130")  # far future
    result = cycle_study(study, allow_unnotarized=True)
    assert result["settled_periods"] == []
    assert any("settle P0130: waiting for draw" in s for s in result["skipped"])
    # Latest known draw is still P0120 → next freeze is P0121 (already not P0130).
    assert result["frozen_period"] == "P0121"
