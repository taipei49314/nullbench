"""完整六主號 proper-score 前緣的聚合與可比性測試。"""
from __future__ import annotations

import math
from pathlib import Path

import pytest

from engine.games import LOTTO649, SUPER
from research.gates import tree_sha256
from research.probability_frontier import (
    METHOD_IDS,
    PROTOCOL_CONFIG,
    build_frontier_row,
    run_probability_frontier,
    validate_result,
)


BASE = Path(__file__).parent.parent


def _synthetic_game_result(game: str, regret: float) -> dict:
    return {
        "game": game,
        "game_name": game,
        "draws": 100,
        "first_date": "2020-01-01",
        "last_date": "2020-12-31",
        "mean_regret_nats": regret,
        "bootstrap_95_low": regret - 0.01,
        "bootstrap_95_high": regret + 0.01,
        "geometric_probability_ratio_vs_uniform": math.exp(
            -regret
        ),
        "source_id": "temporal_stacking_diagnostic",
    }


def test_build_frontier_row_uses_fixed_minimax_aggregation():
    row = build_frontier_row(
        method_id="subset_cumulative",
        family="probability_stacking",
        game_results={
            SUPER: _synthetic_game_result(SUPER, -0.02),
            LOTTO649: _synthetic_game_result(LOTTO649, 0.01),
        },
        source_ids=["temporal_stacking_diagnostic"],
    )
    assert math.isclose(row["mean_regret_across_games"], -0.005)
    assert row["minimax_regret"] == 0.01
    assert math.isclose(
        row["worst_game_probability_ratio_vs_uniform"],
        math.exp(-0.01),
    )
    assert row["strictly_dominated_by_uniform"] is False
    assert row["both_games_mean_negative"] is False


def test_build_frontier_row_rejects_missing_game():
    with pytest.raises(ValueError):
        build_frontier_row(
            method_id="subset_cumulative",
            family="probability_stacking",
            game_results={
                SUPER: _synthetic_game_result(SUPER, 0.01),
            },
            source_ids=["temporal_stacking_diagnostic"],
        )


def test_live_frontier_is_complete_and_records_are_unchanged():
    before = tree_sha256(BASE / "records")
    result = run_probability_frontier(base=BASE)
    after = tree_sha256(BASE / "records")
    validate_result(result)
    assert before == after
    assert result["records_integrity"]["unchanged"] is True
    assert len(result["frontier_rows"]) == len(METHOD_IDS)
    assert {
        row["method_id"] for row in result["frontier_rows"]
    } == set(METHOD_IDS)


def test_uniform_is_champion_and_all_non_uniform_are_dominated():
    result = run_probability_frontier(base=BASE)
    rows = result["frontier_rows"]
    assert rows[0]["method_id"] == "uniform_null_safe"
    assert rows[0]["minimax_regret"] == 0
    non_uniform = [row for row in rows if row["non_uniform"]]
    assert len(non_uniform) == len(METHOD_IDS) - 1
    assert all(
        row["strictly_dominated_by_uniform"]
        for row in non_uniform
    )
    assert not any(
        row["both_games_mean_negative"]
        and row["both_games_bootstrap_upper_negative"]
        for row in non_uniform
    )


def test_best_non_uniform_is_current_rolling_208_result():
    result = run_probability_frontier(base=BASE)
    assert (
        result["conclusion"]["best_non_uniform_method_id"]
        == "subset_rolling_208"
    )
    subset = next(
        row
        for row in result["frontier_rows"]
        if row["method_id"] == "subset_cumulative"
    )
    assert subset["game_results"][SUPER]["mean_regret_nats"] > 0
    assert subset["game_results"][LOTTO649]["mean_regret_nats"] > 0


def test_protocol_explicitly_excludes_incomparable_metrics():
    excluded = set(PROTOCOL_CONFIG["excluded_metric_families"])
    assert excluded == {
        "marginal_mass_log_loss",
        "top_k_or_ticket_hits",
        "prize_or_profit_event_probability",
        "second_zone_or_bonus_probability",
    }
