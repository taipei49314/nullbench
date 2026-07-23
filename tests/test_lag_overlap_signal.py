from __future__ import annotations

from copy import deepcopy
import math

import pytest

from engine.games import LOTTO649, PICK_N, POOL, SUPER
from research.lag_overlap_signal import (
    E_VALUE_THRESHOLD,
    MODEL_ID,
    evaluate_lag_overlap_model,
    forecast_then_update,
    initial_overlap_state,
    null_overlap_distribution,
    overlap_stratum_size,
    overlap_subset_probability,
    predictive_overlap_distribution,
    validate_overlap_state,
)


@pytest.mark.parametrize("game", [SUPER, LOTTO649])
def test_exact_null_distribution_and_strata_cover_all_subsets(game):
    pool = POOL[game]
    probabilities = null_overlap_distribution(pool)
    assert len(probabilities) == PICK_N + 1
    assert math.fsum(probabilities) == pytest.approx(
        1.0,
        abs=1e-15,
    )
    assert sum(
        overlap_stratum_size(pool, overlap)
        for overlap in range(PICK_N + 1)
    ) == math.comb(pool, PICK_N)


@pytest.mark.parametrize("game", [SUPER, LOTTO649])
def test_zero_history_predictive_is_exact_null(game):
    state = initial_overlap_state(POOL[game])
    assert predictive_overlap_distribution(state) == (
        state["null_probabilities"]
    )
    validate_overlap_state(state)


def test_complete_subset_probability_normalizes_by_overlap_stratum():
    pool = POOL[SUPER]
    state = initial_overlap_state(pool)
    state["counts"] = [11, 7, 5, 3, 2, 1, 1]
    state["transitions"] = sum(state["counts"])
    state["previous_numbers"] = (1, 2, 3, 4, 5, 6)
    predictive = predictive_overlap_distribution(state)
    total = 0.0
    for overlap in range(PICK_N + 1):
        subset = tuple(
            list(range(1, overlap + 1))
            + list(
                range(
                    7,
                    7 + PICK_N - overlap,
                )
            )
        )
        probability = overlap_subset_probability(
            subset,
            previous_numbers=state["previous_numbers"],
            predictive=predictive,
            pool=pool,
        )
        total += overlap_stratum_size(pool, overlap) * probability
    assert total == pytest.approx(1.0, abs=2e-15)


def test_forecast_uses_pre_reveal_state_then_updates_next_target():
    state = initial_overlap_state(POOL[SUPER])
    first = forecast_then_update(state, (1, 2, 3, 4, 5, 6))
    assert first["overlap"] is None
    assert first["raw_regret"] == 0
    assert state["transitions"] == 0

    before_second = deepcopy(state)
    second = forecast_then_update(state, (1, 2, 3, 7, 8, 9))
    assert second["overlap"] == 3
    assert second["predictive"] == (
        predictive_overlap_distribution(before_second)
    )
    assert second["likelihood_ratio"] == pytest.approx(1.0)
    assert state["counts"][3] == 1
    assert state["transitions"] == 1

    alternate = deepcopy(before_second)
    alternate_outcome = forecast_then_update(
        alternate,
        (7, 8, 9, 10, 11, 12),
    )
    assert alternate_outcome["predictive"] == second["predictive"]
    assert alternate["counts"] != state["counts"]


def test_gate_timing_uses_prior_e_value_only():
    state = initial_overlap_state(POOL[SUPER])
    forecast_then_update(state, (1, 2, 3, 4, 5, 6))
    state["log_e_value"] = math.log(E_VALUE_THRESHOLD)
    state["maximum_log_e_value"] = state["log_e_value"]
    outcome = forecast_then_update(
        state,
        (1, 2, 3, 7, 8, 9),
    )
    assert outcome["gate_active"] is True
    assert outcome["safe_regret"] == outcome["raw_regret"]


def test_synthetic_persistent_overlap_can_gain_probability():
    rows = [
        {
            "period": index,
            "date": f"2026-01-{index:02d}",
            "numbers": [1, 2, 3, 4, 5, 6],
        }
        for index in range(1, 9)
    ]
    result = evaluate_lag_overlap_model(
        SUPER,
        rows,
        bootstrap_samples=100,
    )
    assert result["model"] == MODEL_ID
    assert result["transitions"] == len(rows) - 1
    assert result["final_overlap_counts"][6] == len(rows) - 1
    assert result["raw_mean_regret_nats"] < 0
    assert (
        result["raw_geometric_probability_ratio_vs_uniform"]
        > 1
    )
    assert result["final_e_value"] > E_VALUE_THRESHOLD


def test_invalid_state_and_numbers_fail_closed():
    state = initial_overlap_state(POOL[SUPER])
    state["counts"][0] = 1
    with pytest.raises(ValueError):
        validate_overlap_state(state)
    with pytest.raises(ValueError):
        forecast_then_update(
            initial_overlap_state(POOL[SUPER]),
            (1, 1, 2, 3, 4, 5),
        )
