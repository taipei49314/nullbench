"""M5.2 prospective settle — draw must enter draws.jsonl after freeze.

NORTH_STAR.md exit: settle proves the draw entered draws.jsonl after the
freeze; evidence is recorded on the ledger row and enforced by the semantic
audit.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nullbench import add_strategy, freeze_period, freeze_prospective, init_study, settle_period
from nullbench.core.hashing import sha256_hex
from nullbench.core.integrity import (
    expected_settle_timing_proof,
    verify_study_semantic,
)
from nullbench.core.pipeline import load_draws
from nullbench.core.study import Study
from nullbench.errors import IntegrityError, SettleError


def _demo_study(root: Path) -> Path:
    init_study(root, experiment_id="m5-settle", domain="demo649")
    add_strategy(root, strategy_id="random", kind="random", tickets=5, seed=1)
    return root


def _append_draw(root: Path, period: str, numbers: list[int]) -> None:
    study = Study(root)
    draws = load_draws(study.draws_path)
    rows = [json.loads(d.model_dump_json()) for d in draws]
    rows.append({"period": period, "numbers": numbers, "special": None, "date": None})
    study.draws_path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _rebuild_chain(rows: list[dict]) -> list[dict]:
    prev = "0" * 64
    rebuilt = []
    for row in rows:
        body = {k: v for k, v in row.items() if k not in ("prev_line_hash", "line_hash")}
        material = {"prev_line_hash": prev, **body}
        digest = sha256_hex(
            json.dumps(material, sort_keys=True, separators=(",", ":"), default=str)
        )
        material["line_hash"] = digest
        prev = digest
        rebuilt.append(material)
    return rebuilt


def _write_ledger(root: Path, rows: list[dict]) -> None:
    rebuilt = _rebuild_chain(rows)
    led = root / "ledger" / "events.jsonl"
    led.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False, default=str) for r in rebuilt) + "\n",
        encoding="utf-8",
    )
    tip = {
        "line_hash": rebuilt[-1]["line_hash"] if rebuilt else "0" * 64,
        "n_lines": len(rebuilt),
        "path": "events.jsonl",
    }
    (root / "ledger" / "events.jsonl.tip").write_text(
        json.dumps(tip, sort_keys=True), encoding="utf-8"
    )


def test_prospective_settle_records_timing_proof(tmp_path: Path) -> None:
    study = _demo_study(tmp_path)
    freeze_prospective(study)  # P0121, 120 known draws
    _append_draw(study, "P0121", [3, 11, 19, 28, 37, 44])
    settle_period(study, "P0121")

    rows = [
        json.loads(ln)
        for ln in Study(study).ledger_path.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    settle = next(r for r in rows if r["type"] == "settle")
    freeze = next(r for r in rows if r["type"] == "freeze")
    assert settle["schema_version"] == "2"
    assert settle["draw_entered_after_freeze"] is True
    assert settle["known_draws_at_freeze"] == 120
    assert settle["known_draws_at_settle"] == 121
    assert settle["freeze_line_hashes"] == [freeze["line_hash"]]
    assert freeze["outcome_hash"] is None
    ok, issues = verify_study_semantic(study)
    assert ok, issues


def test_replay_settle_does_not_claim_after(tmp_path: Path) -> None:
    study = _demo_study(tmp_path)
    freeze_period(study, "P0120")
    recs = settle_period(study, "P0120")
    assert recs[0].draw_entered_after_freeze is False
    assert recs[0].known_draws_at_freeze is None
    assert recs[0].known_draws_at_settle == 120
    assert recs[0].freeze_line_hashes
    ok, issues = verify_study_semantic(study)
    assert ok, issues


def test_prospective_settle_refuses_when_draws_did_not_grow(tmp_path: Path) -> None:
    """Replace an existing draw's period instead of appending — count stays 120."""
    study = _demo_study(tmp_path)
    freeze_prospective(study, "P0121")
    path = Study(study).draws_path
    lines = [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    lines[-1]["period"] = "P0121"
    path.write_text("\n".join(json.dumps(r) for r in lines) + "\n", encoding="utf-8")
    with pytest.raises(SettleError) as ei:
        settle_period(study, "P0121")
    msg = str(ei.value).lower()
    assert "history" in msg or "m5.2" in msg or "did not enter" in msg


def test_expected_proof_unit_prospective_and_replay(tmp_path: Path) -> None:
    study = _demo_study(tmp_path)
    freeze_prospective(study)
    draws = load_draws(Study(study).draws_path)
    freezes = Study(study).ledger().events_of("freeze")
    with pytest.raises(IntegrityError, match="no draw yet"):
        expected_settle_timing_proof(freezes, draws, "P0121")
    _append_draw(study, "P0121", [1, 2, 3, 4, 5, 6])
    draws = load_draws(Study(study).draws_path)
    proof = expected_settle_timing_proof(freezes, draws, "P0121")
    assert proof["draw_entered_after_freeze"] is True
    assert proof["known_draws_at_freeze"] == 120
    assert proof["known_draws_at_settle"] == 121


@pytest.mark.m1
def test_m1_stripping_prospective_settle_proof_fails_audit(tmp_path: Path) -> None:
    """Adversarial (M5.2): chain-relinked settle that drops the after-freeze
    proof must fail the semantic audit."""
    study = _demo_study(tmp_path)
    freeze_prospective(study)
    _append_draw(study, "P0121", [3, 11, 19, 28, 37, 44])
    settle_period(study, "P0121")
    rows = [
        json.loads(ln)
        for ln in Study(study).ledger_path.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    for r in rows:
        if r.get("type") == "settle":
            r["draw_entered_after_freeze"] = False
            r.pop("freeze_line_hashes", None)
            r.pop("known_draws_at_freeze", None)
            r.pop("known_draws_at_settle", None)
    _write_ledger(study, rows)
    ok_chain, _ = Study(study).ledger().verify_chain()
    assert ok_chain
    ok, issues = verify_study_semantic(study)
    assert not ok
    assert any("M5.2" in i and "draw_entered_after_freeze" in i for i in issues)


@pytest.mark.m1
def test_m1_replay_cannot_claim_draw_entered_after_freeze(tmp_path: Path) -> None:
    """Adversarial (M5.2): a replay settle claiming prospective timing is a lie."""
    study = _demo_study(tmp_path)
    freeze_period(study, "P0120")
    settle_period(study, "P0120")
    rows = [
        json.loads(ln)
        for ln in Study(study).ledger_path.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    for r in rows:
        if r.get("type") == "settle":
            r["draw_entered_after_freeze"] = True
    _write_ledger(study, rows)
    ok_chain, _ = Study(study).ledger().verify_chain()
    assert ok_chain
    ok, issues = verify_study_semantic(study)
    assert not ok
    assert any("replay settle cannot claim" in i for i in issues)
