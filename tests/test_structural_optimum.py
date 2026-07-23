"""五注全域結構最優證明與獨立小池窮舉測試。"""
from __future__ import annotations

from itertools import combinations
from pathlib import Path

import pytest

from engine.games import LOTTO649, SUPER
from research.gates import tree_sha256
from research.portfolio_coverage import (
    _exact_any_prize_favorable_count,
    _membership_counts,
)
from research.structural_optimum import (
    EXPERIMENT_ID,
    PROFILE_COUNT_EXPECTED,
    VALID_PROFILE_COUNT_EXPECTED,
    build_structural_optimum_certificate,
    structural_proof_reference,
    three_ticket_membership_profiles,
    verify_structural_optimum_certificate,
)


BASE = Path(__file__).parent.parent


def _small_pool_tickets(game: str) -> list[dict]:
    rows = (
        (1, 2, 3, 4, 5, 6),
        (4, 5, 6, 7, 8, 9),
        (1, 7, 8, 10, 11, 12),
    )
    return [
        {
            "numbers": list(numbers),
            "special": index + 1 if game == SUPER else None,
        }
        for index, numbers in enumerate(rows)
    ]


def _brute_small_pool(game: str, tickets: list[dict]) -> tuple[int, int]:
    pool = set(range(1, 13))
    favorable = 0
    total = 0
    for draw_tuple in combinations(sorted(pool), 6):
        draw = set(draw_tuple)
        hits = [
            len(set(ticket["numbers"]) & draw)
            for ticket in tickets
        ]
        outcomes = (
            range(1, 9)
            if game == SUPER
            else sorted(pool - draw)
        )
        for extra in outcomes:
            total += 1
            if game == SUPER:
                won = any(
                    hit >= 3
                    or (
                        hit in (1, 2)
                        and ticket["special"] == extra
                    )
                    for hit, ticket in zip(hits, tickets)
                )
            else:
                won = any(
                    hit >= 3
                    or (
                        hit == 2
                        and extra in set(ticket["numbers"])
                    )
                    for hit, ticket in zip(hits, tickets)
                )
            favorable += int(won)
    return favorable, total


def test_three_ticket_profile_enumeration_is_complete_and_unique():
    profiles = list(three_ticket_membership_profiles())

    assert len(profiles) == PROFILE_COUNT_EXPECTED
    assert len(set(profiles)) == PROFILE_COUNT_EXPECTED
    assert all(
        sum(
            amount
            for mask, amount in enumerate(profile)
            if mask & (1 << ticket)
        )
        == 6
        for profile in profiles
        for ticket in range(3)
    )


@pytest.mark.parametrize("game", [SUPER, LOTTO649])
def test_membership_dp_matches_independent_small_pool_brute_force(game):
    tickets = _small_pool_tickets(game)
    counts = _membership_counts(
        12,
        [set(ticket["numbers"]) for ticket in tickets],
    )
    exact = _exact_any_prize_favorable_count(
        game,
        12,
        counts,
        tuple(ticket["special"] for ticket in tickets),
    )

    assert exact == _brute_small_pool(game, tickets)


@pytest.fixture(scope="module")
def certificate():
    return build_structural_optimum_certificate(BASE)


@pytest.mark.parametrize(
    ("game", "any_prize", "three_main"),
    [
        (SUPER, 0.5429629500836931, 0.1920413839918484),
        (LOTTO649, 0.15296613117321764, 0.09290168005643094),
    ],
)
def test_certificate_proves_global_optimum_without_violations(
    certificate,
    game,
    any_prize,
    three_main,
):
    row = certificate["games"][game]

    assert certificate["experiment_id"] == EXPERIMENT_ID
    assert certificate["conclusion"]["global_optimum_proved"] is True
    assert row["any_prize"]["global_optimum_proved"] is True
    assert row["three_main"]["global_optimum_proved"] is True
    assert row["any_prize"][
        "three_ticket_profiles_valid_distinct"
    ] == VALID_PROFILE_COUNT_EXPECTED
    assert row["any_prize"]["triple_charge_violations"] == 0
    assert row["three_main"]["triple_charge_violations"] == 0
    assert row["any_prize"][
        "minimum_non_disjoint_charge_slack_numerator"
    ] > 0
    assert row["three_main"][
        "minimum_non_disjoint_charge_slack_numerator"
    ] > 0
    assert row["any_prize"][
        "global_maximum_probability"
    ] == pytest.approx(any_prize)
    assert row["three_main"][
        "global_maximum_probability"
    ] == pytest.approx(three_main)


def test_super_duplicate_special_is_strictly_suboptimal(certificate):
    proof = certificate["games"][SUPER]["duplicate_special_proof"]

    assert proof[
        "duplicate_special_cannot_reach_global_maximum"
    ] is True
    assert proof["hunter_tree_margin_numerator"] > 0
    assert (
        proof["hunter_upper_bound_favorable_count"]
        < proof["disjoint_distinct_special_favorable_count"]
    )


def test_certificate_is_deterministic_tamper_evident_and_reveal_free(
    certificate,
):
    before = tree_sha256(BASE / "records")
    verify_structural_optimum_certificate(certificate)
    reference = structural_proof_reference()
    rebuilt = build_structural_optimum_certificate(BASE)

    assert rebuilt == certificate
    assert reference == {
        "experiment_id": EXPERIMENT_ID,
        "certificate_hash": certificate["certificate_hash"],
    }
    assert (
        "reveal"
        not in build_structural_optimum_certificate.__code__.co_varnames
    )
    tampered = {
        **certificate,
        "certificate_hash": "0" * 64,
    }
    with pytest.raises(RuntimeError, match="certificate hash"):
        verify_structural_optimum_certificate(tampered)
    assert tree_sha256(BASE / "records") == before
