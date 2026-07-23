"""獎級精確分解的守恆、獨立小池窮舉與正式結果測試。"""
from __future__ import annotations

from itertools import combinations
import math
from pathlib import Path

import pytest

from engine.games import LOTTO649, PICK_N, POOL, SUPER, TIERS
from research.gates import tree_sha256
from research.portfolio_coverage import _membership_counts
from research.prize_tier_profile import (
    EXPERIMENT_ID,
    _exact_hit_state_distribution,
    _exact_prize_profile_from_memberships,
    build_prize_tier_certificate,
    exact_prize_profile,
    verify_prize_tier_certificate,
)
from research.structural_optimum import disjoint_reference_tickets


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


def _independent_brute_profile(
    game: str,
    pool: int,
    tickets: list[dict],
) -> dict:
    tier_lookup = {
        (tier.match_main, tier.match_special): tier.rank
        for tier in TIERS[game]
    }
    best = {tier.rank: 0 for tier in TIERS[game]}
    awarded = {tier.rank: 0 for tier in TIERS[game]}
    winning_counts = {
        count: 0 for count in range(len(tickets) + 1)
    }
    maximum_hits = {hits: 0 for hits in range(PICK_N + 1)}
    no_prize = 0
    total = 0
    universe = set(range(1, pool + 1))
    for main_tuple in combinations(range(1, pool + 1), PICK_N):
        main = set(main_tuple)
        hits = tuple(
            len(main & set(ticket["numbers"]))
            for ticket in tickets
        )
        extras = (
            range(1, 9)
            if game == SUPER
            else sorted(universe - main)
        )
        for extra in extras:
            total += 1
            ranks = []
            for hit, ticket in zip(hits, tickets):
                special_hit = (
                    ticket["special"] == extra
                    if game == SUPER
                    else extra in set(ticket["numbers"])
                )
                rank = tier_lookup.get((hit, special_hit))
                if rank is not None:
                    ranks.append(rank)
                    awarded[rank] += 1
            winning_counts[len(ranks)] += 1
            maximum_hits[max(hits)] += 1
            if ranks:
                best[min(ranks)] += 1
            else:
                no_prize += 1
    return {
        "denominator": total,
        "best_tier_counts": best,
        "awarded_tier_ticket_counts": awarded,
        "winning_ticket_count_counts": winning_counts,
        "maximum_main_hits_counts": maximum_hits,
        "no_prize_count": no_prize,
    }


@pytest.mark.parametrize("game", [SUPER, LOTTO649])
def test_exact_tier_dp_matches_independent_small_pool_brute_force(game):
    tickets = _small_pool_tickets(game)
    membership_counts = _membership_counts(
        12,
        [set(ticket["numbers"]) for ticket in tickets],
    )
    exact = _exact_prize_profile_from_memberships(
        game,
        12,
        membership_counts,
        tuple(ticket["special"] for ticket in tickets),
    )

    assert exact == _independent_brute_profile(
        game, 12, tickets
    )


def test_exact_hit_state_distribution_conserves_draws_and_selections():
    tickets = _small_pool_tickets(LOTTO649)
    membership_counts = _membership_counts(
        12,
        [set(ticket["numbers"]) for ticket in tickets],
    )
    distribution = _exact_hit_state_distribution(
        12, membership_counts
    )

    assert sum(row[1] for row in distribution) == math.comb(12, 6)
    for _, ways, selected_by_mask in distribution:
        assert sum(selected_by_mask) == PICK_N * ways
        assert all(
            selected
            <= membership_counts[mask] * ways
            for mask, selected in enumerate(selected_by_mask)
        )


@pytest.fixture(scope="module")
def certificate():
    return build_prize_tier_certificate(BASE)


@pytest.mark.parametrize(
    ("game", "any_prize", "three_main"),
    [
        (SUPER, 0.5429629500836931, 0.1920413839918484),
        (LOTTO649, 0.15296613117321764, 0.09290168005643094),
    ],
)
def test_five_ticket_profile_matches_proved_union_probabilities(
    certificate,
    game,
    any_prize,
    three_main,
):
    row = certificate["games"][game]
    profile = row["five_ticket_profile"]
    curve = row["ticket_count_curve"]

    assert certificate["experiment_id"] == EXPERIMENT_ID
    assert profile["any_prize"]["probability"] == pytest.approx(
        any_prize
    )
    assert curve[-1][
        "at_least_three_main"
    ]["probability"] == pytest.approx(three_main)
    assert sum(
        tier["probability"]
        for tier in profile["best_tier_distribution"]
    ) == pytest.approx(any_prize)
    assert (
        sum(
            item["probability"]
            for item in profile[
                "winning_ticket_count_distribution"
            ]
        )
        == pytest.approx(1)
    )


@pytest.mark.parametrize("game", [SUPER, LOTTO649])
def test_ticket_count_curve_is_monotone_with_diminishing_union_gain(
    certificate,
    game,
):
    curve = certificate["games"][game]["ticket_count_curve"]
    any_probabilities = [
        row["any_prize"]["probability"] for row in curve
    ]
    any_marginals = [
        row["marginal_any_prize"]["probability"] for row in curve
    ]
    three_probabilities = [
        row["at_least_three_main"]["probability"]
        for row in curve
    ]
    three_marginals = [
        row["marginal_at_least_three_main"]["probability"]
        for row in curve
    ]

    assert all(
        left < right
        for left, right in zip(
            any_probabilities, any_probabilities[1:]
        )
    )
    assert all(
        left > right
        for left, right in zip(any_marginals, any_marginals[1:])
    )
    assert all(
        left < right
        for left, right in zip(
            three_probabilities, three_probabilities[1:]
        )
    )
    assert all(
        left > right
        for left, right in zip(
            three_marginals, three_marginals[1:]
        )
    )


def test_five_ticket_jackpot_counts_are_exact(certificate):
    super_jackpot = certificate["games"][SUPER][
        "jackpot_probability_five_tickets"
    ]
    lotto_jackpot = certificate["games"][LOTTO649][
        "jackpot_probability_five_tickets"
    ]

    assert super_jackpot["numerator"] == 5
    assert super_jackpot["denominator"] == (
        math.comb(POOL[SUPER], PICK_N) * 8
    )
    assert lotto_jackpot["numerator"] == 5 * (
        POOL[LOTTO649] - PICK_N
    )
    assert lotto_jackpot["denominator"] == (
        math.comb(POOL[LOTTO649], PICK_N)
        * (POOL[LOTTO649] - PICK_N)
    )


@pytest.mark.parametrize("game", [SUPER, LOTTO649])
def test_public_profile_matches_reference_certificate(
    certificate,
    game,
):
    profile = exact_prize_profile(
        game, disjoint_reference_tickets(game)
    )

    assert profile == certificate["games"][game][
        "five_ticket_profile"
    ]


def test_certificate_is_deterministic_tamper_evident_and_read_only(
    certificate,
):
    before = tree_sha256(BASE / "records")
    verify_prize_tier_certificate(certificate)
    rebuilt = build_prize_tier_certificate(BASE)

    assert rebuilt == certificate
    assert (
        "reveal"
        not in build_prize_tier_certificate.__code__.co_varnames
    )
    tampered = {
        **certificate,
        "certificate_hash": "0" * 64,
    }
    with pytest.raises(RuntimeError, match="certificate hash"):
        verify_prize_tier_certificate(tampered)
    assert tree_sha256(BASE / "records") == before
