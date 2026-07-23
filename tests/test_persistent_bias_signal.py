"""持續球號偏差完整 subset 機率的數學與時間邊界測試。"""
from __future__ import annotations

import itertools
import math
from pathlib import Path

import pytest

from engine.games import LOTTO649, PICK_N, POOL, SUPER
import research.persistent_bias_signal as persistent
from research.persistent_bias_signal import (
    ALPHA,
    evaluate_persistent_model,
    initial_label_counts,
    persistent_subset_probability,
)


BASE = Path(__file__).parent.parent


def _trained_small_counts() -> list[int]:
    # 總和 12，等於兩期各六個主號。
    return [0, 2, 2, 2, 2, 1, 1, 1, 1]


def _brute_probability(
    target: tuple[int, ...],
    counts: list[int],
    *,
    pool: int,
) -> float:
    weights = {
        number: ALPHA + counts[number]
        for number in range(1, pool + 1)
    }
    total = sum(weights.values())
    probability = 0.0
    for order in itertools.permutations(target):
        remaining = total
        path_probability = 1.0
        for number in order:
            path_probability *= weights[number] / remaining
            remaining -= weights[number]
        probability += path_probability
    return probability


@pytest.mark.parametrize("game", [SUPER, LOTTO649])
def test_zero_history_probability_is_exact_uniform(game):
    pool = POOL[game]
    target = tuple(range(1, PICK_N + 1))
    probability = persistent_subset_probability(
        target,
        initial_label_counts(pool),
        pool=pool,
    )
    assert math.isclose(
        probability,
        1.0 / math.comb(pool, PICK_N),
        rel_tol=1e-12,
        abs_tol=1e-18,
    )


def test_subset_dp_matches_all_720_orderings():
    counts = _trained_small_counts()
    target = (1, 2, 3, 4, 5, 8)
    exact = persistent_subset_probability(
        target,
        counts,
        pool=8,
    )
    brute = _brute_probability(target, counts, pool=8)
    assert math.isclose(
        exact,
        brute,
        rel_tol=1e-12,
        abs_tol=1e-15,
    )


def test_subset_probabilities_normalize_over_small_pool():
    counts = _trained_small_counts()
    total = sum(
        persistent_subset_probability(
            target,
            counts,
            pool=8,
        )
        for target in itertools.combinations(range(1, 9), PICK_N)
    )
    assert math.isclose(total, 1.0, rel_tol=1e-12, abs_tol=1e-12)


def test_evaluate_updates_only_after_current_forecast(monkeypatch):
    observed_count_totals = []
    original = persistent.persistent_subset_probability

    def recording_probability(target, counts, *, pool, alpha=ALPHA):
        observed_count_totals.append(sum(counts))
        return original(target, counts, pool=pool, alpha=alpha)

    monkeypatch.setattr(
        persistent,
        "persistent_subset_probability",
        recording_probability,
    )
    rows = [
        {
            "date": "2026-01-01",
            "period": 1,
            "numbers": [1, 2, 3, 4, 5, 6],
        },
        {
            "date": "2026-01-02",
            "period": 2,
            "numbers": [7, 8, 9, 10, 11, 12],
        },
    ]
    result = evaluate_persistent_model(
        SUPER,
        rows,
        bootstrap_samples=20,
    )
    assert observed_count_totals == [0, PICK_N]
    assert sum(result["final_label_counts"]) == 2 * PICK_N


@pytest.mark.parametrize(
    "target",
    [
        [1, 2, 3, 4, 5],
        [1, 2, 3, 4, 5, 5],
        [0, 1, 2, 3, 4, 5],
        [1, 2, 3, 4, 5, 9],
    ],
)
def test_subset_probability_rejects_invalid_target(target):
    with pytest.raises(ValueError):
        persistent_subset_probability(
            target,
            initial_label_counts(8),
            pool=8,
        )


def test_subset_probability_rejects_invalid_count_state():
    counts = initial_label_counts(8)
    counts[1] = 1
    with pytest.raises(ValueError):
        persistent_subset_probability(
            [1, 2, 3, 4, 5, 6],
            counts,
            pool=8,
        )


def test_subset_probability_rejects_impossible_per_number_count():
    counts = initial_label_counts(8)
    counts[1] = PICK_N
    with pytest.raises(ValueError):
        persistent_subset_probability(
            [1, 2, 3, 4, 5, 6],
            counts,
            pool=8,
        )


@pytest.mark.parametrize("game", [SUPER, LOTTO649])
def test_raw_main_numbers_are_complete_and_match_ledger(game):
    rows, profile = persistent.load_and_profile_raw_game(
        game,
        base=BASE,
    )
    assert profile["status"] == "pass"
    assert profile["draws"] == len(rows)
    assert profile["raw_ledger_mismatches"] == 0
    assert all(
        len(row["numbers"]) == PICK_N
        and len(set(row["numbers"])) == PICK_N
        and all(
            1 <= number <= POOL[game]
            for number in row["numbers"]
        )
        for row in rows
    )
