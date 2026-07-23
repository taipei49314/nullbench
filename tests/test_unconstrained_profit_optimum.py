"""無 overlap 守門獲利最優證明的有限枚舉、上界與正式數值測試。"""
from __future__ import annotations

import math
from pathlib import Path

import pytest

from engine.games import POOL, SUPER
from research.gates import tree_sha256
from research.profit_probability import (
    _exact_main_hit_distribution,
)
from research.unconstrained_profit_optimum import (
    EXPECTED_EMPIRICAL_PROPER_UPPERS,
    EXPECTED_MULTIPLICITY_HISTOGRAMS,
    EXPECTED_NOMINAL_SINGLE_BLOCK_UPPERS,
    EXPECTED_THREE_UNIFORM_PROFILES,
    EXPERIMENT_ID,
    FULL_DENOMINATOR,
    MAIN_DRAW_DENOMINATOR,
    NOMINAL_OPTIMUM_COUNT,
    PAIR_MAIN_FOUR_INTERSECTION_COUNTS,
    PROPER_SPECIAL_COMPOSITIONS,
    _hunter_main_four_upper,
    _multiplicity_certificate,
    _nominal_common_special_certificate,
    _pair_main_four_intersection_count,
    _three_uniform_certificate,
    build_unconstrained_profit_certificate,
    multiplicity_histograms,
    nominal_single_block_upper,
    optimum_membership_counts,
    optimum_tickets,
    verify_unconstrained_profit_certificate,
    weighted_hit_distribution,
)


BASE = Path(__file__).parent.parent


def test_multiplicity_histograms_are_complete_and_conserve_incidence():
    rows = multiplicity_histograms()

    assert len(rows) == EXPECTED_MULTIPLICITY_HISTOGRAMS
    assert len(set(rows)) == EXPECTED_MULTIPLICITY_HISTOGRAMS
    assert all(
        sum(
            multiplicity * count
            for multiplicity, count in enumerate(row, 1)
        )
        == 30
        for row in rows
    )
    assert all(sum(row) <= POOL[SUPER] for row in rows)


def test_weighted_histogram_dp_matches_full_ticket_hit_dp():
    histogram = (0, 0, 10, 0, 0)
    weighted = dict(weighted_hit_distribution(histogram))
    full = _exact_main_hit_distribution(
        POOL[SUPER], optimum_membership_counts()
    )
    aggregated = {}
    for hits, ways in full:
        total = sum(hits)
        aggregated[total] = aggregated.get(total, 0) + ways

    assert weighted == aggregated
    assert sum(weighted.values()) == MAIN_DRAW_DENOMINATOR


def test_finite_multiplicity_and_three_uniform_proofs_close():
    multiplicity = _multiplicity_certificate()
    triple = _three_uniform_certificate()

    assert multiplicity["histograms_evaluated"] == (
        EXPECTED_MULTIPLICITY_HISTOGRAMS
    )
    assert multiplicity[
        "unique_maximum_histogram_n1_to_n5"
    ] == [0, 0, 10, 0, 0]
    assert multiplicity[
        "maximum_total_hits_at_least_six_count"
    ] == 1_401_141
    assert multiplicity[
        "non_optimum_histogram_empirical_profit_upper_count"
    ] == 1_551_291
    assert triple["profiles_evaluated"] == (
        EXPECTED_THREE_UNIFORM_PROFILES
    )
    assert triple["unique_maximum_profile"] == [1] * 10
    assert triple[
        "maximum_at_least_four_main_count"
    ] == 35_280
    assert triple[
        "second_best_at_least_four_main_count"
    ] == 34_412


def test_optimum_example_realizes_all_ten_triples_once():
    tickets = optimum_tickets()
    memberships = optimum_membership_counts()

    assert len(tickets) == 5
    assert len({tuple(ticket["numbers"]) for ticket in tickets}) == 5
    assert all(len(ticket["numbers"]) == 6 for ticket in tickets)
    assert all(ticket["special"] == 1 for ticket in tickets)
    assert [
        mask
        for mask, count in enumerate(memberships)
        if mask and count
    ] == [7, 11, 13, 14, 19, 21, 22, 25, 26, 28]
    assert all(
        memberships[mask] == 1
        for mask in (7, 11, 13, 14, 19, 21, 22, 25, 26, 28)
    )


@pytest.fixture(scope="module")
def certificate():
    return build_unconstrained_profit_certificate(BASE)


def test_all_proper_special_partitions_have_strict_global_upper(
    certificate,
):
    rows = certificate["proof"][
        "proper_special_partition_relaxations"
    ]
    actual = {
        tuple(row["special_block_sizes"]): row[
            "total_empirical_strict_profit_upper_count"
        ]
        for row in rows
    }

    assert actual == EXPECTED_EMPIRICAL_PROPER_UPPERS
    assert all(
        row["strictly_below_optimum"] is True for row in rows
    )
    assert max(actual.values()) == 1_582_520
    assert max(actual.values()) < 1_648_101


def test_exact_global_optimum_and_tradeoffs(certificate):
    assert certificate["experiment_id"] == EXPERIMENT_ID
    assert certificate["proof"][
        "global_empirical_optimum_proved"
    ] is True
    row = certificate["games"][SUPER]
    metrics = row["metrics"]

    assert row[
        "empirical_floor_strict_profit_global_maximum"
    ]["numerator"] == 1_648_101
    assert row[
        "empirical_floor_strict_profit_global_maximum"
    ]["denominator"] == FULL_DENOMINATOR
    assert metrics["empirical_floor_strict_profit"][
        "probability"
    ] == pytest.approx(0.07462384281269731)
    assert metrics["nominal_strict_profit"][
        "probability"
    ] == pytest.approx(0.07462384281269731)
    assert metrics["any_prize"]["probability"] == pytest.approx(
        0.2288539947208678
    )
    assert metrics["at_least_three_main"][
        "probability"
    ] == pytest.approx(0.1381854694548193)
    assert metrics["at_least_four_main"][
        "probability"
    ] == pytest.approx(0.012779455503913708)
    assert certificate["comparison"][
        "unconstrained_vs_coverage_ratio"
    ] == pytest.approx(1_648_101 / 305_320)
    assert certificate["comparison"][
        "unconstrained_vs_guarded_ratio"
    ] == pytest.approx(1_648_101 / 1_203_926)


def test_nominal_common_special_subproof_closes(certificate):
    nominal = _nominal_common_special_certificate()

    assert nominal["nominal_only_low_hit_vectors"] == [
        [3, 2, 0, 0, 0],
        [3, 1, 1, 0, 0],
    ]
    assert nominal[
        "non_optimum_histogram_maximum_upper_count"
    ] == 1_642_111
    assert nominal[
        "common_special_nominal_global_optimum_proved"
    ] is True
    assert nominal["certificate_scope"] == (
        "common_special_structures"
    )
    assert certificate["games"][SUPER][
        "nominal_strict_profit_global_maximum"
    ]["numerator"] == 1_648_101


def test_nominal_proper_special_bounds_close_global_gap(certificate):
    proof = certificate["proof"]
    rows = proof["nominal_proper_special_global_bounds"]
    by_composition = {
        tuple(row["special_block_sizes"]): row for row in rows
    }

    assert set(by_composition) == set(PROPER_SPECIAL_COMPOSITIONS)
    assert proof["global_nominal_optimum_proved"] is True
    assert proof[
        "global_nominal_optimum_unique_up_to_relabeling"
    ] is True
    assert all(
        row["global_nominal_strict_profit_upper_count"]
        < NOMINAL_OPTIMUM_COUNT
        and row["strictly_below_optimum"] is True
        for row in rows
    )
    assert by_composition[(4, 1)][
        "global_nominal_strict_profit_upper_count"
    ] == 1_606_875
    assert by_composition[(3, 1, 1)][
        "global_nominal_strict_profit_upper_count"
    ] == 1_596_420
    assert by_composition[(2, 1, 1, 1)][
        "global_nominal_strict_profit_upper_count"
    ] == 1_449_375
    assert by_composition[(1, 1, 1, 1, 1)][
        "global_nominal_strict_profit_upper_count"
    ] == 1_002_820

    three_two = by_composition[(3, 2)]
    assert three_two["dangerous_macro_histograms"] == 160
    assert three_two["labeled_degree_valid_refinements"] == 4_083
    assert three_two["canonical_exact_candidates"] == 565
    assert three_two[
        "maximum_exact_nominal_strict_profit_count"
    ] == 906_434

    two_two_one = by_composition[(2, 2, 1)]
    assert two_two_one["dangerous_macro_histograms"] == 2_098
    assert two_two_one[
        "labeled_degree_valid_refinements"
    ] == 1_721_537
    assert two_two_one["cross_macro_survivors"] == 814_501
    assert two_two_one["hunter_survivors"] == 75_195
    assert two_two_one["canonical_exact_candidates"] == 10_199
    assert two_two_one[
        "maximum_exact_nominal_strict_profit_count"
    ] == 606_888


def test_nominal_single_block_and_hunter_bounds_are_exact():
    assert {
        size: nominal_single_block_upper(size)[
            "low_hit_profit_upper_count"
        ]
        for size in range(1, 5)
    } == EXPECTED_NOMINAL_SINGLE_BLOCK_UPPERS
    assert tuple(
        _pair_main_four_intersection_count(overlap)
        for overlap in range(7)
    ) == PAIR_MAIN_FOUR_INTERSECTION_COUNTS
    assert _hunter_main_four_upper(
        optimum_membership_counts()
    ) == 36_941


def test_certificate_is_deterministic_tamper_evident_and_read_only(
    certificate,
):
    before = tree_sha256(BASE / "records")
    verify_unconstrained_profit_certificate(certificate, BASE)
    rebuilt = build_unconstrained_profit_certificate(BASE)

    assert rebuilt == certificate
    assert certificate["decision"]["automatic_switch"] is False
    assert certificate["source_pareto_certificate"][
        "certificate_hash"
    ] == (
        "b91fb1e1f4a4f7ba6478389b05182761472fcdc9784460967"
        "b9011a739356ee4"
    )
    tampered = {
        **certificate,
        "certificate_hash": "0" * 64,
    }
    with pytest.raises(RuntimeError, match="certificate hash"):
        verify_unconstrained_profit_certificate(
            tampered, BASE
        )
    assert tree_sha256(BASE / "records") == before
    assert math.comb(38, 6) * 8 == FULL_DENOMINATOR
