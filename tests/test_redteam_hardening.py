"""Red-team hardening — R-03 settle/null semantic + doctor vault fail-closed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nullbench.core import pipeline
from nullbench.core.hashing import sha256_hex
from nullbench.core.integrity import (
    freeze_content_hash,
    settle_content_hash,
    verify_study_semantic,
)
from nullbench.core.models import Draw, Ticket
from nullbench.core.seal import notarize_study, verify_study_vault
from nullbench.core.settle_math import portfolio_cost, portfolio_payout
from nullbench.core.study import Study
from nullbench.core.vault import Vault
from nullbench.core.workspace import doctor
from nullbench.strategies import get_strategy, list_strategies

pytestmark = pytest.mark.m1


def _rebuild(path: Path, rows: list[dict]) -> None:
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
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False, default=str) for r in rebuilt) + "\n",
        encoding="utf-8",
    )
    tip = {"line_hash": prev, "n_lines": len(rebuilt), "path": path.name}
    path.with_suffix(path.suffix + ".tip").write_text(json.dumps(tip), encoding="utf-8")


def _study(tmp_path: Path) -> Path:
    root = tmp_path / "s"
    pipeline.init_study(
        root, experiment_id="rt", domain="demo649", demo_draws=20, null_portfolios=30
    )
    pipeline.add_strategy(root, strategy_id="random", kind="random", tickets=2, seed=1)
    pipeline.freeze_latest(root, backtest=True)
    pipeline.settle_period(root)
    return root


def test_r03_forged_null_results_detected(tmp_path: Path) -> None:
    root = _study(tmp_path)
    led = root / "ledger" / "events.jsonl"
    rows = [json.loads(x) for x in led.read_text(encoding="utf-8").splitlines() if x.strip()]
    for r in rows:
        if r.get("type") == "settle":
            for nr in r.get("null_results", []):
                nr["payout"] = 1_000_000.0
    _rebuild(led, rows)
    ok, issues = verify_study_semantic(root)
    assert ok is False
    assert any("null" in i.lower() for i in issues)


def test_r03_settle_draw_vs_draws_file_detected(tmp_path: Path) -> None:
    root = _study(tmp_path)
    study = Study(root)
    spec = study.load_experiment()
    draws = pipeline.load_draws(study.draws_path)
    led = root / "ledger" / "events.jsonl"
    rows = [json.loads(x) for x in led.read_text(encoding="utf-8").splitlines() if x.strip()]
    fr = next(e for e in rows if e.get("type") == "freeze")
    tickets = [Ticket.model_validate(t) for t in fr["tickets"]]
    nums = sorted({n for t in tickets for n in t.numbers})[:6]
    while len(nums) < 6:
        nums.append((max(nums) if nums else 1) + 1)
    forged = Draw(
        period=fr["period"],
        date=draws[0].date,
        numbers=nums,
        special=tickets[0].special,
    )
    for r in rows:
        if r.get("type") == "settle":
            r["draw"] = forged.model_dump(mode="json")
            for s in r.get("strategy_results", []):
                if s.get("portfolio_id") == fr["strategy_id"]:
                    payout, _ = portfolio_payout(spec.game, tickets, forged)
                    s["payout"] = payout
                    s["cost"] = portfolio_cost(spec.game, len(tickets))
    _rebuild(led, rows)
    ok, issues = verify_study_semantic(root)
    assert ok is False
    assert any("settle.draw" in i or "R-03" in i for i in issues)


def test_doctor_fails_when_receipt_deleted_after_notarize(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _study(tmp_path)
    vault = Vault(tmp_path / "vault")
    vault.init()
    monkeypatch.setenv("NULLBENCH_VAULT_DIR", str(vault.root))
    notarize_study(root, vault=vault)
    # Consistent A5 rewrite of freeze tickets + tip
    study = Study(root)
    spec = study.load_experiment()
    draws = pipeline.load_draws(study.draws_path)
    by_period = {d.period: d for d in draws}
    led = root / "ledger" / "events.jsonl"
    rows = [json.loads(x) for x in led.read_text(encoding="utf-8").splitlines() if x.strip()]
    for ev in rows:
        if ev.get("type") != "freeze":
            continue
        tickets = [Ticket.model_validate(t) for t in ev["tickets"]]
        nums = list(tickets[0].numbers)
        nums[0] = 1 if nums[0] != 1 else 2
        tickets[0] = Ticket(numbers=nums, special=tickets[0].special)
        ev["tickets"] = [t.model_dump(mode="json") for t in tickets]
        ev["content_hash"] = freeze_content_hash(
            schema_version=ev["schema_version"],
            experiment_id=ev["experiment_id"],
            period=ev["period"],
            strategy_id=ev["strategy_id"],
            tickets=tickets,
            experiment_hash_=ev["experiment_hash"],
            history_hash_=ev["history_hash"],
            code_fingerprint_=ev["code_fingerprint"],
            outcome_hash=ev.get("outcome_hash"),
            registration_mode=ev.get("registration_mode"),
            history_anchor=ev.get("history_anchor"),
            frozen_at=ev.get("frozen_at"),
        )
    for ev in rows:
        if ev.get("type") != "settle":
            continue
        period_freezes = [
            e for e in rows if e.get("type") == "freeze" and e["period"] == ev["period"]
        ]
        fr = period_freezes[0]
        tickets = [Ticket.model_validate(t) for t in fr["tickets"]]
        draw = by_period[ev["period"]]
        for s in ev.get("strategy_results", []):
            if s.get("portfolio_id") == fr["strategy_id"]:
                payout, _ = portfolio_payout(spec.game, tickets, draw)
                s["payout"] = payout
                s["cost"] = portfolio_cost(spec.game, len(tickets))
        ev["freeze_content_hashes"] = sorted(e["content_hash"] for e in period_freezes)
        ev["content_hash"] = settle_content_hash(
            schema_version=ev["schema_version"],
            experiment_id=ev["experiment_id"],
            period=ev["period"],
            draw=ev["draw"],
            strategy_results=ev["strategy_results"],
            null_pnl=[r["payout"] - r["cost"] for r in ev["null_results"]],
            experiment_hash_=ev["experiment_hash"],
            outcome_hash_=ev["outcome_hash"],
            registration_mode=ev["registration_mode"],
            freeze_content_hashes=ev["freeze_content_hashes"],
        )
    _rebuild(led, rows)
    sem_ok, sem_issues = verify_study_semantic(root)
    assert sem_ok, sem_issues
    (root / "vault" / "latest_receipt.json").unlink()
    vok, viss, _ = verify_study_vault(root, vault=vault)
    assert vok is False
    assert any("vault has" in i for i in viss)
    report = doctor(root)
    vault_check = next(c for c in report["checks"] if c["name"] == "vault_receipt")
    assert vault_check.get("optional") is not True
    assert vault_check["ok"] is False
    assert report["ok"] is False


def test_ic09_list_strategies_does_not_require_trust() -> None:
    # Listing must not import plugins; builtins always present
    assert "random" in list_strategies()
    fn = get_strategy("random")
    assert callable(fn)
