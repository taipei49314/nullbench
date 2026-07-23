from __future__ import annotations

import json
from pathlib import Path

import pytest

from research.lag_overlap_signal import MODEL_ID as LAG_MODEL_ID
from research.probability_frontier_v2 import (
    METHOD_IDS,
    SOURCE_FILES,
    build_conclusion,
    build_frontier_rows,
    run_probability_frontier_v2,
    validate_result,
)


ROOT = Path(__file__).resolve().parents[1]


def _sources() -> dict[str, dict]:
    return {
        source_id: json.loads(
            (ROOT / relative_path).read_text(encoding="utf-8")
        )
        for source_id, relative_path in SOURCE_FILES.items()
    }


def test_frontier_v2_has_fixed_twelve_method_contract():
    assert len(METHOD_IDS) == 12
    assert len(set(METHOD_IDS)) == 12
    assert LAG_MODEL_ID in METHOD_IDS


def test_frontier_v2_includes_lag_unconditionally_and_ranks_it():
    rows = build_frontier_rows(_sources())
    assert len(rows) == 12
    lag = next(row for row in rows if row["method_id"] == LAG_MODEL_ID)
    assert lag["rank"] == 10
    assert lag["strictly_dominated_by_uniform"] is True
    assert lag["both_games_mean_negative"] is False
    assert lag["both_games_bootstrap_upper_negative"] is False


def test_v1_scores_are_immutable_in_v2_mapping():
    sources = _sources()
    v1_rows = {
        row["method_id"]: row
        for row in sources["probability_frontier_v1"][
            "frontier_rows"
        ]
    }
    v2_rows = {
        row["method_id"]: row
        for row in build_frontier_rows(sources)
    }
    for method_id, v1 in v1_rows.items():
        v2 = v2_rows[method_id]
        assert v2["minimax_regret"] == v1["minimax_regret"]
        assert (
            v2["mean_regret_across_games"]
            == v1["mean_regret_across_games"]
        )
        for game in ("super", "lotto649"):
            expected = dict(v1["game_results"][game])
            expected["source_id"] = "probability_frontier_v1"
            assert v2["game_results"][game] == expected


def test_conclusion_retains_uniform_and_freezes_v1():
    conclusion = build_conclusion(build_frontier_rows(_sources()))
    assert conclusion["status"] == (
        "retain_uniform_null_safe_champion"
    )
    assert conclusion["champion_method_id"] == "uniform_null_safe"
    assert conclusion["historically_supported_non_uniform_methods"] == []
    assert conclusion["non_uniform_method_count"] == 11
    assert conclusion["v1_immutable"] is True


def test_live_frontier_v2_validates_and_preserves_records():
    result = run_probability_frontier_v2(base=ROOT)
    assert validate_result(result) == result
    assert result["records_integrity"]["unchanged"] is True
    assert len(result["frontier_rows"]) == 12


def test_frontier_v2_rejects_missing_source():
    sources = _sources()
    sources.pop("lag_overlap_signal")
    with pytest.raises(KeyError):
        build_frontier_rows(sources)
