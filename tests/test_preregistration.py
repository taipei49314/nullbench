"""Acceptance coverage for fail-closed pre-outcome classification (0.9.0)."""

from __future__ import annotations

import contextlib
import copy
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from nullbench.cli import app
from nullbench.core import pipeline
from nullbench.core.integrity import (
    code_fingerprint,
    experiment_hash,
    freeze_content_hash,
    history_before,
    history_hash,
    outcome_hash,
    registration_class_for_freeze,
    settle_content_hash,
    verify_freeze_history,
    verify_freeze_row,
    verify_study_semantic,
)
from nullbench.core.locking import study_lock
from nullbench.core.models import ClaimStatus, Draw
from nullbench.core.study import Study
from nullbench.errors import (
    DataError,
    FreezeError,
    IntegrityError,
    OutcomePendingError,
    SettleError,
    StrategyError,
    StudyExistsError,
)
from nullbench.strategies import get_strategy

pytestmark = pytest.mark.m1


def _mode_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def _anchor_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return dict(value)


def _study(
    tmp_path: Path,
    name: str,
    *,
    draws: int = 20,
    formal: bool = False,
) -> Path:
    root = tmp_path / name
    pipeline.init_study(
        root,
        experiment_id=name,
        domain="demo649",
        demo_draws=draws,
        null_portfolios=5,
        formal_enabled=formal,
        formal_primary="random" if formal else None,
    )
    pipeline.add_strategy(root, strategy_id="random", kind="random", tickets=2, seed=7)
    return root


def _append_draw(
    root: Path,
    period: str,
    *,
    numbers: list[int] | None = None,
    date: str | None = None,
) -> Draw:
    draw = Draw(
        period=period,
        numbers=numbers or [1, 2, 3, 4, 5, 6],
        date=date,
        meta={"source": "acceptance-fixture"},
    )
    path = Study(root).draws_path
    with path.open("a", encoding="utf-8") as fh:
        fh.write(draw.model_dump_json() + "\n")
    return draw


def _freeze_row(root: Path, period: str) -> dict[str, Any]:
    return next(
        row for row in Study(root).ledger().events_of("freeze") if row.get("period") == period
    )


def _rewrite_ledger(root: Path, rows: list[dict[str, Any]]) -> None:
    from nullbench.core.hashing import sha256_hex

    previous = "0" * 64
    rebuilt = []
    for row in rows:
        body = {k: v for k, v in row.items() if k not in ("prev_line_hash", "line_hash")}
        material = {"prev_line_hash": previous, **body}
        digest = sha256_hex(
            json.dumps(material, sort_keys=True, separators=(",", ":"), default=str)
        )
        material["line_hash"] = digest
        previous = digest
        rebuilt.append(material)
    path = root / "ledger" / "events.jsonl"
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, default=str) for row in rebuilt) + "\n",
        encoding="utf-8",
    )
    path.with_suffix(path.suffix + ".tip").write_text(
        json.dumps({"line_hash": previous, "n_lines": len(rebuilt), "path": path.name}),
        encoding="utf-8",
    )


def test_prospective_freeze_reveal_then_settle(tmp_path: Path) -> None:
    root = _study(tmp_path, "prospective")

    records = pipeline.freeze_period(root, "P0021")

    assert len(records) == 1
    record = records[0]
    assert _mode_value(record.registration_mode) == "pre_outcome"
    assert record.outcome_hash is None
    assert record.late is False
    anchor = _anchor_dict(record.history_anchor)
    assert anchor == {
        "algorithm": "ordered_prefix_v1",
        "count": 20,
        "through": {"date": None, "period": "P0020"},
    }
    row = _freeze_row(root, "P0021")
    verify_freeze_row(row)
    verify_freeze_history(pipeline.load_draws(Study(root).draws_path), row)
    assert verify_study_semantic(root)[0] is True  # pending is healthy, not corrupt

    _append_draw(root, "P0021")
    settlements = pipeline.settle_period(root, "P0021")

    assert len(settlements) == 1
    assert _mode_value(settlements[0].registration_mode) == "pre_outcome"
    assert verify_study_semantic(root)[0] is True


def test_known_outcome_requires_explicit_backtest(tmp_path: Path) -> None:
    root = _study(tmp_path, "known")

    with pytest.raises(FreezeError, match="backtest"):
        pipeline.freeze_period(root, "P0020")
    assert Study(root).ledger().events_of("freeze") == []

    records = pipeline.freeze_period(root, "P0020", backtest=True)
    assert len(records) == 1
    assert _mode_value(records[0].registration_mode) == "backtest"
    assert records[0].outcome_hash
    assert records[0].late is True


def test_pending_batch_skips_but_explicit_settle_is_typed(tmp_path: Path) -> None:
    root = _study(tmp_path, "pending")
    pipeline.freeze_period(root, "P0021")

    assert pipeline.settle_period(root) == []
    assert Study(root).ledger().events_of("settle") == []
    with pytest.raises(OutcomePendingError, match="P0021"):
        pipeline.settle_period(root, "P0021")


def test_history_anchor_allows_later_intermediate_draws(tmp_path: Path) -> None:
    root = _study(tmp_path, "intermediate")
    pipeline.freeze_period(root, "P0022")
    row = _freeze_row(root, "P0022")

    _append_draw(root, "P0021", numbers=[2, 3, 4, 5, 6, 7])
    _append_draw(root, "P0022", numbers=[3, 4, 5, 6, 7, 8])

    verify_freeze_history(pipeline.load_draws(Study(root).draws_path), row)
    assert len(pipeline.settle_period(root, "P0022")) == 1
    assert verify_study_semantic(root)[0] is True


def test_history_anchor_detects_prefix_drift(tmp_path: Path) -> None:
    root = _study(tmp_path, "prefix-drift")
    pipeline.freeze_period(root, "P0021")
    row = _freeze_row(root, "P0021")
    path = Study(root).draws_path
    draws = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    draws[0]["numbers"] = [1, 2, 3, 4, 5, 49]
    path.write_text("\n".join(json.dumps(draw) for draw in draws) + "\n", encoding="utf-8")

    with pytest.raises(IntegrityError, match="history|anchor|prefix"):
        verify_freeze_history(pipeline.load_draws(path), row)
    _append_draw(root, "P0021")
    with pytest.raises(SettleError, match="history|anchor|prefix"):
        pipeline.settle_period(root, "P0021")


def test_revealed_target_must_follow_history_anchor(tmp_path: Path) -> None:
    root = _study(tmp_path, "causal-order")
    pipeline.freeze_period(root, "P0019A")
    _append_draw(root, "P0019A", numbers=[4, 5, 6, 7, 8, 9])

    with pytest.raises(SettleError, match="causal|look-ahead|anchor"):
        pipeline.settle_period(root, "P0019A")


def test_duplicate_draw_period_is_rejected(tmp_path: Path) -> None:
    root = _study(tmp_path, "duplicate")
    _append_draw(root, "P0020", numbers=[2, 3, 4, 5, 6, 7])

    with pytest.raises(DataError, match="duplicate.*P0020|P0020.*duplicate"):
        pipeline.load_draws(Study(root).draws_path)


def test_backtest_settlements_are_never_formal_eligible(tmp_path: Path) -> None:
    root = _study(tmp_path, "backtest-formal", draws=30, formal=True)
    draws = pipeline.load_draws(Study(root).draws_path)
    for draw in draws[-26:]:
        pipeline.freeze_period(root, draw.period, backtest=True)
    pipeline.settle_period(root)

    summary = pipeline.build_report(root)

    assert summary.periods_settled == 26
    assert summary.claim_status == ClaimStatus.DESCRIPTIVE_ONLY
    assert summary.formal_endpoint.get("n_settled") == 0
    assert summary.formal_endpoint.get("endpoint_open") is False
    assert any("backtest" in warning.lower() for warning in summary.warnings)


def test_cli_requires_backtest_for_known_or_latest_outcome(tmp_path: Path) -> None:
    runner = CliRunner()
    root = _study(tmp_path, "cli-gate")

    refused = runner.invoke(app, ["freeze", "P0020", "--study", str(root)])
    assert refused.exit_code != 0
    assert "backtest" in refused.output.lower()
    assert Study(root).ledger().events_of("freeze") == []

    refused_latest = runner.invoke(app, ["freeze", "--latest", "--study", str(root)])
    assert refused_latest.exit_code != 0
    assert "backtest" in refused_latest.output.lower()

    accepted = runner.invoke(
        app,
        ["freeze", "P0020", "--study", str(root), "--backtest"],
    )
    assert accepted.exit_code == 0, accepted.output
    assert _mode_value(_freeze_row(root, "P0020")["registration_mode"]) == "backtest"


def test_legacy_v2_hash_dispatch_and_classification() -> None:
    tickets = [{"numbers": [1, 2, 3, 4, 5, 6], "special": None, "label": "x"}]
    kwargs = {
        "experiment_id": "exp-v2",
        "period": "P0001",
        "strategy_id": "random",
        "tickets": tickets,
        "experiment_hash_": "e" * 64,
        "history_hash_": "h" * 64,
        "code_fingerprint_": "c" * 32,
        "outcome_hash": "o" * 64,
    }
    expected = "bd6eea6f0f68c541d2813816ae988bacefa0c96b415668801866871250cc9b47"
    assert freeze_content_hash(**kwargs) == expected
    assert freeze_content_hash(schema_version="2", **kwargs) == expected

    row = {
        "schema_version": "2",
        "type": "freeze",
        "experiment_id": kwargs["experiment_id"],
        "period": kwargs["period"],
        "strategy_id": kwargs["strategy_id"],
        "tickets": tickets,
        "experiment_hash": kwargs["experiment_hash_"],
        "history_hash": kwargs["history_hash_"],
        "code_fingerprint": kwargs["code_fingerprint_"],
        "outcome_hash": kwargs["outcome_hash"],
        "content_hash": expected,
        "late": False,
        # New-looking fields on a v2 row must never upgrade its evidence class.
        "registration_mode": "pre_outcome",
    }
    verify_freeze_row(row)
    assert _mode_value(registration_class_for_freeze(row)) == "legacy_backtest"

    unknown = dict(row)
    unknown["outcome_hash"] = None
    unknown["content_hash"] = freeze_content_hash(
        schema_version="2",
        **{**kwargs, "outcome_hash": None},
    )
    assert _mode_value(registration_class_for_freeze(unknown)) == "legacy_unknown"


def test_v3_hash_binds_registration_evidence(tmp_path: Path) -> None:
    root = _study(tmp_path, "hash-evidence")
    pipeline.freeze_period(root, "P0021")
    original = _freeze_row(root, "P0021")

    variants = []
    changed_anchor = copy.deepcopy(original)
    changed_anchor["history_anchor"]["through"]["period"] = "P0019"
    variants.append(changed_anchor)
    changed_time = copy.deepcopy(original)
    changed_time["frozen_at"] = "2000-01-01T00:00:00Z"
    variants.append(changed_time)
    changed_mode = copy.deepcopy(original)
    changed_mode["registration_mode"] = "backtest"
    variants.append(changed_mode)
    changed_outcome = copy.deepcopy(original)
    changed_outcome["outcome_hash"] = "f" * 64
    variants.append(changed_outcome)
    changed_late = copy.deepcopy(original)
    changed_late["late"] = True
    variants.append(changed_late)

    for changed in variants:
        with pytest.raises(IntegrityError):
            verify_freeze_row(changed)


def test_cross_arm_registration_evidence_must_match(tmp_path: Path) -> None:
    root = _study(tmp_path, "cross-arm")
    pipeline.add_strategy(root, strategy_id="frequency", kind="frequency", tickets=2, seed=8)
    pipeline.freeze_period(root, "P0021")
    rows = list(Study(root).ledger())
    altered = next(
        row for row in rows if row.get("type") == "freeze" and row.get("strategy_id") == "frequency"
    )
    altered["frozen_at"] = "2000-01-01T00:00:00Z"
    altered["content_hash"] = freeze_content_hash(
        schema_version="3",
        experiment_id=altered["experiment_id"],
        period=altered["period"],
        strategy_id=altered["strategy_id"],
        tickets=altered["tickets"],
        experiment_hash_=altered["experiment_hash"],
        history_hash_=altered["history_hash"],
        code_fingerprint_=altered["code_fingerprint"],
        registration_mode=altered["registration_mode"],
        history_anchor=altered["history_anchor"],
        outcome_hash=altered["outcome_hash"],
        frozen_at=altered["frozen_at"],
    )
    _rewrite_ledger(root, rows)

    ok, issues = verify_study_semantic(root)
    assert ok is False
    assert any("cross-arm" in issue for issue in issues)
    _append_draw(root, "P0021")
    with pytest.raises(SettleError, match="across arms"):
        pipeline.settle_period(root, "P0021")


def test_experiment_rejects_mixed_registration_modes(tmp_path: Path) -> None:
    root = _study(tmp_path, "mixed-mode")
    pipeline.freeze_period(root, "P0020", backtest=True)

    with pytest.raises(FreezeError, match="mix"):
        pipeline.freeze_period(root, "P0021")


def test_26_pre_outcome_periods_can_open_formal_endpoint(tmp_path: Path) -> None:
    root = _study(tmp_path, "prospective-formal", formal=True)
    for number in range(21, 47):
        period = f"P{number:04d}"
        pipeline.freeze_period(root, period)
        _append_draw(root, period, numbers=[2, 3, 4, 5, 6, 7])
        pipeline.settle_period(root, period)

    summary = pipeline.build_report(root)
    assert summary.periods_settled == 26
    assert summary.formal_eligible_periods == 26
    assert summary.registration_counts == {"pre_outcome": 26}
    assert summary.formal_endpoint["n_settled"] == 26
    assert summary.formal_endpoint["endpoint_open"] is True
    assert summary.claim_status == ClaimStatus.FORMAL_ENDPOINT


def test_legacy_v2_study_settles_without_rewriting_freeze(tmp_path: Path) -> None:
    root = _study(tmp_path, "legacy-study", formal=True)
    study = Study(root)
    spec = study.load_experiment()
    draws = pipeline.load_draws(study.draws_path)
    target = draws[-1]
    prior = history_before(draws, target.period)
    strategy = spec.strategies[0]
    seed = pipeline._period_seed(target.period)
    tickets = get_strategy(strategy.kind)(spec.game, strategy, prior, seed)
    exp_hash = experiment_hash(spec)
    hist_hash = history_hash(prior)
    fingerprint = code_fingerprint(strategy_kinds=[strategy.kind], domain_id=spec.domain)
    out_hash = outcome_hash(target)
    freeze_hash = freeze_content_hash(
        experiment_id=spec.experiment_id,
        period=target.period,
        strategy_id=strategy.id,
        tickets=tickets,
        experiment_hash_=exp_hash,
        history_hash_=hist_hash,
        code_fingerprint_=fingerprint,
        outcome_hash=out_hash,
    )
    legacy_row = {
        "schema_version": "2",
        "type": "freeze",
        "experiment_id": spec.experiment_id,
        "period": target.period,
        "strategy_id": strategy.id,
        "tickets": [ticket.model_dump(mode="json") for ticket in tickets],
        "content_hash": freeze_hash,
        "code_fingerprint": fingerprint,
        "experiment_hash": exp_hash,
        "history_hash": hist_hash,
        "outcome_hash": out_hash,
        "frozen_at": "2026-01-01T00:00:00Z",
        "late": False,
        "meta": {"null_seed": spec.null_seed},
    }
    study.ledger().append(legacy_row)
    before = _freeze_row(root, target.period)

    settlements = pipeline.settle_period(root, target.period)
    assert _mode_value(settlements[0].registration_mode) == "legacy_backtest"
    assert _freeze_row(root, target.period) == before
    summary = pipeline.build_report(root)
    assert summary.formal_eligible_periods == 0
    assert summary.registration_counts == {"legacy_backtest": 1}
    assert summary.claim_status == ClaimStatus.DESCRIPTIVE_ONLY
    assert verify_study_semantic(root)[0] is True


def test_duplicate_settle_cannot_inflate_formal_sample_count(tmp_path: Path) -> None:
    root = _study(tmp_path, "duplicate-settle", formal=True)
    pipeline.freeze_period(root, "P0021")
    _append_draw(root, "P0021")
    pipeline.settle_period(root, "P0021")
    ledger = Study(root).ledger()
    original_settle = ledger.events_of("settle")[0]
    ledger.append(original_settle)

    ok, issues = verify_study_semantic(root)
    assert ok is False
    assert any("duplicate settle" in issue for issue in issues)
    with pytest.raises(SettleError, match="duplicate settle"):
        pipeline.settle_period(root)
    with pytest.raises(IntegrityError, match="duplicate settle"):
        pipeline.build_report(root)


def test_outcome_appearing_during_strategy_execution_aborts_freeze(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _study(tmp_path, "freeze-toctou", draws=3)
    original_get_strategy = pipeline.get_strategy

    def mutating_strategy(game, strategy, history, period_seed):
        _append_draw(root, "P0004", numbers=[2, 3, 4, 5, 6, 7])
        return original_get_strategy("random")(game, strategy, history, period_seed)

    monkeypatch.setattr(pipeline, "get_strategy", lambda _kind: mutating_strategy)

    with pytest.raises(FreezeError, match="appeared while freezing"):
        pipeline.freeze_period(root, "P0004")
    assert Study(root).ledger().events_of("freeze") == []


def test_outcome_appearing_at_commit_time_aborts_freeze(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _study(tmp_path, "freeze-commit-toctou", draws=3)
    original_utc_now = pipeline.utc_now

    def mutating_clock():
        _append_draw(root, "P0004", numbers=[2, 3, 4, 5, 6, 7])
        return original_utc_now()

    monkeypatch.setattr(pipeline, "utc_now", mutating_clock)

    with pytest.raises(FreezeError, match="appeared while freezing"):
        pipeline.freeze_period(root, "P0004")
    assert Study(root).ledger().events_of("freeze") == []
    assert not (root / ".nullbench.lock").exists()


def test_settle_v2_cannot_be_downgraded_for_v3_freeze(tmp_path: Path) -> None:
    root = _study(tmp_path, "settle-downgrade")
    pipeline.freeze_period(root, "P0021")
    _append_draw(root, "P0021")
    pipeline.settle_period(root, "P0021")
    rows = list(Study(root).ledger())
    settle = next(row for row in rows if row.get("type") == "settle")
    settle["schema_version"] = "1"
    settle.pop("registration_mode")
    settle.pop("freeze_content_hashes")
    settle["content_hash"] = settle_content_hash(
        schema_version="1",
        experiment_id=settle["experiment_id"],
        period=settle["period"],
        draw=settle["draw"],
        strategy_results=settle["strategy_results"],
        null_pnl=[row["payout"] - row["cost"] for row in settle["null_results"]],
        experiment_hash_=settle["experiment_hash"],
        outcome_hash_=settle["outcome_hash"],
    )
    _rewrite_ledger(root, rows)

    ok, issues = verify_study_semantic(root)
    assert ok is False
    assert any("schema downgrade" in issue for issue in issues)
    with pytest.raises(IntegrityError, match="schema downgrade"):
        pipeline.build_report(root)


def test_missing_backtest_outcome_is_not_treated_as_pending(tmp_path: Path) -> None:
    root = _study(tmp_path, "missing-backtest")
    pipeline.freeze_period(root, "P0020", backtest=True)
    path = Study(root).draws_path
    remaining = [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if json.loads(line)["period"] != "P0020"
    ]
    path.write_text("\n".join(remaining) + "\n", encoding="utf-8")

    with pytest.raises(SettleError, match="historical outcome missing"):
        pipeline.settle_period(root)
    ok, issues = verify_study_semantic(root)
    assert ok is False
    assert any("backtest target missing" in issue for issue in issues)

    result = CliRunner().invoke(app, ["periods", "--study", str(root)])
    assert result.exit_code == 0
    assert "MISSING" in result.output
    assert "pending" not in result.output


def test_backtest_demo_can_be_reused(tmp_path: Path) -> None:
    runner = CliRunner()
    args = ["demo", "--name", "reusable", "--path", str(tmp_path), "--periods", "2"]

    first = runner.invoke(app, args)
    second = runner.invoke(app, args)

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    assert "Reusing" in second.output
    assert "BACKTEST" in second.output


def test_demo_refuses_to_mutate_an_existing_non_demo_study(tmp_path: Path) -> None:
    root = _study(tmp_path, "occupied")
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["demo", "--name", root.name, "--path", str(tmp_path), "--periods", "2"],
    )

    assert result.exit_code == 1
    assert "refusing to reuse non-demo study" in result.output
    assert Study(root).ledger().events_of("freeze") == []
    assert Study(root).ledger().events_of("settle") == []


def test_demo_rejects_non_positive_period_count_without_creating_study(tmp_path: Path) -> None:
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["demo", "--name", "invalid-count", "--path", str(tmp_path), "--periods", "0"],
    )

    assert result.exit_code != 0
    assert not (tmp_path / "invalid-count").exists()


def test_demo_rejects_oversized_period_count_without_creating_study(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        ["demo", "--name", "too-many", "--path", str(tmp_path), "--periods", "101"],
    )

    assert result.exit_code != 0
    assert not (tmp_path / "too-many").exists()


def test_json_status_failure_has_nonzero_exit_code(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        ["status", "--study", str(tmp_path / "missing"), "--json"],
    )

    assert result.exit_code == 1
    assert '"ok": false' in result.output


def test_broken_ledger_status_is_nonzero_in_text_and_json(tmp_path: Path) -> None:
    root = _study(tmp_path, "broken-status")
    Study(root).ledger_path.write_text('{"broken":', encoding="utf-8")

    text_result = CliRunner().invoke(app, ["status", "--study", str(root)])
    json_result = CliRunner().invoke(app, ["status", "--study", str(root), "--json"])

    assert text_result.exit_code == 1
    assert json_result.exit_code == 1
    assert "ledger integrity failed" in text_result.output
    assert '"ok": false' in json_result.output
    assert "Traceback" not in text_result.output + json_result.output


def test_relinked_semantic_tamper_makes_status_fail(tmp_path: Path) -> None:
    root = _study(tmp_path, "semantic-status")
    pipeline.freeze_period(root, "P0020", backtest=True)
    rows = list(Study(root).ledger())
    rows[0]["frozen_at"] = "1900-01-01T00:00:00+00:00"
    _rewrite_ledger(root, rows)

    info = pipeline.status(root)
    cli = CliRunner().invoke(app, ["status", "--study", str(root), "--json"])

    assert info["ok"] is False
    assert info["ledger_ok"] is True
    assert info["semantic_ok"] is False
    assert cli.exit_code == 1
    assert "semantic integrity failed" in cli.output


def test_invalid_init_and_strategy_configurations_fail_before_writes(tmp_path: Path) -> None:
    invalid_root = tmp_path / "invalid-init"
    with pytest.raises(DataError, match="invalid study configuration"):
        pipeline.init_study(
            invalid_root,
            experiment_id="invalid",
            domain="demo649",
            null_portfolios=0,
            demo_draws=3,
        )
    assert not invalid_root.exists()

    cli_root = tmp_path / "invalid-cli"
    cli_result = CliRunner().invoke(
        app,
        [
            "init",
            cli_root.name,
            "--path",
            str(tmp_path),
            "--nulls",
            "0",
            "--demo-draws",
            "3",
        ],
    )
    assert cli_result.exit_code != 0
    assert not cli_root.exists()

    root = tmp_path / "strategy-validation"
    pipeline.init_study(root, experiment_id="strategy-validation", demo_draws=3)
    with pytest.raises(StrategyError, match="invalid strategy configuration"):
        pipeline.add_strategy(root, strategy_id="bad", kind="random", tickets=0)
    assert Study(root).load_experiment().strategies == []
    assert not Study(root).ledger_path.exists()
    assert not Study(root).ledger_path.with_suffix(".jsonl.tip").exists()


def test_init_refuses_nonempty_target_without_overwriting_files(tmp_path: Path) -> None:
    root = tmp_path / "occupied"
    root.mkdir()
    sentinel = root / "keep.txt"
    sentinel.write_text("user data", encoding="utf-8")

    with pytest.raises(StudyExistsError, match="not empty"):
        pipeline.init_study(root, experiment_id="must-not-overwrite", demo_draws=3)

    assert sentinel.read_text(encoding="utf-8") == "user data"
    assert not (root / "experiment.json").exists()
    assert not (root / "data").exists()


def test_formal_endpoint_requires_predeclared_primary(tmp_path: Path) -> None:
    with pytest.raises(DataError, match="requires a primary"):
        pipeline.init_study(
            tmp_path / "no-primary",
            experiment_id="no-primary",
            demo_draws=3,
            formal_enabled=True,
        )
    assert not (tmp_path / "no-primary").exists()

    root = _study(tmp_path, "enable-no-primary")
    with pytest.raises(StrategyError, match="requires a primary"):
        pipeline.enable_formal_endpoint(root, enabled=True)


def test_missing_formal_primary_blocks_first_freeze(tmp_path: Path) -> None:
    root = tmp_path / "missing-primary"
    pipeline.init_study(
        root,
        experiment_id="missing-primary",
        domain="demo649",
        demo_draws=3,
        formal_enabled=True,
        formal_primary="typo",
    )
    pipeline.add_strategy(root, strategy_id="actual", kind="random", tickets=1)

    with pytest.raises(FreezeError, match="formal primary strategy does not exist"):
        pipeline.freeze_period(root, "P0004")
    assert Study(root).ledger().events_of("freeze") == []


def test_freeze_requires_equal_declared_and_actual_arm_costs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    unequal = _study(tmp_path, "unequal-arms")
    pipeline.add_strategy(unequal, strategy_id="frequency", kind="frequency", tickets=3)
    with pytest.raises(FreezeError, match="same tickets_per_period"):
        pipeline.freeze_period(unequal, "P0021")

    short = _study(tmp_path, "short-plugin")
    original = pipeline.get_strategy("random")

    def short_strategy(game, strategy, history, period_seed):
        return original(game, strategy, history, period_seed)[:1]

    monkeypatch.setattr(pipeline, "get_strategy", lambda _kind: short_strategy)
    with pytest.raises(FreezeError, match="returned 1 ticket"):
        pipeline.freeze_period(short, "P0021")
    assert Study(short).ledger().events_of("freeze") == []


def test_live_study_lock_is_never_stolen_by_age(tmp_path: Path) -> None:
    root = tmp_path / "locked"
    root.mkdir()
    with study_lock(root):
        old = time.time() - 86_400
        os.utime(root / ".nullbench.lock", (old, old))
        with (
            pytest.raises(IntegrityError, match="already held"),
            study_lock(root, timeout=0.01),
        ):
            pytest.fail("a live lock must not be stolen")


def test_lock_owner_write_failure_does_not_strand_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nullbench.core import locking

    root = tmp_path / "write-failure"
    root.mkdir()
    with monkeypatch.context() as scoped, pytest.raises(IntegrityError, match="owner record"):
        scoped.setattr(locking.os, "write", lambda *_args: (_ for _ in ()).throw(OSError("disk")))
        with study_lock(root, timeout=0.01):
            pytest.fail("lock acquisition must not succeed")
    assert not (root / ".nullbench.lock").exists()
    with study_lock(root, timeout=0.01):
        pass


def test_concurrent_initializers_cannot_both_write_same_study(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "init-race"
    original_exists = Study.exists
    checked = threading.Barrier(2)

    def synchronized_exists(study: Study) -> bool:
        exists = original_exists(study)
        if study.root == root and not exists:
            with contextlib.suppress(threading.BrokenBarrierError):
                checked.wait(timeout=0.2)
        return exists

    monkeypatch.setattr(Study, "exists", synchronized_exists)

    def initialize(experiment_id: str, draws: int) -> str:
        try:
            spec = pipeline.init_study(
                root,
                experiment_id=experiment_id,
                domain="demo649",
                demo_draws=draws,
            )
            return spec.experiment_id
        except (IntegrityError, StudyExistsError) as exc:
            return type(exc).__name__

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda args: initialize(*args),
                [("race-a", 23), ("race-b", 29)],
            )
        )

    winners = [result for result in results if result in {"race-a", "race-b"}]
    assert len(winners) == 1
    assert len([result for result in results if result.endswith("Error")]) == 1
    winner = winners[0]
    assert Study(root).load_experiment().experiment_id == winner
    expected_draws = 23 if winner == "race-a" else 29
    assert len(pipeline.load_draws(Study(root).draws_path)) == expected_draws
