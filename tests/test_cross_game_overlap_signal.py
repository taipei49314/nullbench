from __future__ import annotations

from copy import deepcopy
import itertools
import math
from pathlib import Path

import pytest

from engine.games import LOTTO649, PICK_N, POOL, SUPER
from research.cross_game_overlap_signal import (
    E_VALUE_THRESHOLD,
    MODEL_ID,
    build_cross_game_pairs,
    cross_game_subset_probability,
    evaluate_cross_game_model,
    forecast_then_update,
    initial_cross_game_state,
    null_overlap_distribution,
    overlap_stratum_size,
    predictive_overlap_distribution,
    validate_cross_game_state,
)
from research.draw_order_signal import load_and_profile_raw_game


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("game", [SUPER, LOTTO649])
@pytest.mark.parametrize("m", range(PICK_N + 1))
def test_exact_null_strata_cover_all_subsets(game, m):
    pool = POOL[game]
    null = null_overlap_distribution(pool, m)
    assert math.fsum(null) == pytest.approx(1.0, abs=2e-15)
    assert sum(
        overlap_stratum_size(pool, m, overlap)
        for overlap in range(PICK_N + 1)
    ) == math.comb(pool, PICK_N)
    assert all(null[k] == 0 for k in range(m + 1, PICK_N + 1))


@pytest.mark.parametrize("m", range(PICK_N + 1))
def test_zero_history_is_exact_uniform_for_every_source_size(m):
    pool = POOL[SUPER]
    state = initial_cross_game_state(pool)
    source = [
        *range(1, m + 1),
        *range(39, 39 + PICK_N - m),
    ]
    target = tuple(range(1, PICK_N + 1))
    probability = cross_game_subset_probability(
        target,
        source,
        state,
        source_pool=POOL[LOTTO649],
    )
    assert probability == pytest.approx(
        1.0 / math.comb(pool, PICK_N),
        rel=1e-12,
        abs=1e-18,
    )


def test_complete_subset_probabilities_normalize_small_pool():
    state = initial_cross_game_state(8)
    state["counts_by_m"][4] = [0, 0, 7, 5, 3, 0, 0]
    state["transitions_by_m"][4] = 15
    source = [1, 2, 3, 8, 9, 10]
    total = sum(
        cross_game_subset_probability(
            target,
            source,
            state,
            source_pool=10,
        )
        for target in itertools.combinations(range(1, 9), PICK_N)
    )
    assert total == pytest.approx(1.0, abs=2e-15)


def test_pairing_uses_strict_prior_ignores_same_day_and_allows_reuse():
    source_rows = [
        {
            "date": "2026-01-01",
            "period": 1,
            "numbers": [1, 2, 3, 4, 5, 6],
        },
        {
            "date": "2026-01-03",
            "period": 2,
            "numbers": [7, 8, 9, 10, 11, 12],
        },
    ]
    target_rows = [
        {
            "date": "2025-12-31",
            "period": 10,
            "numbers": [1, 2, 3, 4, 5, 6],
        },
        {
            "date": "2026-01-02",
            "period": 11,
            "numbers": [1, 2, 3, 7, 8, 9],
        },
        {
            "date": "2026-01-03",
            "period": 12,
            "numbers": [4, 5, 6, 10, 11, 12],
        },
        {
            "date": "2026-01-04",
            "period": 13,
            "numbers": [7, 8, 9, 13, 14, 15],
        },
    ]
    pairs, profile = build_cross_game_pairs(
        SUPER,
        target_rows,
        source_rows,
    )
    assert pairs[0]["source_date"] is None
    assert pairs[1]["source_date"] == "2026-01-01"
    assert pairs[2]["source_date"] == "2026-01-01"
    assert pairs[2]["same_date_source_ignored"] is True
    assert pairs[3]["source_date"] == "2026-01-03"
    assert profile["strict_prior_available"] == 3
    assert profile["missing_source"] == 1
    assert profile["same_date_source_ignored"] == 1
    assert profile["sources_reused"] == 1
    assert profile["maximum_source_reuse"] == 2


def test_forecast_uses_pre_reveal_state_then_updates_same_m():
    state = initial_cross_game_state(POOL[SUPER])
    source = (1, 2, 3, 4, 5, 6)
    before = deepcopy(state)
    first = forecast_then_update(
        state,
        (1, 2, 3, 7, 8, 9),
        source,
        source_pool=POOL[LOTTO649],
    )
    assert first["m"] == 6
    assert first["overlap"] == 3
    assert first["predictive"] == predictive_overlap_distribution(
        before,
        6,
    )
    assert first["likelihood_ratio"] == pytest.approx(1.0)
    assert state["counts_by_m"][6][3] == 1
    assert state["transitions_by_m"][6] == 1

    alternate = deepcopy(before)
    forecast_then_update(
        alternate,
        (7, 8, 9, 10, 11, 12),
        source,
        source_pool=POOL[LOTTO649],
    )
    assert alternate["counts_by_m"][6] != state["counts_by_m"][6]


def test_missing_source_is_uniform_and_does_not_update_state():
    state = initial_cross_game_state(POOL[LOTTO649])
    outcome = forecast_then_update(
        state,
        (1, 2, 3, 4, 5, 6),
        None,
        source_pool=POOL[SUPER],
    )
    assert outcome["regret"] == 0.0
    assert sum(state["transitions_by_m"]) == 0
    validate_cross_game_state(state)


def test_synthetic_persistent_cross_overlap_can_gain_probability():
    source_rows = [
        {
            "date": f"2025-12-{index:02d}",
            "period": index,
            "numbers": [1, 2, 3, 4, 5, 6],
        }
        for index in range(1, 11)
    ]
    target_rows = [
        {
            "date": f"2026-01-{index:02d}",
            "period": 100 + index,
            "numbers": [1, 2, 3, 4, 5, 6],
        }
        for index in range(1, 11)
    ]
    pairs, profile = build_cross_game_pairs(
        SUPER,
        target_rows,
        source_rows,
    )
    result = evaluate_cross_game_model(
        SUPER,
        pairs,
        pairing_profile=profile,
        bootstrap_samples=100,
    )
    assert result["model"] == MODEL_ID
    assert result["mean_regret_nats"] < 0
    assert result["geometric_probability_ratio_vs_uniform"] > 1
    assert result["final_e_value"] > E_VALUE_THRESHOLD


def test_invalid_state_and_same_date_row_order_fail_closed():
    state = initial_cross_game_state(POOL[SUPER])
    state["counts_by_m"][3][4] = 1
    state["transitions_by_m"][3] = 1
    with pytest.raises(ValueError):
        validate_cross_game_state(state)
    duplicate_dates = [
        {
            "date": "2026-01-01",
            "period": index,
            "numbers": [1, 2, 3, 4, 5, 6],
        }
        for index in (1, 2)
    ]
    with pytest.raises(ValueError):
        build_cross_game_pairs(
            SUPER,
            duplicate_dates,
            [
                {
                    "date": "2025-12-31",
                    "period": 3,
                    "numbers": [1, 2, 3, 4, 5, 6],
                }
            ],
        )


def test_live_pairing_profiles_match_frozen_date_boundary():
    rows = {
        game: load_and_profile_raw_game(game, base=ROOT)[0]
        for game in (SUPER, LOTTO649)
    }
    _, super_profile = build_cross_game_pairs(
        SUPER,
        rows[SUPER],
        rows[LOTTO649],
    )
    _, lotto_profile = build_cross_game_pairs(
        LOTTO649,
        rows[LOTTO649],
        rows[SUPER],
    )
    assert super_profile == {
        **super_profile,
        "targets": 1929,
        "strict_prior_available": 1929,
        "missing_source": 0,
        "same_date_source_ignored": 42,
        "lag_days": {"1": 45, "2": 947, "3": 937},
        "unique_sources_used": 1929,
        "sources_reused": 0,
        "maximum_source_reuse": 1,
    }
    assert lotto_profile == {
        **lotto_profile,
        "targets": 2153,
        "strict_prior_available": 2042,
        "missing_source": 111,
        "same_date_source_ignored": 42,
        "lag_days": {"1": 1929, "2": 45, "3": 47, "4": 21},
        "unique_sources_used": 1929,
        "sources_reused": 50,
        "maximum_source_reuse": 4,
    }
