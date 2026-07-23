from __future__ import annotations

import json
from pathlib import Path

import pytest

from research.calendar_regime_signal import (
    MODEL_ID as CALENDAR_MODEL_ID,
)
from research.probability_frontier_v3 import (
    METHOD_IDS,
    SOURCE_FILES,
    build_conclusion,
    build_frontier_rows,
    run_probability_frontier_v3,
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


def test_frontier_v3_has_fixed_thirteen_method_contract():
    assert len(METHOD_IDS) == 13
    assert len(set(METHOD_IDS)) == 13
    assert CALENDAR_MODEL_ID in METHOD_IDS


def test_frontier_v3_includes_calendar_and_ranks_it():
    rows = build_frontier_rows(_sources())
    calendar = next(
        row
        for row in rows
        if row["method_id"] == CALENDAR_MODEL_ID
    )
    assert calendar["rank"] == 13
    assert calendar["strictly_dominated_by_uniform"] is True
    assert calendar["both_games_mean_negative"] is False
    assert calendar["both_games_bootstrap_upper_negative"] is False


def test_v2_scores_are_immutable_in_v3_mapping():
    sources = _sources()
    v2_rows = {
        row["method_id"]: row
        for row in sources["probability_frontier_v2"][
            "frontier_rows"
        ]
    }
    v3_rows = {
        row["method_id"]: row
        for row in build_frontier_rows(sources)
    }
    for method_id, v2 in v2_rows.items():
        v3 = v3_rows[method_id]
        assert v3["minimax_regret"] == v2["minimax_regret"]
        assert (
            v3["mean_regret_across_games"]
            == v2["mean_regret_across_games"]
        )
        for game in ("super", "lotto649"):
            expected = dict(v2["game_results"][game])
            expected["source_id"] = "probability_frontier_v2"
            assert v3["game_results"][game] == expected


def test_conclusion_retains_uniform_and_freezes_v2():
    conclusion = build_conclusion(build_frontier_rows(_sources()))
    assert conclusion["status"] == (
        "retain_uniform_null_safe_champion"
    )
    assert conclusion["champion_method_id"] == "uniform_null_safe"
    assert conclusion["historically_supported_non_uniform_methods"] == []
    assert conclusion["non_uniform_method_count"] == 12
    assert conclusion["v2_immutable"] is True


def test_live_frontier_v3_validates_and_preserves_records():
    result = run_probability_frontier_v3(base=ROOT)
    assert validate_result(result) == result
    assert result["records_integrity"]["unchanged"] is True
    assert len(result["frontier_rows"]) == 13


def test_frontier_v3_rejects_missing_source():
    sources = _sources()
    sources.pop("calendar_regime_signal")
    with pytest.raises(KeyError):
        build_frontier_rows(sources)
