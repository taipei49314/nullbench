"""開獎星期完整 subset 機率的數學與時間邊界測試。"""
from __future__ import annotations

from datetime import date
import itertools
import math
from pathlib import Path

import pytest

from engine.games import LOTTO649, PICK_N, POOL, SUPER
import research.calendar_regime_signal as calendar
from research.calendar_regime_signal import (
    REGULAR_WEEKDAYS,
    evaluate_calendar_model,
    initial_weekday_counts,
    weekday_subset_probability,
)


BASE = Path(__file__).parent.parent


@pytest.mark.parametrize("game", [SUPER, LOTTO649])
def test_zero_same_weekday_history_is_exact_uniform(game):
    pool = POOL[game]
    regular = REGULAR_WEEKDAYS[game]
    states = initial_weekday_counts(pool, regular)
    probability = weekday_subset_probability(
        tuple(range(1, PICK_N + 1)),
        states,
        pool=pool,
        weekday=regular[0],
        regular_weekdays=regular,
    )
    assert math.isclose(
        probability,
        1.0 / math.comb(pool, PICK_N),
        rel_tol=1e-12,
        abs_tol=1e-18,
    )


def test_off_schedule_is_uniform_even_with_trained_states():
    states = initial_weekday_counts(8, (1, 4))
    states[1] = [0, 2, 2, 2, 2, 1, 1, 1, 1]
    probability = weekday_subset_probability(
        (1, 2, 3, 4, 5, 8),
        states,
        pool=8,
        weekday=2,
        regular_weekdays=(1, 4),
    )
    assert math.isclose(
        probability,
        1.0 / math.comb(8, PICK_N),
        rel_tol=1e-12,
        abs_tol=1e-15,
    )


def test_small_pool_probabilities_normalize_for_weekday_model():
    states = initial_weekday_counts(8, (1, 4))
    states[1] = [0, 2, 2, 2, 2, 1, 1, 1, 1]
    total = sum(
        weekday_subset_probability(
            target,
            states,
            pool=8,
            weekday=1,
            regular_weekdays=(1, 4),
        )
        for target in itertools.combinations(range(1, 9), PICK_N)
    )
    assert math.isclose(total, 1.0, rel_tol=1e-12, abs_tol=1e-12)


def test_forecast_before_update_and_weekday_states_are_isolated(
    monkeypatch,
):
    observed = []
    original = calendar.weekday_subset_probability

    def recording_probability(
        target,
        states,
        *,
        pool,
        weekday,
        regular_weekdays,
    ):
        observed.append(
            (
                weekday,
                {
                    key: sum(value)
                    for key, value in states.items()
                },
            )
        )
        return original(
            target,
            states,
            pool=pool,
            weekday=weekday,
            regular_weekdays=regular_weekdays,
        )

    monkeypatch.setattr(
        calendar,
        "weekday_subset_probability",
        recording_probability,
    )
    rows = [
        {
            "date": "2026-01-05",
            "period": 1,
            "numbers": [1, 2, 3, 4, 5, 6],
        },
        {
            "date": "2026-01-08",
            "period": 2,
            "numbers": [7, 8, 9, 10, 11, 12],
        },
        {
            "date": "2026-01-12",
            "period": 3,
            "numbers": [13, 14, 15, 16, 17, 18],
        },
    ]
    result = evaluate_calendar_model(
        SUPER,
        rows,
        bootstrap_samples=20,
    )
    assert observed == [
        (0, {0: 0, 3: 0}),
        (3, {0: PICK_N, 3: 0}),
        (0, {0: PICK_N, 3: PICK_N}),
    ]
    assert sum(result["final_weekday_label_counts"]["0"]) == 12
    assert sum(result["final_weekday_label_counts"]["3"]) == 6


def test_off_schedule_draw_does_not_update_regular_state():
    rows = [
        {
            "date": "2026-02-17",
            "period": 1,
            "numbers": [1, 2, 3, 4, 5, 6],
        },
        {
            "date": "2026-02-18",
            "period": 2,
            "numbers": [7, 8, 9, 10, 11, 12],
        },
        {
            "date": "2026-02-20",
            "period": 3,
            "numbers": [13, 14, 15, 16, 17, 18],
        },
    ]
    result = evaluate_calendar_model(
        LOTTO649,
        rows,
        bootstrap_samples=20,
    )
    assert result["off_schedule_draws"] == 1
    assert result["off_schedule_max_abs_regret"] == 0.0
    assert sum(result["final_weekday_label_counts"]["1"]) == PICK_N
    assert sum(result["final_weekday_label_counts"]["4"]) == PICK_N


def test_rejects_non_increasing_dates():
    rows = [
        {"date": "2026-01-08", "numbers": [1, 2, 3, 4, 5, 6]},
        {"date": "2026-01-05", "numbers": [7, 8, 9, 10, 11, 12]},
    ]
    with pytest.raises(ValueError):
        evaluate_calendar_model(
            SUPER,
            rows,
            bootstrap_samples=20,
        )


@pytest.mark.parametrize("game", [SUPER, LOTTO649])
def test_raw_schedule_and_main_numbers_match_contract(game):
    rows, profile = calendar.load_and_profile_raw_game(
        game,
        base=BASE,
    )
    counts = {str(weekday): 0 for weekday in range(7)}
    for row in rows:
        counts[str(date.fromisoformat(row["date"]).weekday())] += 1
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
    if game == SUPER:
        assert counts == {
            "0": 964,
            "1": 0,
            "2": 0,
            "3": 965,
            "4": 0,
            "5": 0,
            "6": 0,
        }
    else:
        assert counts == {
            "0": 21,
            "1": 1020,
            "2": 19,
            "3": 21,
            "4": 1020,
            "5": 26,
            "6": 26,
        }
