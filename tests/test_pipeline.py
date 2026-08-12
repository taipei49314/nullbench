from __future__ import annotations

from pathlib import Path

from nullbench.core import pipeline
from nullbench.core.study import Study


def test_golden_path_deterministic(tmp_path: Path) -> None:
    root = tmp_path / "study"
    pipeline.init_study(root, experiment_id="t1", domain="demo649", demo_draws=80)
    pipeline.add_strategy(root, strategy_id="random", kind="random", tickets=5, seed=7)
    pipeline.add_strategy(
        root, strategy_id="frequency", kind="frequency", tickets=5, seed=8, params={"window": 30}
    )
    draws = pipeline.load_draws(Study(root).draws_path)
    period = draws[-5].period

    r1 = pipeline.freeze_period(root, period)
    assert len(r1) == 2
    # idempotent
    r2 = pipeline.freeze_period(root, period)
    assert r2 == []

    tickets_a = [t.numbers for t in r1[0].tickets]
    # re-freeze path already skipped; re-run strategy via second study for determinism
    root_b = tmp_path / "study_b"
    pipeline.init_study(root_b, experiment_id="t1", domain="demo649", demo_draws=80)
    pipeline.add_strategy(root_b, strategy_id="random", kind="random", tickets=5, seed=7)
    r_b = pipeline.freeze_period(root_b, period)
    tickets_b = [t.numbers for t in r_b[0].tickets]
    assert tickets_a == tickets_b

    settled = pipeline.settle_period(root, period)
    assert len(settled) == 1
    summary = pipeline.build_report(root)
    assert summary.periods_settled == 1
    assert "random" in summary.strategy_cum_pnl
    assert (Study(root).reports_dir / "latest.md").exists()

    st = pipeline.status(root)
    assert st["ledger_ok"] is True


def test_no_backfill_freeze_after_settle(tmp_path: Path) -> None:
    root = tmp_path / "study"
    pipeline.init_study(root, experiment_id="t2", domain="demo649", demo_draws=40)
    pipeline.add_strategy(root, strategy_id="random", kind="random", tickets=3, seed=1)
    draws = pipeline.load_draws(Study(root).draws_path)
    p = draws[-1].period
    pipeline.freeze_period(root, p)
    pipeline.settle_period(root, p)
    from nullbench.errors import FreezeError

    try:
        pipeline.freeze_period(root, p)
        assert False, "should have refused freeze after settle"
    except FreezeError as e:
        assert "settled" in str(e).lower() or "backfill" in str(e).lower()


def test_claims_forbidden() -> None:
    from nullbench.core.claims import scan_forbidden

    assert scan_forbidden("this is a prediction of winning numbers")
    assert not scan_forbidden("descriptive percentile vs equal-cost chance")
