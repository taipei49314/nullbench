"""M5.1 prospective freeze — the north-star mode (NORTH_STAR.md).

Contract: freeze a period whose draw does not exist yet. The period must be
absent from draws.jsonl, outcome_hash stays null, late stays false, and the
history seal covers every draw known at freeze time.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nullbench import add_strategy, build_report, freeze_prospective, init_study, settle_period
from nullbench.core.integrity import verify_study_semantic
from nullbench.core.pipeline import _next_period_id, freeze_period, load_draws
from nullbench.core.study import Study
from nullbench.errors import FreezeError


def _demo_study(root: Path) -> Path:
    init_study(root, experiment_id="m5-prospective", domain="demo649")
    add_strategy(root, strategy_id="random", kind="random", tickets=5, seed=1)
    return root


def _append_draw(root: Path, period: str, numbers: list[int]) -> None:
    study = Study(root)
    draws = load_draws(study.draws_path)
    rows = [json.loads(d.model_dump_json()) for d in draws]
    rows.append({"period": period, "numbers": numbers, "special": None, "date": None})
    study.draws_path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def test_next_period_id_derivation() -> None:
    assert _next_period_id("P0120") == "P0121"
    assert _next_period_id("114000041") == "114000042"
    assert _next_period_id("2026-09-04") is None


def test_prospective_freeze_contract(tmp_path: Path) -> None:
    study = _demo_study(tmp_path)
    records = freeze_prospective(study)  # derives P0121 from latest P0120
    assert [r.period for r in records] == ["P0121"]
    for rec in records:
        assert rec.outcome_hash is None, "prospective freeze must not seal an outcome"
        assert rec.late is False
        assert rec.schema_version == "3"
        assert rec.meta["prospective"] is True
        assert rec.meta["known_draws_at_freeze"] == 120  # every known draw is history


def test_prospective_freeze_rejects_drawn_period(tmp_path: Path) -> None:
    study = _demo_study(tmp_path)
    with pytest.raises(FreezeError, match="replay"):
        freeze_prospective(study, "P0120")  # this draw already exists


def test_prospective_roundtrip_settle_and_clean_audit(tmp_path: Path) -> None:
    study = _demo_study(tmp_path)
    freeze_prospective(study)  # P0121 frozen before its draw exists
    # The draw arrives later (ingest):
    _append_draw(study, "P0121", [3, 11, 19, 28, 37, 44])

    ok, issues = verify_study_semantic(study)
    assert ok, issues

    settles = settle_period(study, "P0121")
    assert len(settles) == 1
    ok, issues = verify_study_semantic(study)
    assert ok, issues

    summary = build_report(study)
    assert any(w.startswith("PROSPECTIVE:") for w in summary.warnings)
    assert not any(w.startswith("REPLAY:") for w in summary.warnings)


def test_prospective_pending_audit_fails_when_history_grows(tmp_path: Path) -> None:
    study = _demo_study(tmp_path)
    freeze_prospective(study, "P0130")  # far-future period
    # A draw that is NOT the target arrives while P0130 is still pending —
    # the seal no longer covers all known draws → fail-closed.
    _append_draw(study, "P0121", [1, 2, 3, 4, 5, 6])
    ok, issues = verify_study_semantic(study)
    assert not ok
    assert any("history_hash drift" in i for i in issues)


def test_coach_waits_for_draw(tmp_path: Path) -> None:
    from nullbench.core.workspace import next_actions

    study = _demo_study(tmp_path)
    freeze_prospective(study)  # P0121 pending
    actions = next_actions(study)
    assert any("waiting for draw" in a for a in actions)


@pytest.mark.m1
def test_m1_v3_row_cannot_lie_about_late(tmp_path: Path) -> None:
    """Adversarial (M5.1 / R-05): a v3 freeze row with late contradicting
    outcome_hash must fail the semantic audit, even with a valid chain."""
    study = _demo_study(tmp_path)
    freeze_period(study, "P0120")  # replay: outcome sealed, late=true
    ledger_path = Study(study).ledger_path
    rows = [json.loads(ln) for ln in ledger_path.read_text(encoding="utf-8").splitlines() if ln]
    row = next(r for r in rows if r["type"] == "freeze")
    row["late"] = False  # forge: claim the sealed-outcome freeze was prospective

    # Rewrite ledger + tip consistently (A2 attacker with file write):
    import hashlib

    prev = "0" * 64
    new_rows = []
    for r in rows:
        body = {k: v for k, v in r.items() if k not in ("prev_line_hash", "line_hash")}
        if body is r:
            body = dict(r)
            body.pop("prev_line_hash", None)
            body.pop("line_hash", None)
        material = {"prev_line_hash": prev, **body}
        digest = hashlib.sha256(
            json.dumps(material, sort_keys=True, separators=(",", ":"), default=str).encode()
        ).hexdigest()
        new_rows.append({**material, "line_hash": digest})
        prev = digest
    ledger_path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False, default=str) for r in new_rows) + "\n",
        encoding="utf-8",
    )
    tip = {"line_hash": prev, "n_lines": len(new_rows), "path": ledger_path.name}
    ledger_path.with_suffix(".jsonl.tip").write_text(
        json.dumps(tip, sort_keys=True), encoding="utf-8"
    )

    # Chain is green; the semantic audit must still catch the lie.
    ok_chain, _ = Study(study).ledger().verify_chain()
    assert ok_chain
    ok, issues = verify_study_semantic(study)
    assert not ok
    assert any("late/outcome_hash inconsistency" in i for i in issues)
