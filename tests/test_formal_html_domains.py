from __future__ import annotations

from pathlib import Path

from nullbench.core import pipeline
from nullbench.core.models import GameSpec, SpecialMode
from nullbench.domains import get_domain_info, list_domains, register_domain
from nullbench.formal.endpoints import (
    FormalEndpointConfig,
    evaluate_formal_endpoint,
    two_sided_empirical_p,
)
from nullbench.protocols import DomainInfo
from nullbench.report.html import render_html


def test_two_sided_p_center() -> None:
    cloud = list(range(-50, 51))
    p = two_sided_empirical_p(0.0, [float(x) for x in cloud])
    assert p > 0.5  # near center → large p


def test_formal_between_looks() -> None:
    cfg = FormalEndpointConfig(enabled=True, primary_strategy_id="a")
    ev = evaluate_formal_endpoint(
        config=cfg,
        strategy_cum_pnl={"a": -100.0},
        null_cum_pnl_cloud=[-90.0] * 200,
        n_settled=10,
    )
    assert ev.endpoint_open is False


def test_formal_open_at_26() -> None:
    cfg = FormalEndpointConfig(enabled=True, primary_strategy_id="a")
    # extreme strategy vs tight null cloud around -100
    nulls = [-100.0] * 200
    ev = evaluate_formal_endpoint(
        config=cfg,
        strategy_cum_pnl={"a": 5000.0},
        null_cum_pnl_cloud=nulls,
        n_settled=26,
    )
    assert ev.endpoint_open is True
    assert ev.alpha_spent == 0.005
    assert ev.strategies["a"].reject_h0 is True


def test_formal_checkpoint_stays_closed_when_primary_is_missing() -> None:
    cfg = FormalEndpointConfig(enabled=True, primary_strategy_id="missing")
    ev = evaluate_formal_endpoint(
        config=cfg,
        strategy_cum_pnl={"actual": 5000.0},
        null_cum_pnl_cloud=[-100.0] * 200,
        n_settled=26,
    )

    assert ev.endpoint_open is False
    assert ev.alpha_spent is None
    assert ev.strategies == {}
    assert "missing" in ev.note


def test_formal_checkpoint_stays_closed_when_primary_was_never_declared() -> None:
    cfg = FormalEndpointConfig(enabled=True, primary_strategy_id=None)
    ev = evaluate_formal_endpoint(
        config=cfg,
        strategy_cum_pnl={"a": 5000.0, "b": -5000.0},
        null_cum_pnl_cloud=[0.0] * 200,
        n_settled=26,
    )

    assert ev.endpoint_open is False
    assert ev.alpha_spent is None
    assert ev.strategies == {}
    assert "no primary" in ev.note.lower()


def test_html_report_and_formal_in_pipeline(tmp_path: Path) -> None:
    root = tmp_path / "s"
    pipeline.init_study(
        root,
        experiment_id="f1",
        domain="demo649",
        demo_draws=40,
        formal_enabled=True,
        formal_primary="random",
    )
    pipeline.add_strategy(root, strategy_id="random", kind="random", tickets=3, seed=1)
    draws = pipeline.load_draws(root / "data" / "draws.jsonl")
    for d in draws[-5:]:
        pipeline.freeze_period(root, d.period, backtest=True)
    pipeline.settle_period(root)
    summary = pipeline.build_report(root)
    assert (root / "reports" / "latest.html").exists()
    html = (root / "reports" / "latest.html").read_text(encoding="utf-8")
    assert "nullbench" in html
    assert summary.periods_settled == 5
    assert summary.formal_endpoint.get("n_settled") == 0
    assert summary.formal_endpoint.get("endpoint_open") is False  # not at 26


def test_register_domain_plugin(tmp_path: Path) -> None:
    # minimal offline domain module object
    class _Mod:
        DOMAIN_ID = "toy6"
        NETWORK = False
        GAME = GameSpec(
            id="toy6",
            name="Toy 6",
            main_count=3,
            main_max=10,
            special_mode=SpecialMode.NONE,
            ticket_cost=1.0,
            prize_table={"2": 5.0},
        )

        @staticmethod
        def write_demo_data(path: Path, n: int = 20, seed: int = 1) -> Path:
            import random

            from nullbench.core.models import Draw

            rng = random.Random(seed)
            lines = []
            for i in range(1, n + 1):
                nums = sorted(rng.sample(range(1, 11), 3))
                lines.append(Draw(period=f"T{i:03d}", numbers=nums).model_dump_json())
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return path

    register_domain(
        DomainInfo(
            id="toy6",
            name="Toy 6",
            network=False,
            description="test plugin domain",
            module=_Mod,
        )
    )
    assert "toy6" in list_domains()
    assert get_domain_info("toy6").name == "Toy 6"
    root = tmp_path / "toy"
    pipeline.init_study(root, experiment_id="t", domain="toy6", demo_draws=15)
    assert len(pipeline.load_draws(root / "data" / "draws.jsonl")) == 15


def test_render_html_smoke() -> None:
    from nullbench.core.models import (
        ClaimStatus,
        ExperimentSpec,
        ReportSummary,
    )
    from nullbench.domains.demo649 import GAME

    spec = ExperimentSpec(experiment_id="x", domain="demo649", game=GAME)
    summary = ReportSummary(
        experiment_id="x",
        periods_settled=2,
        claim_status=ClaimStatus.DESCRIPTIVE_ONLY,
        strategy_cum_pnl={"a": -10.0},
        null_mean_cum_pnl=-12.0,
        strategy_percentiles={"a": 40.0},
        sequential_evidence={"a": {"backend": "test", "e_pq": 1.0, "lcb": -1.0, "ucb": 1.0}},
    )
    html = render_html(spec=spec, summary=summary, settles=[], formal=None)
    assert "<!DOCTYPE html>" in html
