"""五注獲利機率的枚舉完整性、獨立窮舉與正式數值測試。"""
from __future__ import annotations

from itertools import combinations
import math
from pathlib import Path

import pytest

from engine.games import LOTTO649, PICK_N, SUPER, TIERS
from research.gates import tree_sha256
from research.portfolio_coverage import _membership_counts
from research.prize_tier_profile import (
    _exact_hit_state_distribution,
)
from research.profit_probability import (
    EXPECTED_CANONICAL_STRUCTURES,
    EXPECTED_LABELED_STRUCTURES,
    EXPECTED_SEARCH_CANDIDATES,
    EXPECTED_SPECIAL_PARTITIONS,
    EXPERIMENT_ID,
    PAIR_INDEXES,
    _exact_main_hit_distribution,
    _exact_super_payout_counts,
    _labeled_linear_shared_structures,
    _membership_counts_from_structure,
    _payout_table,
    build_profit_probability_certificate,
    linear_shared_structures,
    special_partitions,
    verify_profit_probability_certificate,
)


BASE = Path(__file__).parent.parent


def test_linear_structure_and_special_partition_enumerations_are_complete():
    labeled = tuple(_labeled_linear_shared_structures())
    canonical = linear_shared_structures()
    partitions = special_partitions()

    assert len(labeled) == EXPECTED_LABELED_STRUCTURES
    assert len(set(labeled)) == EXPECTED_LABELED_STRUCTURES
    assert len(canonical) == EXPECTED_CANONICAL_STRUCTURES
    assert len(set(canonical)) == EXPECTED_CANONICAL_STRUCTURES
    assert len(partitions) == EXPECTED_SPECIAL_PARTITIONS
    assert len(set(partitions)) == EXPECTED_SPECIAL_PARTITIONS
    for pattern in partitions:
        assert pattern[0] == 0
        assert all(
            value <= max(pattern[:index], default=-1) + 1
            for index, value in enumerate(pattern)
        )


def test_every_canonical_structure_has_six_numbers_and_pair_overlap_at_most_one():
    for structure in linear_shared_structures():
        counts = _membership_counts_from_structure(38, structure)
        assert sum(counts) == 38
        for ticket_index in range(5):
            assert (
                sum(
                    amount
                    for mask, amount in enumerate(counts)
                    if mask & (1 << ticket_index)
                )
                == PICK_N
            )
        for left, right in PAIR_INDEXES:
            assert (
                sum(
                    amount
                    for mask, amount in enumerate(counts)
                    if mask & (1 << left)
                    and mask & (1 << right)
                )
                <= 1
            )


def test_fast_main_hit_dp_matches_existing_exact_dp():
    tickets = [
        {1, 2, 3, 4, 5, 6},
        {4, 5, 6, 7, 8, 9},
        {1, 7, 8, 10, 11, 12},
    ]
    memberships = _membership_counts(12, tickets)
    fast = dict(_exact_main_hit_distribution(12, memberships))
    reference = {
        hits: ways
        for hits, ways, _ in _exact_hit_state_distribution(
            12, memberships
        )
    }

    assert fast == reference
    assert sum(fast.values()) == math.comb(12, PICK_N)


def _independent_small_pool_counts(
    tickets: list[set[int]],
    special_pattern: tuple[int, ...],
    cost: int,
    payout: dict[tuple[int, bool], int],
) -> dict[str, int]:
    tier_keys = {
        (tier.match_main, tier.match_special)
        for tier in TIERS[SUPER]
    }
    counts = {
        "any_prize": 0,
        "nominal_break_even": 0,
        "nominal_strict_profit": 0,
        "empirical_floor_break_even": 0,
        "empirical_floor_strict_profit": 0,
        "at_least_three_main": 0,
        "at_least_four_main": 0,
    }
    total = 0
    for draw in combinations(range(1, 13), PICK_N):
        draw_set = set(draw)
        hits = tuple(
            len(draw_set & ticket) for ticket in tickets
        )
        for special in range(8):
            total += 1
            special_hits = tuple(
                selected == special
                for selected in special_pattern
            )
            results = tuple(zip(hits, special_hits))
            amount = sum(payout.get(result, 0) for result in results)
            counts["any_prize"] += any(
                result in tier_keys for result in results
            )
            counts["nominal_break_even"] += amount >= cost
            counts["nominal_strict_profit"] += amount > cost
            counts["empirical_floor_break_even"] += amount >= cost
            counts["empirical_floor_strict_profit"] += amount > cost
            counts["at_least_three_main"] += max(hits) >= 3
            counts["at_least_four_main"] += max(hits) >= 4
    return {"denominator": total, **counts}


def test_payout_dp_matches_independent_small_pool_brute_force():
    tickets = [
        {1, 2, 3, 4, 5, 6},
        {4, 5, 6, 7, 8, 9},
        {1, 7, 8, 10, 11, 12},
    ]
    special_pattern = (0, 0, 1)
    cost = 300
    payout = _payout_table("nominal", {}, cost)
    memberships = _membership_counts(12, tickets)

    exact = _exact_super_payout_counts(
        12,
        memberships,
        special_pattern,
        payout,
        payout,
        cost,
    )
    brute = _independent_small_pool_counts(
        tickets, special_pattern, cost, payout
    )

    assert exact == brute


@pytest.fixture(scope="module")
def certificate():
    return build_profit_probability_certificate(BASE)


def test_formal_search_finds_unique_profit_structure(certificate):
    row = certificate["games"][SUPER]
    optimum = row["strict_profit_optimum"]
    baseline = row["coverage_optimum_baseline"]

    assert certificate["experiment_id"] == EXPERIMENT_ID
    assert certificate["enumeration_certificate"][
        "total_exact_candidates"
    ] == EXPECTED_SEARCH_CANDIDATES
    assert row["robust_optimum_is_unique"] is True
    assert row["nominal_optimum_is_unique"] is True
    assert row["same_optimum_under_both_payout_models"] is True
    assert optimum["canonical_shared_masks"] == [
        3,
        5,
        6,
        9,
        10,
        12,
        17,
        18,
        20,
        24,
    ]
    assert optimum["special_partition"] == [0, 0, 0, 0, 0]
    assert all(
        pair["main_overlap"] == 1
        for pair in optimum["pairwise_overlaps"]
    )
    assert optimum["ticket_singleton_counts"] == [2] * 5
    assert baseline["canonical_shared_masks"] == []
    assert baseline["special_partition"] == [0, 1, 2, 3, 4]


def test_exact_profit_tradeoff_values(certificate):
    row = certificate["games"][SUPER]
    baseline = row["coverage_optimum_baseline"]["metrics"]
    optimum = row["strict_profit_optimum"]["metrics"]

    assert baseline["empirical_floor_strict_profit"][
        "numerator"
    ] == 305_320
    assert baseline["empirical_floor_strict_profit"][
        "probability"
    ] == pytest.approx(0.013824487508698035)
    assert optimum["empirical_floor_strict_profit"][
        "numerator"
    ] == 1_203_926
    assert optimum["empirical_floor_strict_profit"][
        "probability"
    ] == pytest.approx(0.054512183769149715)
    assert optimum["nominal_strict_profit"][
        "numerator"
    ] == 1_277_366
    assert optimum["nominal_strict_profit"][
        "probability"
    ] == pytest.approx(0.057837450252310935)
    assert optimum["any_prize"]["probability"] == pytest.approx(
        0.2841562009518666
    )
    assert baseline["any_prize"]["probability"] == pytest.approx(
        0.5429629500836931
    )
    assert optimum["at_least_three_main"][
        "probability"
    ] == pytest.approx(0.18285343362742743)
    assert optimum["at_least_four_main"] == baseline[
        "at_least_four_main"
    ]
    assert row["tradeoff"][
        "at_least_four_main_probability_change"
    ] == 0


def test_lotto_any_prize_is_strict_profit_and_remains_global_optimum(
    certificate,
):
    row = certificate["games"][LOTTO649]

    assert row["five_ticket_cost_ntd"] == 250
    assert row["minimum_fixed_face_prize_ntd"] == 400
    assert row["minimum_observed_per_prize_ntd"] == 274
    assert row["any_prize_equals_nominal_strict_profit"] is True
    assert (
        row["any_prize_equals_empirical_floor_strict_profit"]
        is True
    )
    assert row["strict_profit_global_optimum"][
        "probability"
    ]["probability"] == pytest.approx(0.15296613117321764)


def test_history_snapshot_is_frozen_and_forward_safe(certificate):
    history = certificate["official_history"]
    super_row = history["games"][SUPER]
    lotto_row = history["games"][LOTTO649]

    assert history["cutoff_inclusive"] == "2026-07-17"
    assert (super_row["draw_count"], super_row["last_date"]) == (
        1929,
        "2026-07-16",
    )
    assert (lotto_row["draw_count"], lotto_row["last_date"]) == (
        2153,
        "2026-07-17",
    )
    assert len(super_row["normalized_prize_snapshot_hash"]) == 64
    assert len(lotto_row["normalized_prize_snapshot_hash"]) == 64


def test_certificate_is_deterministic_tamper_evident_and_read_only(
    certificate,
):
    before = tree_sha256(BASE / "records")
    verify_profit_probability_certificate(certificate, BASE)
    rebuilt = build_profit_probability_certificate(BASE)

    assert rebuilt == certificate
    assert certificate["source_structural_proof"][
        "certificate_hash"
    ] == (
        "9d74135192e33d5c8f20753841885cd604cd9523248e15f52"
        "dad4d4580742a23"
    )
    assert certificate["decision"]["automatic_switch"] is False
    tampered = {
        **certificate,
        "certificate_hash": "0" * 64,
    }
    with pytest.raises(RuntimeError, match="certificate hash"):
        verify_profit_probability_certificate(tampered, BASE)
    assert tree_sha256(BASE / "records") == before
