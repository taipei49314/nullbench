"""開獎前辯論排序到獲利五注結構的純函式測試。"""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from engine.agent_loop import canonical_hash
from research.profit_portfolio_forward import (
    COMMON_SPECIAL_CANDIDATE_HASH,
    COMMON_SPECIAL_SHADOW_EXPERIMENT_ID,
    EXACT_METRICS,
    GUARDED_PROFIT,
    UNCONSTRAINED_PROFIT,
    UNCONSTRAINED_PROOF,
    build_profit_portfolio_shadows,
    verify_profit_portfolio_shadows,
)


BASE = Path(__file__).parent.parent


def _shadow() -> dict:
    return build_profit_portfolio_shadows(
        source_decision_hash="d" * 64,
        support_evidence_hash="e" * 64,
        ranked_main_numbers=list(range(1, 31)),
        selected_special=7,
    )


def _common_candidate() -> dict:
    artifact = json.loads(
        (
            BASE
            / "research"
            / "results"
            / "mechanism_signal.json"
        ).read_text(encoding="utf-8")
    )
    return artifact[
        "future_profit_common_special_shadow_candidate"
    ]


def test_builds_two_exact_profit_structures_from_debate_ranking():
    shadow = _shadow()
    guarded = shadow["portfolios"][GUARDED_PROFIT]
    unconstrained = shadow["portfolios"][UNCONSTRAINED_PROFIT]

    assert set(shadow["portfolios"]) == {
        GUARDED_PROFIT,
        UNCONSTRAINED_PROFIT,
    }
    assert shadow["selected_special"] == 7
    assert guarded["ranked_main_prefix"] == list(range(1, 21))
    assert unconstrained["ranked_main_prefix"] == list(range(1, 11))
    assert guarded["structure"]["main_union_size"] == 20
    assert guarded["structure"]["pairwise_main_overlaps"] == [1] * 10
    assert unconstrained["structure"]["main_union_size"] == 10
    assert (
        unconstrained["structure"]["pairwise_main_overlaps"]
        == [3] * 10
    )
    assert all(
        ticket["special"] == 7
        for row in shadow["portfolios"].values()
        for ticket in row["tickets"]
    )
    assert guarded["exact_metrics"] == EXACT_METRICS[GUARDED_PROFIT]
    assert unconstrained["exact_metrics"] == (
        EXACT_METRICS[UNCONSTRAINED_PROFIT]
    )
    payload = {
        key: value
        for key, value in shadow.items()
        if key != "shadow_hash"
    }
    assert shadow["shadow_hash"] == canonical_hash(payload)
    assert "common_special_shadow" not in shadow


def test_common_special_shadow_changes_only_special_and_is_tamper_evident():
    candidate = _common_candidate()
    shadow = build_profit_portfolio_shadows(
        source_decision_hash="d" * 64,
        support_evidence_hash="e" * 64,
        ranked_main_numbers=list(range(1, 31)),
        selected_special=7,
        common_special_candidate=candidate,
    )
    common = shadow["common_special_shadow"]

    assert common["experiment_id"] == (
        COMMON_SPECIAL_SHADOW_EXPERIMENT_ID
    )
    assert common["candidate_hash"] == COMMON_SPECIAL_CANDIDATE_HASH
    assert common["baseline_special"] == 7
    assert common["selected_special"] == 2
    for portfolio_id in (GUARDED_PROFIT, UNCONSTRAINED_PROFIT):
        baseline = shadow["portfolios"][portfolio_id]
        comparison = common["portfolios"][portfolio_id]
        assert [
            ticket["numbers"] for ticket in comparison["tickets"]
        ] == [ticket["numbers"] for ticket in baseline["tickets"]]
        assert comparison["structure"] == baseline["structure"]
        assert all(
            ticket["special"] == 2
            for ticket in comparison["tickets"]
        )
    payload = {
        key: value
        for key, value in common.items()
        if key != "shadow_hash"
    }
    assert common["shadow_hash"] == canonical_hash(payload)
    assert verify_profit_portfolio_shadows(
        shadow,
        expected_source_decision_hash="d" * 64,
        expected_support_evidence_hash="e" * 64,
        expected_ranked_main_numbers=list(range(1, 31)),
        expected_selected_special=7,
        expected_common_special_candidate=candidate,
    ) == shadow


def test_common_special_candidate_rejects_rehashed_semantic_tampering():
    candidate = _common_candidate()
    candidate["selected_special"] = 3
    payload = {
        key: value
        for key, value in candidate.items()
        if key != "candidate_hash"
    }
    candidate["candidate_hash"] = canonical_hash(payload)

    with pytest.raises(ValueError, match="共同第二區"):
        build_profit_portfolio_shadows(
            source_decision_hash="d" * 64,
            support_evidence_hash="e" * 64,
            ranked_main_numbers=list(range(1, 31)),
            selected_special=7,
            common_special_candidate=candidate,
        )


def test_structure_uses_highest_ranked_labels_in_proved_memberships():
    shadow = _shadow()
    guarded = shadow["portfolios"][GUARDED_PROFIT]["tickets"]
    unconstrained = shadow["portfolios"][UNCONSTRAINED_PROFIT][
        "tickets"
    ]

    guarded_counts = {
        number: sum(number in ticket["numbers"] for ticket in guarded)
        for number in range(1, 31)
    }
    unconstrained_counts = {
        number: sum(
            number in ticket["numbers"] for ticket in unconstrained
        )
        for number in range(1, 31)
    }
    assert all(guarded_counts[number] == 2 for number in range(1, 11))
    assert all(
        guarded_counts[number] == 1 for number in range(11, 21)
    )
    assert all(
        guarded_counts[number] == 0 for number in range(21, 31)
    )
    assert all(
        unconstrained_counts[number] == 3 for number in range(1, 11)
    )
    assert all(
        unconstrained_counts[number] == 0
        for number in range(11, 31)
    )


def test_verifier_rebuilds_contract_and_rejects_rehashed_tampering():
    shadow = _shadow()
    assert verify_profit_portfolio_shadows(
        shadow,
        expected_source_decision_hash="d" * 64,
        expected_support_evidence_hash="e" * 64,
        expected_ranked_main_numbers=list(range(1, 31)),
        expected_selected_special=7,
    ) == shadow

    tampered = deepcopy(shadow)
    tampered["portfolios"][GUARDED_PROFIT]["tickets"][0][
        "numbers"
    ][0] = 38
    tampered["portfolios"][GUARDED_PROFIT]["selection_hash"] = (
        canonical_hash(
            {
                "game": "super",
                "tickets": tampered["portfolios"][GUARDED_PROFIT][
                    "tickets"
                ],
            }
        )
    )
    tampered_payload = {
        key: value
        for key, value in tampered.items()
        if key != "shadow_hash"
    }
    tampered["shadow_hash"] = canonical_hash(tampered_payload)

    with pytest.raises(ValueError, match="獲利 forward shadow"):
        verify_profit_portfolio_shadows(
            tampered,
            expected_source_decision_hash="d" * 64,
            expected_support_evidence_hash="e" * 64,
            expected_ranked_main_numbers=list(range(1, 31)),
            expected_selected_special=7,
        )


def test_forward_proof_reference_matches_formal_v2_artifact():
    artifact = json.loads(
        (
            BASE
            / "research"
            / "results"
            / "unconstrained_profit_optimum.json"
        ).read_text(encoding="utf-8")
    )

    assert UNCONSTRAINED_PROOF == {
        "experiment_id": artifact["experiment_id"],
        "certificate_hash": artifact["certificate_hash"],
    }
    assert artifact["proof"]["global_nominal_optimum_proved"] is True
    assert artifact["proof"][
        "maximum_proper_special_nominal_upper_count"
    ] < artifact["games"]["super"][
        "nominal_strict_profit_global_maximum"
    ]["numerator"]


@pytest.mark.parametrize(
    ("ranking", "special"),
    [
        (list(range(1, 30)), 7),
        ([1] * 30, 7),
        (list(range(1, 31)), 0),
        (list(range(1, 31)), 9),
    ],
)
def test_invalid_ranking_or_special_fails_closed(ranking, special):
    with pytest.raises(ValueError):
        build_profit_portfolio_shadows(
            source_decision_hash="d" * 64,
            support_evidence_hash="e" * 64,
            ranked_main_numbers=ranking,
            selected_special=special,
        )
