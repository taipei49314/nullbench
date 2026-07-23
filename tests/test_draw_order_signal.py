"""抽出順序子集合模型的數學、時間邊界與資料品質測試。"""
from __future__ import annotations

import itertools
import math
from pathlib import Path

import pytest

from engine.games import LOTTO649, POOL, SUPER
from research.draw_order_signal import (
    ALPHA,
    conditional_order_permutation_test,
    evaluate_position_model,
    initial_position_counts,
    load_and_profile_raw_game,
    position_subset_probability,
)


BASE = Path(__file__).parent.parent


def _trained_small_counts(pool: int) -> list[list[int]]:
    counts = initial_position_counts(pool)
    orders = (
        (1, 2, 3, 4, 5, 6),
        (2, 3, 4, 5, 6, 7),
        (7, 6, 5, 4, 3, 2),
    )
    for order in orders:
        for position, number in enumerate(order):
            counts[position][number] += 1
    return counts


def _brute_probability(
    target: tuple[int, ...],
    counts: list[list[int]],
    *,
    pool: int,
) -> float:
    total = 0.0
    for order in itertools.permutations(target):
        selected = set()
        probability = 1.0
        for position, number in enumerate(order):
            row = counts[position]
            denominator = sum(
                ALPHA + row[candidate]
                for candidate in range(1, pool + 1)
                if candidate not in selected
            )
            probability *= (ALPHA + row[number]) / denominator
            selected.add(number)
        total += probability
    return total


@pytest.mark.parametrize("game", [SUPER, LOTTO649])
def test_zero_history_probability_is_exact_uniform(game):
    pool = POOL[game]
    observed = position_subset_probability(
        (1, 2, 3, 4, 5, 6),
        initial_position_counts(pool),
        pool=pool,
    )
    assert observed == pytest.approx(
        1.0 / math.comb(pool, 6),
        rel=1e-12,
        abs=1e-18,
    )


def test_subset_dp_matches_all_720_orderings():
    pool = 8
    counts = _trained_small_counts(pool)
    target = (1, 2, 3, 4, 5, 6)
    observed = position_subset_probability(
        target,
        counts,
        pool=pool,
    )
    expected = _brute_probability(
        target,
        counts,
        pool=pool,
    )
    assert observed == pytest.approx(expected, rel=1e-13)


def test_subset_probabilities_normalize_over_small_pool():
    pool = 8
    counts = _trained_small_counts(pool)
    total = sum(
        position_subset_probability(
            target,
            counts,
            pool=pool,
        )
        for target in itertools.combinations(range(1, pool + 1), 6)
    )
    assert total == pytest.approx(1.0, rel=1e-12)


def test_evaluate_updates_only_after_current_forecast():
    rows = [
        {
            "period": 1,
            "date": "2026-01-01",
            "numbers": [1, 2, 3, 4, 5, 6],
            "order": [1, 2, 3, 4, 5, 6],
            "special": 1,
        },
        {
            "period": 2,
            "date": "2026-01-02",
            "numbers": [2, 3, 4, 5, 6, 7],
            "order": [7, 6, 5, 4, 3, 2],
            "special": 2,
        },
    ]
    pool = POOL[SUPER]
    counts = initial_position_counts(pool)
    second_probability = position_subset_probability(
        rows[1]["numbers"],
        [
            [
                value + int(number == rows[0]["order"][position])
                for number, value in enumerate(row)
            ]
            for position, row in enumerate(counts)
        ],
        pool=pool,
    )
    second_regret = (
        -math.log(second_probability)
        - math.log(math.comb(pool, 6))
    )
    result = evaluate_position_model(
        SUPER,
        rows,
        bootstrap_samples=20,
        permutation_samples=20,
    )
    assert result["mean_regret_nats"] == pytest.approx(
        second_regret / 2,
        abs=1e-15,
    )
    assert all(
        sum(position) == 2
        for position in result["final_position_counts"]
    )


def test_conditional_permutation_is_deterministic():
    orders = [
        [1, 2, 3, 4, 5, 6],
        [2, 3, 4, 5, 6, 7],
        [7, 6, 5, 4, 3, 2],
    ]
    first = conditional_order_permutation_test(
        orders,
        pool=8,
        samples=50,
        seed="fixed",
    )
    second = conditional_order_permutation_test(
        orders,
        pool=8,
        samples=50,
        seed="fixed",
    )
    assert first == second
    assert 0 < first["p_value"] <= 1


@pytest.mark.parametrize(
    "target",
    [
        [1, 2, 3, 4, 5],
        [1, 2, 3, 4, 5, 5],
        [0, 2, 3, 4, 5, 6],
    ],
)
def test_subset_probability_rejects_invalid_target(target):
    with pytest.raises(ValueError):
        position_subset_probability(
            target,
            initial_position_counts(8),
            pool=8,
        )


@pytest.mark.parametrize("game,expected_draws", [(SUPER, 1929), (LOTTO649, 2153)])
def test_raw_draw_order_is_complete_and_matches_ledger(
    game,
    expected_draws,
):
    rows, profile = load_and_profile_raw_game(game, base=BASE)
    assert len(rows) == expected_draws
    assert profile["status"] == "pass"
    assert profile["draw_order_coverage_rate"] == 1.0
    assert profile["raw_ledger_mismatches"] == 0
    assert profile["row_schema_variants"] == 1

