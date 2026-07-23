from __future__ import annotations

import json
from pathlib import Path

import pytest

from research.cross_game_overlap_signal import (
    MODEL_ID as CROSS_GAME_MODEL_ID,
)
from research.probability_frontier_v4 import (
    METHOD_IDS,
    SOURCE_FILES,
    build_conclusion,
    build_frontier_rows,
    run_probability_frontier_v4,
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


def test_frontier_v4_has_fixed_fourteen_method_contract():
    assert len(METHOD_IDS) == 14
    assert len(set(METHOD_IDS)) == 14
    assert CROSS_GAME_MODEL_ID in METHOD_IDS


def test_frontier_v4_includes_cross_game_and_ranks_it():
    rows = build_frontier_rows(_sources())
    cross = next(
        row
        for row in rows
        if row["method_id"] == CROSS_GAME_MODEL_ID
    )
    assert cross["rank"] == 11
    assert cross["strictly_dominated_by_uniform"] is True
    assert cross["both_games_mean_negative"] is False
    assert cross["both_games_bootstrap_upper_negative"] is False


def test_v3_scores_are_immutable_in_v4_mapping():
    sources = _sources()
    v3_rows = {
        row["method_id"]: row
        for row in sources["probability_frontier_v3"][
            "frontier_rows"
        ]
    }
    v4_rows = {
        row["method_id"]: row
        for row in build_frontier_rows(sources)
    }
    for method_id, v3 in v3_rows.items():
        v4 = v4_rows[method_id]
        assert v4["minimax_regret"] == v3["minimax_regret"]
        assert (
            v4["mean_regret_across_games"]
            == v3["mean_regret_across_games"]
        )
        for game in ("super", "lotto649"):
            expected = dict(v3["game_results"][game])
            expected["source_id"] = "probability_frontier_v3"
            assert v4["game_results"][game] == expected


def test_conclusion_retains_uniform_and_freezes_v3():
    conclusion = build_conclusion(build_frontier_rows(_sources()))
    assert conclusion["status"] == (
        "retain_uniform_null_safe_champion"
    )
    assert conclusion["champion_method_id"] == "uniform_null_safe"
    assert conclusion["historically_supported_non_uniform_methods"] == []
    assert conclusion["non_uniform_method_count"] == 13
    assert conclusion["v3_immutable"] is True


def test_live_frontier_v4_validates_and_preserves_records():
    result = run_probability_frontier_v4(base=ROOT)
    assert validate_result(result) == result
    assert result["records_integrity"]["unchanged"] is True
    assert len(result["frontier_rows"]) == 14


def test_frontier_v4_rejects_missing_source():
    sources = _sources()
    sources.pop("cross_game_overlap_signal")
    with pytest.raises(KeyError):
        build_frontier_rows(sources)
