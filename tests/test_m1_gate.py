"""M1 product gate — adversarial IC-01..08 must stay green.

Run: pytest -m m1 -q
     nullbench maturity --check-m1
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nullbench.core import pipeline
from nullbench.core.claims import assert_clean, scan_forbidden
from nullbench.core.hashing import sha256_hex
from nullbench.core.integrity import (
    code_fingerprint,
    experiment_hash,
    history_before,
    verify_freeze_row,
    verify_study_semantic,
)
from nullbench.core.models import Draw
from nullbench.core.study import Study
from nullbench.errors import SettleError
from nullbench.report.html import _safe_script_json

pytestmark = pytest.mark.m1


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
    (root / "ledger" / "events.jsonl.tip").write_text(json.dumps(tip), encoding="utf-8")


def _fresh(tmp_path: Path, n: int = 25) -> tuple[Path, str]:
    root = tmp_path / "m1"
    pipeline.init_study(root, experiment_id="m1", domain="demo649", demo_draws=n)
    pipeline.add_strategy(root, strategy_id="random", kind="random", tickets=2, seed=1)
    draws = pipeline.load_draws(root / "data" / "draws.jsonl")
    p = draws[-1].period
    pipeline.freeze_period(root, p, backtest=True)
    return root, p


def test_m1_seal_experiment_and_freeze_hashes(tmp_path: Path) -> None:
    root, p = _fresh(tmp_path)
    spec = Study(root).load_experiment()
    exp_h = experiment_hash(spec)
    freezes = [e for e in Study(root).ledger().events_of("freeze") if e.get("period") == p]
    assert freezes
    for fr in freezes:
        assert fr.get("schema_version") == "3"
        assert fr.get("registration_mode") == "backtest"
        assert fr.get("late") is True
        assert fr.get("experiment_hash") == exp_h
        assert fr.get("history_hash")
        assert fr.get("history_anchor")
        assert fr.get("content_hash")
        assert fr.get("outcome_hash")
        verify_freeze_row(fr)


def test_m1_ic01_forged_payout_semantic_fail(tmp_path: Path) -> None:
    root, p = _fresh(tmp_path)
    pipeline.settle_period(root, p)
    rows = [
        json.loads(x)
        for x in (root / "ledger" / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if x.strip()
    ]
    for r in rows:
        if r.get("type") == "settle":
            for s in r.get("strategy_results", []):
                s["payout"] = 999999.0
    _write_ledger(root, rows)
    assert Study(root).ledger().verify_chain()[0] is True
    ok, issues = verify_study_semantic(root)
    assert ok is False
    assert any("payout" in i or "IC-01" in i for i in issues)


def test_m1_ic02_settle_rejects_tampered_tickets(tmp_path: Path) -> None:
    root, p = _fresh(tmp_path)
    rows = [
        json.loads(x)
        for x in (root / "ledger" / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if x.strip()
    ]
    for r in rows:
        if r.get("type") == "freeze":
            r["tickets"][0]["numbers"] = [1, 2, 3, 4, 5, 6]
    _write_ledger(root, rows)
    with pytest.raises(SettleError):
        pipeline.settle_period(root, p)


def test_m1_ic03_outcome_pin(tmp_path: Path) -> None:
    root, p = _fresh(tmp_path)
    path = root / "data" / "draws.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    last = json.loads(lines[-1])
    last["numbers"] = [1, 2, 3, 4, 5, 6]
    lines[-1] = json.dumps(last)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(SettleError):
        pipeline.settle_period(root, p)


def test_m1_ic04_history_order(tmp_path: Path) -> None:
    a = Draw(period="A", numbers=[1, 2, 3, 4, 5, 7], date="2020-01-01")
    b = Draw(period="B", numbers=[1, 2, 3, 4, 5, 6], date="2020-02-01")
    c = Draw(period="C", numbers=[1, 2, 3, 4, 5, 8], date="2020-03-01")
    # File order puts C first — naive scan yields empty history (look-ahead bug)
    file_order = [c, b, a]

    def naive(draws, period):
        out = []
        for d in draws:
            if d.period == period:
                break
            out.append(d)
        return out

    assert len(naive(file_order, "C")) == 0
    hist = history_before(file_order, "C")
    assert [d.period for d in hist] == ["A", "B"]
    assert len(hist) == 2


def test_m1_ic05_experiment_pin(tmp_path: Path) -> None:
    root, p = _fresh(tmp_path)
    exp = json.loads((root / "experiment.json").read_text(encoding="utf-8"))
    exp["null_seed"] = 424242
    exp["formal"]["checkpoints"] = {"26": 0.99, "52": 0.99}
    (root / "experiment.json").write_text(json.dumps(exp, indent=2), encoding="utf-8")
    with pytest.raises(SettleError):
        pipeline.settle_period(root, p)


def test_m1_ic06_claim_lint() -> None:
    assert scan_forbidden("winning numbers tonight")
    assert_clean("Descriptive percentile vs equal-cost chance.")
    with pytest.raises(ValueError):
        assert_clean("We predict the next draw.")


def test_m1_ic07_html_json_injection() -> None:
    evil = {"series": [{"id": "</script><script>alert(1)//", "values": [1.0, 2.0]}]}
    s = _safe_script_json(evil)
    assert "</script>" not in s
    assert "\\u003c" in s


def test_m1_ic08_code_fingerprint_binds_source() -> None:
    a = code_fingerprint(strategy_kinds=["random"], domain_id="demo649")
    b = code_fingerprint(strategy_kinds=["frequency"], domain_id="demo649")
    assert len(a) >= 16
    assert a != b


def test_m1_settle_and_report_happy_path(tmp_path: Path) -> None:
    root, p = _fresh(tmp_path)
    pipeline.settle_period(root, p)
    summary = pipeline.build_report(root)
    assert (root / "reports" / "latest.html").exists()
    assert summary.periods_settled >= 1
    ok, _ = verify_study_semantic(root)
    assert ok is True
