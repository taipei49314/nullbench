"""階段 1：歷史資料品質閘門的完整測試。"""
from dataclasses import replace
from pathlib import Path

import pytest

from engine.games import LOTTO649, SUPER, TIERS
from engine.store import DrawStore
from research.backtest import profile_data
from research.gates import (
    StageGateError,
    build_data_quality_gate,
    require_gate,
)


DATA = Path(__file__).parent.parent / "data"


@pytest.fixture(scope="module")
def store():
    return DrawStore(DATA)


def test_official_ledgers_pass_and_are_fingerprinted(store):
    profiles = [
        profile_data(game, store.draws(game)) for game in (SUPER, LOTTO649)
    ]
    gate = build_data_quality_gate(profiles)
    require_gate(gate)
    assert gate["status"] == "pass"
    assert all(len(profile["dataset_sha256"]) == 64 for profile in profiles)
    assert all(profile["ordered_chronologically"] for profile in profiles)


def test_empty_dataset_fails_cleanly():
    profile = profile_data(SUPER, [])
    assert profile["quality_status"] == "fail"
    assert profile["date_min"] is None
    assert profile["period_min"] is None
    assert "empty_dataset" in profile["quality_failures"]


@pytest.mark.parametrize(
    ("mutation", "failure"),
    [
        (lambda draw: replace(draw, date="not-a-date"), "invalid_dates"),
        (lambda draw: replace(draw, game=LOTTO649), "game_mismatches"),
        (lambda draw: replace(draw, period=0), "invalid_periods"),
        (lambda draw: replace(draw, numbers=(1, 1, 2, 3, 4, 5)), "invalid_numbers"),
        (lambda draw: replace(draw, special=99), "invalid_special"),
    ],
)
def test_illegal_draw_fields_fail_profile(store, mutation, failure):
    draw = mutation(store.draws(SUPER)[0])
    profile = profile_data(SUPER, [draw])
    assert profile["quality_status"] == "fail"
    assert failure in profile["quality_failures"]


def test_duplicates_and_unsorted_draws_fail_profile(store):
    first, second = store.draws(SUPER)[:2]
    duplicate = replace(second, period=first.period)
    duplicate_profile = profile_data(SUPER, [first, duplicate])
    assert duplicate_profile["duplicate_periods"] == 1
    assert duplicate_profile["quality_status"] == "fail"

    unsorted_profile = profile_data(SUPER, [second, first])
    assert unsorted_profile["ordered_chronologically"] is False
    assert "not_chronological" in unsorted_profile["quality_failures"]


def test_missing_and_negative_prize_data_fail_profile(store):
    draw = store.draws(SUPER)[0]
    missing = dict(draw.prizes)
    missing.pop(TIERS[SUPER][0].api_key)
    missing_profile = profile_data(SUPER, [replace(draw, prizes=missing)])
    assert "missing_prize_fields" in missing_profile["quality_failures"]

    invalid = {key: dict(value) for key, value in draw.prizes.items()}
    invalid[TIERS[SUPER][0].api_key]["per_prize"] = -1
    invalid_profile = profile_data(SUPER, [replace(draw, prizes=invalid)])
    assert invalid_profile["invalid_prize_records"] == 1
    assert "invalid_prize_records" in invalid_profile["quality_failures"]


def test_lotto_extra_draw_schedule_is_warning_not_failure(store):
    draws = store.draws(LOTTO649)
    profile = profile_data(LOTTO649, draws)
    assert profile["off_regular_schedule_draws"] > 0
    assert profile["weeks_with_extra_draws"] > 0
    assert profile["quality_status"] == "pass"


def test_gate_rejects_missing_or_failed_game(store):
    super_profile = profile_data(SUPER, store.draws(SUPER))
    missing_gate = build_data_quality_gate([super_profile])
    with pytest.raises(StageGateError, match="games_exactly_once"):
        require_gate(missing_gate)

    bad_lotto = profile_data(LOTTO649, [])
    failed_gate = build_data_quality_gate([super_profile, bad_lotto])
    with pytest.raises(StageGateError, match="lotto649.nonempty"):
        require_gate(failed_gate)
