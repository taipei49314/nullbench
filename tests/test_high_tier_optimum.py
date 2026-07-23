"""高獎級 union bound、門檻交集與證書完整性測試。"""
from __future__ import annotations

from copy import deepcopy
from itertools import combinations
import math
from pathlib import Path

import pytest

from engine.games import LOTTO649, PICK_N, POOL, SUPER
from research.gates import tree_sha256
from research.high_tier_optimum import (
    EXPERIMENT_ID,
    HIGH_TIER_CUTOFF_RANK,
    MAIN_THRESHOLDS,
    build_high_tier_optimum_certificate,
    verify_high_tier_optimum_certificate,
)
from research.portfolio_coverage import (
    _pair_intersection_count,
    _single_favorable_count,
)
from research.structural_optimum import structural_proof_reference


BASE = Path(__file__).parent.parent


def _brute_pair_intersection(
    pool: int,
    overlap: int,
    threshold: int,
) -> int:
    left = set(range(1, PICK_N + 1))
    right = set(range(1, overlap + 1)) | set(
        range(PICK_N + 1, PICK_N + 1 + PICK_N - overlap)
    )
    return sum(
        len(left & set(draw)) >= threshold
        and len(right & set(draw)) >= threshold
        for draw in combinations(range(1, pool + 1), PICK_N)
    )


@pytest.mark.parametrize("threshold", [4, 5, 6])
def test_pair_intersections_match_independent_small_pool_brute_force(
    threshold,
):
    for overlap in range(PICK_N):
        assert _pair_intersection_count(
            12, overlap, threshold
        ) == _brute_pair_intersection(
            12, overlap, threshold
        )


@pytest.fixture(scope="module")
def certificate():
    return build_high_tier_optimum_certificate(BASE)


@pytest.mark.parametrize("game", [SUPER, LOTTO649])
def test_all_main_thresholds_are_globally_maximized(
    certificate,
    game,
):
    rows = certificate["games"][game]["main_hit_thresholds"]

    assert [row["minimum_main_hits"] for row in rows] == list(
        MAIN_THRESHOLDS
    )
    assert all(row["global_optimum_proved"] for row in rows)
    for row in rows[1:]:
        assert (
            row["disjoint_five_ticket_favorable_count"]
            == row["five_ticket_universal_union_upper_count"]
            == 5 * row["single_ticket_favorable_count"]
        )
    assert rows[1]["known_sufficient_pairwise_overlap_max"] == 1
    assert rows[2]["known_sufficient_pairwise_overlap_max"] == 3
    assert rows[3]["known_sufficient_pairwise_overlap_max"] == 5


@pytest.mark.parametrize("game", [SUPER, LOTTO649])
def test_every_high_tier_cumulative_union_attains_upper_bound(
    certificate,
    game,
):
    row = certificate["games"][game]
    tiers = row["cumulative_high_tier_union_bounds"]

    assert len(tiers) == HIGH_TIER_CUTOFF_RANK[game]
    assert all(
        tier["union_upper_attained"]
        and tier["global_optimum_proved"]
        and tier["disjoint_five_ticket_cumulative_count"]
        == tier["five_ticket_universal_union_upper_count"]
        for tier in tiers
    )
    boundary = row["first_non_exclusive_cumulative_tier"]
    assert boundary["maximum_best_tier_rank"] == (
        HIGH_TIER_CUTOFF_RANK[game] + 1
    )
    assert boundary["union_upper_attained"] is False
    assert boundary["union_upper_deficit_count"] > 0


def test_expected_official_threshold_probabilities(certificate):
    rows = {
        game: {
            row["minimum_main_hits"]: row[
                "global_maximum_probability"
            ]
            for row in certificate["games"][game][
                "main_hit_thresholds"
            ]
        }
        for game in (SUPER, LOTTO649)
    }

    assert rows[SUPER][4] == pytest.approx(
        0.013824487508698035
    )
    assert rows[SUPER][5] == pytest.approx(
        0.0003495514331427644
    )
    assert rows[SUPER][6] == pytest.approx(
        5 / math.comb(POOL[SUPER], PICK_N)
    )
    assert rows[LOTTO649][4] == pytest.approx(
        0.00493570567576118
    )
    assert rows[LOTTO649][5] == pytest.approx(
        9.260705375413979e-05
    )
    assert rows[LOTTO649][6] == pytest.approx(
        5 / math.comb(POOL[LOTTO649], PICK_N)
    )


def test_supplement_preserves_v1_reference_and_formal_records(
    certificate,
):
    before = tree_sha256(BASE / "records")
    assert certificate["experiment_id"] == EXPERIMENT_ID
    assert certificate["source_structural_proof"] == {
        "experiment_id": "five-ticket-structural-optimum-proof-v1",
        "certificate_hash": (
            "9d74135192e33d5c8f20753841885cd604cd9523248e15f52"
            "dad4d4580742a23"
        ),
    }
    assert structural_proof_reference() == certificate[
        "source_structural_proof"
    ]
    verify_high_tier_optimum_certificate(certificate)
    rebuilt = build_high_tier_optimum_certificate(BASE)
    assert rebuilt == certificate
    tampered = deepcopy(certificate)
    tampered["games"][SUPER]["main_hit_thresholds"][1][
        "global_optimum_proved"
    ] = False
    with pytest.raises(RuntimeError, match="certificate hash"):
        verify_high_tier_optimum_certificate(tampered)
    assert tree_sha256(BASE / "records") == before
