"""下一期終局裁判前向 A/B：凍結、結算、雜湊與門檻。"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import random
from statistics import NormalDist

import pytest

from engine.agent_loop import (
    apply_final_judge,
    canonical_hash,
    conduct_debate,
    initial_state,
)
from engine.forward_feedback import (
    build_feedback_context_from_settlements,
)
from engine.forward_lab import (
    ARM_COVERAGE,
    ARM_QWEN,
    ARM_RANDOM,
    ARM_RULE,
    ARMS,
    COVERAGE_FORWARD_EXPERIMENT_ID_V5,
    COVERAGE_FORWARD_EXPERIMENT_ID_V6,
    COVERAGE_FORWARD_EXPERIMENT_ID_V7,
    FORWARD_EXPERIMENT_ID,
    MONITORING_CHECKPOINTS,
    MONITORING_FAMILY_LOWER_TAIL_ALPHA,
    MONITORING_LOOK_LOWER_TAIL_ALPHA,
    MONITORING_PROTOCOL_ID,
    _block_bootstrap_ci,
    _joint_probability_score_monitor,
    _joint_probability_stacking_monitor,
    _joint_qwen_monitor,
    _mechanism_candidate_from_artifact,
    _null_safe_probability_candidate_from_artifact,
    _probability_stacking_candidate_from_artifact,
    _probability_stacking_promotion_gate,
    _profit_common_special_candidate_from_artifact,
    _sequential_monitor,
    build_summary,
    feedback_for_target,
    forward_ledger,
    preregister_decision,
    reconcile_forward_registry,
    settle_forward_registry,
    settle_ready,
    verify_registry,
)
from engine.games import LOTTO649, SUPER, Draw
from engine.ledger import Ledger
from engine.qwen_judge import selection_diagnostics
from engine.store import DrawStore
from research.portfolio_coverage import select_coverage_portfolio
from research.profit_portfolio_forward import (
    COMMON_SPECIAL_SHADOW_EXPERIMENT_ID,
    GUARDED_PROFIT,
    UNCONSTRAINED_PROFIT,
)
from research.null_safe_probability import (
    SCORE_CAPSULE_EXPERIMENT_ID as NULL_SAFE_SCORE_CAPSULE_EXPERIMENT_ID,
    build_forward_state_artifact as build_null_safe_forward_state_artifact,
)


BASE = Path(__file__).parent.parent
DATA = BASE / "data"


def _mechanism_candidate() -> dict:
    result = json.loads(
        (
            BASE
            / "research"
            / "results"
            / "mechanism_signal.json"
        ).read_text(encoding="utf-8")
    )
    return result["future_forward_shadow_candidate"]


def _profit_common_special_candidate() -> dict:
    result = json.loads(
        (
            BASE
            / "research"
            / "results"
            / "mechanism_signal.json"
        ).read_text(encoding="utf-8")
    )
    return result[
        "future_profit_common_special_shadow_candidate"
    ]


def _probability_stacking_candidate() -> dict:
    result = json.loads(
        (
            BASE
            / "research"
            / "results"
            / "probability_stacking.json"
        ).read_text(encoding="utf-8")
    )
    return result["future_forward_shadow_candidate"]


def _null_safe_probability_candidate() -> dict:
    result = json.loads(
        (
            BASE
            / "research"
            / "results"
            / "null_safe_probability.json"
        ).read_text(encoding="utf-8")
    )
    return result["future_forward_shadow_candidate"]


def test_mechanism_candidate_artifact_loads_and_fails_closed(
    tmp_path,
):
    results = tmp_path / "research" / "results"
    results.mkdir(parents=True)
    candidate = _mechanism_candidate()
    (results / "mechanism_signal.json").write_text(
        json.dumps(
            {"future_forward_shadow_candidate": candidate}
        ),
        encoding="utf-8",
    )

    assert _mechanism_candidate_from_artifact(tmp_path) == candidate
    candidate["candidate_hash"] = "0" * 64
    (results / "mechanism_signal.json").write_text(
        json.dumps(
            {"future_forward_shadow_candidate": candidate}
        ),
        encoding="utf-8",
    )
    assert _mechanism_candidate_from_artifact(tmp_path) is None


def test_profit_common_special_candidate_artifact_loads_and_fails_closed(
    tmp_path,
):
    results = tmp_path / "research" / "results"
    results.mkdir(parents=True)
    candidate = _profit_common_special_candidate()
    (results / "mechanism_signal.json").write_text(
        json.dumps(
            {
                "future_profit_common_special_shadow_candidate": (
                    candidate
                )
            }
        ),
        encoding="utf-8",
    )

    assert _profit_common_special_candidate_from_artifact(
        tmp_path
    ) == candidate
    candidate["selected_special"] = 3
    payload = {
        key: value
        for key, value in candidate.items()
        if key != "candidate_hash"
    }
    candidate["candidate_hash"] = canonical_hash(payload)
    (results / "mechanism_signal.json").write_text(
        json.dumps(
            {
                "future_profit_common_special_shadow_candidate": (
                    candidate
                )
            }
        ),
        encoding="utf-8",
    )
    assert (
        _profit_common_special_candidate_from_artifact(tmp_path)
        is None
    )


def test_probability_stacking_candidate_artifact_loads_and_fails_closed(
    tmp_path,
):
    results = tmp_path / "research" / "results"
    results.mkdir(parents=True)
    candidate = _probability_stacking_candidate()
    path = results / "probability_stacking.json"
    path.write_text(
        json.dumps(
            {"future_forward_shadow_candidate": candidate}
        ),
        encoding="utf-8",
    )

    assert (
        _probability_stacking_candidate_from_artifact(tmp_path)
        == candidate
    )
    candidate["candidate_hash"] = "0" * 64
    path.write_text(
        json.dumps(
            {"future_forward_shadow_candidate": candidate}
        ),
        encoding="utf-8",
    )
    assert (
        _probability_stacking_candidate_from_artifact(tmp_path)
        is None
    )


def test_null_safe_candidate_artifact_loads_and_fails_closed(
    tmp_path,
):
    results = tmp_path / "research" / "results"
    results.mkdir(parents=True)
    candidate = _null_safe_probability_candidate()
    path = results / "null_safe_probability.json"
    path.write_text(
        json.dumps(
            {"future_forward_shadow_candidate": candidate}
        ),
        encoding="utf-8",
    )

    assert (
        _null_safe_probability_candidate_from_artifact(tmp_path)
        == candidate
    )
    candidate["candidate_hash"] = "0" * 64
    path.write_text(
        json.dumps(
            {"future_forward_shadow_candidate": candidate}
        ),
        encoding="utf-8",
    )
    assert (
        _null_safe_probability_candidate_from_artifact(tmp_path)
        is None
    )


def test_null_safe_operational_state_is_preferred_and_fails_closed(
    tmp_path,
):
    results = tmp_path / "research" / "results"
    results.mkdir(parents=True)
    candidate = _null_safe_probability_candidate()
    stacking = _probability_stacking_candidate()
    (results / "null_safe_probability.json").write_text(
        json.dumps(
            {"future_forward_shadow_candidate": candidate}
        ),
        encoding="utf-8",
    )
    artifact = build_null_safe_forward_state_artifact(
        candidate,
        stacking,
        [],
    )
    path = results / "null_safe_probability_forward.json"
    path.write_text(json.dumps(artifact), encoding="utf-8")

    assert (
        _null_safe_probability_candidate_from_artifact(tmp_path)
        == artifact["future_forward_shadow_candidate"]
    )

    artifact["state_hash"] = "0" * 64
    path.write_text(json.dumps(artifact), encoding="utf-8")
    assert (
        _null_safe_probability_candidate_from_artifact(tmp_path)
        is None
    )


def _qwen_payload(decision):
    feedback_context = build_feedback_context_from_settlements(
        [],
        decision["game"],
        before_target=decision["target"],
    )
    selected = [
        proposal["proposal_id"] for proposal in decision["proposals"][-5:]
    ]
    return {
        "source": "ollama",
        "requested_model": "qwen3:8b",
        "model": "qwen3:8b",
        "selected_proposal_ids": selected,
        "summary": "測試用終局裁決。",
        "reasons": [
            {"proposal_id": proposal_id, "reason": "測試理由"}
            for proposal_id in selected
        ],
        "prompt_hash": "prompt-sha",
        "response_hash": "response-sha",
        "feedback_provenance": {
            "experiment_id": "settled-forward-feedback-v1",
            "status": "verified_empty",
            "feedback_hash": feedback_context["feedback_hash"],
            "settlement_count": 0,
            "as_of_target": None,
            "source_postmortem_hashes": [],
        },
        "feedback_context": feedback_context,
        "telemetry": {
            "schema_version": "1",
            "outcome": "success",
            "wall_duration_ms": 1200,
            "ollama_total_duration_ms": 1100,
            "eval_count": 80,
            "eval_tokens_per_second": 20,
            "complete": True,
        },
        "selection_diagnostics": selection_diagnostics(
            decision,
            selected,
        ),
    }


def _decision(
    game: str,
    *,
    date: str | None = None,
    period: int = 188000001,
) -> dict:
    history = DrawStore(DATA).draws(game)[:80]
    target = {
        "date": date or (
            "2099-01-05" if game == SUPER else "2099-01-06"
        ),
        "period": period,
    }
    decision = conduct_debate(game, target, history, initial_state())
    return apply_final_judge(
        deepcopy(decision), lambda current: _qwen_payload(current)
    )


def _draw(game: str) -> Draw:
    return Draw(
        game=game,
        period=188000001,
        date="2099-01-05" if game == SUPER else "2099-01-06",
        numbers=(1, 2, 3, 4, 5, 6),
        special=8 if game == SUPER else 7,
    )


class FakeStore:
    def __init__(self, draws=None):
        self._draws = draws or {}

    def draws(self, game):
        return list(self._draws.get(game, []))


@pytest.mark.parametrize("game", [SUPER, LOTTO649])
def test_preregister_freezes_four_valid_arms_without_reveal(tmp_path, game):
    ledger = Ledger(tmp_path / "forward.jsonl")
    result = preregister_decision(
        ledger,
        _decision(game),
        registered_at="2099-01-01T12:00:00+08:00",
    )
    content = result["event"]["content"]

    assert result["status"] == "created"
    assert content["experiment_id"] == FORWARD_EXPERIMENT_ID
    assert content["late"] is False
    assert set(content["arms"]) == set(ARMS)
    assert all(len(content["arms"][arm]["tickets"]) == 5 for arm in ARMS)
    assert all(content["arms"][arm]["eligible"] for arm in ARMS)
    assert content["arms"][ARM_QWEN]["metadata"]["model"] == "qwen3:8b"
    assert content["arms"][ARM_QWEN]["metadata"][
        "feedback_provenance"
    ]["status"] == "verified_empty"
    assert content["arms"][ARM_QWEN]["metadata"][
        "feedback_context"
    ]["feedback_hash"] == content["arms"][ARM_QWEN][
        "metadata"
    ]["feedback_provenance"]["feedback_hash"]
    assert (
        content["arms"][ARM_QWEN]["metadata"]["telemetry"]["outcome"]
        == "success"
    )
    assert (
        content["arms"][ARM_QWEN]["metadata"]["selection_diagnostics"][
            "selected_count"
        ]
        == 5
    )
    assert content["arms"][ARM_RANDOM]["source"] == "uniform_null"
    coverage = content["arms"][ARM_COVERAGE]
    coverage_metadata = coverage["metadata"]
    assert (
        coverage["source"]
        == "deterministic_consensus_disjoint_selector"
    )
    assert coverage_metadata["experiment_id"] == (
        "profit-portfolio-consensus-forward-v3"
    )
    assert len(coverage_metadata["support_evidence_hash"]) == 64
    assert coverage_metadata["structural_optimum_proof"][
        "experiment_id"
    ] == "five-ticket-structural-optimum-proof-v1"
    assert len(
        coverage_metadata["structural_optimum_proof"][
            "certificate_hash"
        ]
    ) == 64
    assert len(coverage_metadata["selected_main_numbers"]) == 30
    assert (
        len(set(coverage_metadata["selected_main_numbers"])) == 30
    )
    assert coverage_metadata["exact_probability_delta"] >= -1e-15
    assert (
        coverage_metadata["exact_any_prize_probability_delta"]
        >= -1e-15
    )
    assert len(coverage_metadata["candidate_pool_hash"]) == 64
    assert (
        coverage_metadata["selected_structure"][
            "exact_at_least_three_main"
        ]
        >= coverage_metadata["baseline_structure"][
            "exact_at_least_three_main"
        ]
    )
    assert (
        coverage_metadata["selected_structure"]["exact_any_prize"]
        >= coverage_metadata["baseline_structure"]["exact_any_prize"]
    )
    assert (
        coverage_metadata["selected_structure"]["main_union_size"]
        == 30
    )
    assert (
        coverage_metadata["selected_structure"][
            "maximum_pairwise_main_overlap"
        ]
        == 0
    )
    if game == SUPER:
        assert len(coverage_metadata["selected_specials"]) == 5
        assert len(set(coverage_metadata["selected_specials"])) == 5
        profit_shadows = coverage_metadata[
            "profit_portfolio_shadows"
        ]
        assert profit_shadows["source_decision_hash"] == (
            content["source_decision_hash"]
        )
        assert profit_shadows["support_evidence_hash"] == (
            coverage_metadata["support_evidence_hash"]
        )
        assert set(profit_shadows["portfolios"]) == {
            GUARDED_PROFIT,
            UNCONSTRAINED_PROFIT,
        }
        assert (
            profit_shadows["portfolios"][GUARDED_PROFIT][
                "structure"
            ]["main_union_size"]
            == 20
        )
        assert (
            profit_shadows["portfolios"][UNCONSTRAINED_PROFIT][
                "structure"
            ]["main_union_size"]
            == 10
        )
        assert (
            coverage_metadata[
                "profit_portfolio_shadows_error_type"
            ]
            is None
        )
    else:
        assert coverage_metadata["selected_specials"] is None
        assert (
            coverage_metadata["profit_portfolio_shadows"] is None
        )
        assert (
            coverage_metadata[
                "profit_portfolio_shadows_error_type"
            ]
            is None
        )
    assert "actual" not in json.dumps(content)
    assert verify_registry(ledger)["registrations"] == 1


def test_existing_three_arm_goal_registrations_remain_verifiable():
    ledger = forward_ledger(BASE)

    summary = verify_registry(ledger)
    first_two = ledger.events_of("forward_preregister")[:2]

    assert summary["chain_valid"] is True
    assert len(first_two) == 2
    assert all(
        set(event["content"]["arms"])
        == {ARM_RULE, ARM_QWEN, ARM_RANDOM}
        for event in first_two
    )


def test_registry_keeps_v1_proposal_coverage_compatible(tmp_path):
    decision = _decision(SUPER)
    seed_ledger = Ledger(tmp_path / "v2-seed.jsonl")
    content = deepcopy(
        preregister_decision(
            seed_ledger,
            decision,
            registered_at="2099-01-01T12:00:00+08:00",
        )["event"]["content"]
    )
    v1_decision = deepcopy(decision)
    v1_decision["selected_tickets"] = content["arms"][ARM_RULE][
        "tickets"
    ]
    tickets, selection = select_coverage_portfolio(
        SUPER, v1_decision
    )
    coverage = content["arms"][ARM_COVERAGE]
    coverage["source"] = "deterministic_coverage_selector"
    coverage["tickets"] = tickets
    coverage["selection_hash"] = canonical_hash(
        {"game": SUPER, "tickets": tickets}
    )
    coverage["eligible"] = True
    coverage["ineligible_reason"] = None
    coverage["metadata"] = {
        "experiment_id": "portfolio-coverage-forward-v1",
        "source_research_experiment_id": (
            "portfolio-coverage-shadow-v1"
        ),
        "source_decision_hash": content["source_decision_hash"],
        "candidate_pool_hash": canonical_hash(
            {
                "game": SUPER,
                "target": content["target"],
                "proposals": decision["proposals"],
            }
        ),
        "selected_proposal_ids": selection[
            "selected_proposal_ids"
        ],
        "combinations_evaluated": 3_003,
        "fallback_to_current": selection["fallback_to_current"],
        "baseline_structure": selection["baseline"],
        "candidate_structure": selection["candidate"],
        "selected_structure": selection["selected"],
        "exact_probability_delta": selection[
            "exact_probability_delta"
        ],
        "exact_any_prize_probability_delta": selection[
            "exact_any_prize_probability_delta"
        ],
        "error_type": None,
    }
    content["coverage_experiment_id"] = (
        "portfolio-coverage-forward-v1"
    )

    v1_ledger = Ledger(tmp_path / "v1-compatible.jsonl")
    v1_ledger.append(
        "forward_preregister",
        {
            "content": content,
            "content_hash": canonical_hash(content),
        },
    )

    assert verify_registry(v1_ledger)["registrations"] == 1


def test_registry_keeps_v2_consensus_coverage_compatible(tmp_path):
    seed_ledger = Ledger(tmp_path / "v3-seed.jsonl")
    content = deepcopy(
        preregister_decision(
            seed_ledger,
            _decision(SUPER),
            registered_at="2099-01-01T12:00:00+08:00",
        )["event"]["content"]
    )
    content["coverage_experiment_id"] = (
        "max-coverage-consensus-forward-v2"
    )
    metadata = content["arms"][ARM_COVERAGE]["metadata"]
    metadata["experiment_id"] = "max-coverage-consensus-forward-v2"
    metadata.pop("profit_portfolio_shadows")
    metadata.pop("profit_portfolio_shadows_error_type")

    ledger = Ledger(tmp_path / "v2-compatible.jsonl")
    ledger.append(
        "forward_preregister",
        {
            "content": content,
            "content_hash": canonical_hash(content),
        },
    )

    assert verify_registry(ledger)["registrations"] == 1


def test_preregister_is_idempotent_and_never_overwrites_first_qwen_choice(
    tmp_path,
):
    ledger = Ledger(tmp_path / "forward.jsonl")
    decision = _decision(SUPER)
    first = preregister_decision(
        ledger,
        decision,
        registered_at="2099-01-01T12:00:00+08:00",
    )
    changed = deepcopy(decision)
    changed["selected_tickets"] = list(reversed(changed["selected_tickets"]))
    second = preregister_decision(
        ledger,
        changed,
        registered_at="2099-01-02T12:00:00+08:00",
    )

    assert first["registration_hash"] == second["registration_hash"]
    assert second["status"] == "existing"
    assert len(ledger.read_all()) == 1


def test_late_registration_and_qwen_fallback_are_ineligible(tmp_path):
    late_ledger = Ledger(tmp_path / "late.jsonl")
    late = preregister_decision(
        late_ledger,
        _decision(SUPER),
        registered_at="2099-01-05T20:30:00+08:00",
    )["event"]["content"]
    assert late["late"] is True
    assert all(not late["arms"][arm]["eligible"] for arm in ARMS)

    fallback_ledger = Ledger(tmp_path / "fallback.jsonl")
    baseline = _decision(SUPER)
    fallback = apply_final_judge(
        conduct_debate(
            SUPER,
            baseline["target"],
            DrawStore(DATA).draws(SUPER)[:80],
            initial_state(),
        ),
        lambda _: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    content = preregister_decision(
        fallback_ledger,
        fallback,
        registered_at="2099-01-01T12:00:00+08:00",
    )["event"]["content"]
    assert content["arms"][ARM_RULE]["eligible"] is True
    assert content["arms"][ARM_RANDOM]["eligible"] is True
    assert content["arms"][ARM_QWEN]["eligible"] is False
    assert (
        content["arms"][ARM_QWEN]["ineligible_reason"]
        == "qwen_not_verified"
    )


def test_coverage_selector_failure_is_explicit_and_keeps_controls(
    tmp_path,
    monkeypatch,
):
    def fail_coverage(*_args, **_kwargs):
        raise ValueError("forced coverage failure")

    monkeypatch.setattr(
        "engine.forward_lab.select_consensus_disjoint_portfolio",
        fail_coverage,
    )
    ledger = Ledger(tmp_path / "coverage-failure.jsonl")
    content = preregister_decision(
        ledger,
        _decision(SUPER),
        registered_at="2099-01-01T12:00:00+08:00",
    )["event"]["content"]

    coverage = content["arms"][ARM_COVERAGE]
    assert coverage["eligible"] is False
    assert coverage["ineligible_reason"] == "coverage_not_verified"
    assert coverage["metadata"]["error_type"] == "ValueError"
    assert coverage["tickets"] == content["arms"][ARM_RULE]["tickets"]
    assert content["arms"][ARM_RULE]["eligible"] is True
    assert content["arms"][ARM_QWEN]["eligible"] is True
    assert content["arms"][ARM_RANDOM]["eligible"] is True
    assert verify_registry(ledger)["registrations"] == 1


def test_qwen_without_verified_settled_feedback_is_ineligible(tmp_path):
    decision = _decision(SUPER)
    decision["adjudication"]["judge"].pop(
        "feedback_provenance",
        None,
    )
    decision["adjudication"]["judge"].pop(
        "feedback_context",
        None,
    )

    content = preregister_decision(
        Ledger(tmp_path / "missing-feedback.jsonl"),
        decision,
        registered_at="2099-01-01T12:00:00+08:00",
    )["event"]["content"]

    assert content["arms"][ARM_RULE]["eligible"] is True
    assert content["arms"][ARM_RANDOM]["eligible"] is True
    assert content["arms"][ARM_QWEN]["eligible"] is False
    assert (
        content["arms"][ARM_QWEN]["ineligible_reason"]
        == "qwen_not_verified"
    )


def test_settlement_requires_existing_preregistration_and_is_idempotent(
    tmp_path,
):
    ledger = Ledger(tmp_path / "forward.jsonl")
    preregistration = preregister_decision(
        ledger,
        _decision(SUPER),
        registered_at="2099-01-01T12:00:00+08:00",
    )

    assert settle_ready(ledger, FakeStore()) == []
    created = settle_ready(
        ledger, FakeStore({SUPER: [_draw(SUPER)]})
    )
    assert len(created) == 1
    settlement = created[0]["content"]
    assert (
        settlement["registration_hash"]
        == preregistration["registration_hash"]
    )
    assert settlement["actual"]["numbers"] == [1, 2, 3, 4, 5, 6]
    assert settlement["postmortem"]["registration_hash"] == (
        preregistration["registration_hash"]
    )
    assert settlement["postmortem"]["postmortem_hash"]
    assert settlement["postmortem"]["profit_portfolio_review"][
        "objective"
    ] == "empirical_floor_stress_strict_profit"
    assert set(settlement["arm_results"]) == set(ARMS)
    assert settlement["qwen_vs_rule"]["verdict"] in {
        "qwen_win",
        "rule_win",
        "tie",
    }
    assert settlement["coverage_vs_rule"]["verdict"] in {
        "coverage_win",
        "rule_win",
        "tie",
    }
    profit_shadows = settlement["profit_portfolio_shadows"]
    assert set(profit_shadows["portfolios"]) == {
        GUARDED_PROFIT,
        UNCONSTRAINED_PROFIT,
    }
    assert (
        profit_shadows["coverage_result"]["five_ticket_cost_ntd"]
        == 500
    )
    assert all(
        row["result"]["five_ticket_cost_ntd"] == 500
        for row in profit_shadows["portfolios"].values()
    )
    feedback = build_feedback_context_from_settlements(
        [settlement],
        SUPER,
        before_target={"date": "2099-01-06", "period": 188000002},
    )
    assert feedback["profit_portfolio_aggregate"][
        "settlement_count"
    ] == 1
    assert set(
        feedback["profit_portfolio_aggregate"]["portfolios"]
    ) == {GUARDED_PROFIT, UNCONSTRAINED_PROFIT}
    assert settle_ready(
        ledger, FakeStore({SUPER: [_draw(SUPER)]})
    ) == []
    assert verify_registry(ledger)["settlements"] == 1


@pytest.mark.parametrize("game", [SUPER, LOTTO649])
def test_probability_stacking_shadow_is_preregistered_as_v6(
    tmp_path,
    game,
):
    ledger = Ledger(tmp_path / f"{game}-stacking.jsonl")
    registration = preregister_decision(
        ledger,
        _decision(game),
        registered_at="2099-01-01T12:00:00+08:00",
        probability_stacking_candidate=(
            _probability_stacking_candidate()
        ),
    )
    content = registration["event"]["content"]
    coverage = content["arms"][ARM_COVERAGE]
    shadow = coverage["metadata"][
        "probability_stacking_shadow"
    ]

    assert (
        content["coverage_experiment_id"]
        == COVERAGE_FORWARD_EXPERIMENT_ID_V6
    )
    assert shadow["candidate_hash"] == (
        _probability_stacking_candidate()["candidate_hash"]
    )
    assert shadow["source_decision_hash"] == (
        content["source_decision_hash"]
    )
    assert len(shadow["tickets"]) == 5
    assert shadow["structure"]["main_union_size"] == 30
    assert (
        shadow["structure"]["maximum_pairwise_main_overlap"]
        == 0
    )
    assert shadow["score_capsule"]["target"] == content["target"]
    assert len(shadow["score_capsule"]["main_probability_mass"]) in {
        38,
        49,
    }
    assert (
        coverage["metadata"][
            "probability_stacking_shadow_error_type"
        ]
        is None
    )
    assert verify_registry(ledger)["registrations"] == 1


@pytest.mark.parametrize("game", [SUPER, LOTTO649])
def test_null_safe_shadow_is_preregistered_as_v7_without_replacing_coverage(
    tmp_path,
    game,
):
    ledger = Ledger(tmp_path / f"{game}-null-safe.jsonl")
    registration = preregister_decision(
        ledger,
        _decision(game),
        registered_at="2099-01-01T12:00:00+08:00",
        probability_stacking_candidate=(
            _probability_stacking_candidate()
        ),
        null_safe_probability_candidate=(
            _null_safe_probability_candidate()
        ),
    )
    content = registration["event"]["content"]
    coverage = content["arms"][ARM_COVERAGE]
    shadow = coverage["metadata"][
        "null_safe_probability_shadow"
    ]
    capsule = shadow["score_capsule"]

    assert (
        content["coverage_experiment_id"]
        == COVERAGE_FORWARD_EXPERIMENT_ID_V7
    )
    assert shadow["experiment_id"] == (
        "null-safe-probability-forward-shadow-v1"
    )
    assert shadow["candidate_hash"] == (
        _null_safe_probability_candidate()["candidate_hash"]
    )
    assert shadow["main_gate_active"] is False
    assert shadow["special_gate_active"] is (
        False if game == SUPER else None
    )
    assert shadow["ticket_label_source"] == "consensus_coverage"
    assert [
        ticket["numbers"] for ticket in shadow["tickets"]
    ] == [
        ticket["numbers"] for ticket in coverage["tickets"]
    ]
    assert [
        ticket["special"] for ticket in shadow["tickets"]
    ] == [
        ticket["special"] for ticket in coverage["tickets"]
    ]
    assert capsule["experiment_id"] == (
        NULL_SAFE_SCORE_CAPSULE_EXPERIMENT_ID
    )
    assert capsule["target"] == content["target"]
    assert capsule["main_gate_active"] is False
    assert capsule["safe_main_probability_mass"] == [
        1 / len(capsule["safe_main_probability_mass"])
    ] * len(capsule["safe_main_probability_mass"])
    assert (
        capsule["safe_main_probability_mass"]
        != capsule["evidence_main_probability_mass"]
    )
    assert coverage["metadata"][
        "null_safe_probability_shadow_error_type"
    ] is None
    assert verify_registry(ledger)["registrations"] == 1


def test_invalid_null_safe_candidate_fails_closed_and_keeps_v6(
    tmp_path,
):
    candidate = _null_safe_probability_candidate()
    candidate["candidate_hash"] = "0" * 64
    ledger = Ledger(tmp_path / "invalid-null-safe.jsonl")
    registration = preregister_decision(
        ledger,
        _decision(SUPER),
        registered_at="2099-01-01T12:00:00+08:00",
        probability_stacking_candidate=(
            _probability_stacking_candidate()
        ),
        null_safe_probability_candidate=candidate,
    )
    content = registration["event"]["content"]
    metadata = content["arms"][ARM_COVERAGE]["metadata"]

    assert (
        content["coverage_experiment_id"]
        == COVERAGE_FORWARD_EXPERIMENT_ID_V6
    )
    assert metadata["null_safe_probability_shadow"] is None
    assert (
        metadata["null_safe_probability_shadow_error_type"]
        == "ValueError"
    )
    assert metadata["probability_stacking_shadow"] is not None
    assert verify_registry(ledger)["registrations"] == 1


def test_invalid_probability_stacking_candidate_is_omitted_fail_closed(
    tmp_path,
):
    candidate = _probability_stacking_candidate()
    candidate["candidate_hash"] = "0" * 64
    ledger = Ledger(tmp_path / "invalid-stacking.jsonl")
    registration = preregister_decision(
        ledger,
        _decision(SUPER),
        registered_at="2099-01-01T12:00:00+08:00",
        probability_stacking_candidate=candidate,
    )
    metadata = registration["event"]["content"]["arms"][
        ARM_COVERAGE
    ]["metadata"]

    assert metadata["probability_stacking_shadow"] is None
    assert (
        metadata["probability_stacking_shadow_error_type"]
        == "ValueError"
    )
    assert verify_registry(ledger)["registrations"] == 1


def test_probability_stacking_shadow_settles_and_stays_future_only(
    tmp_path,
):
    ledger = Ledger(tmp_path / "stacking-settlement.jsonl")
    for game in (SUPER, LOTTO649):
        preregister_decision(
            ledger,
            _decision(game),
            registered_at="2099-01-01T12:00:00+08:00",
            probability_stacking_candidate=(
                _probability_stacking_candidate()
            ),
        )

    settlements = settle_ready(
        ledger,
        FakeStore(
            {
                SUPER: [_draw(SUPER)],
                LOTTO649: [_draw(LOTTO649)],
            }
        ),
    )

    assert len(settlements) == 2
    for event in settlements:
        shadow = event["content"]["probability_stacking_shadow"]
        assert shadow["eligible"] is True
        assert shadow["verdict"] in {
            "stacking_win",
            "coverage_win",
            "tie",
        }
        assert isinstance(
            shadow[
                "stacking_minus_coverage_union_main_hits"
            ],
            int,
        )
        proper_score = shadow["proper_score"]
        assert proper_score["eligible"] is True
        assert math.isfinite(proper_score["main_log_loss"])
        assert math.isfinite(
            proper_score["main_regret_vs_uniform"]
        )
        assert event["content"]["postmortem"][
            "probability_score_review"
        ] == proper_score
        feedback = build_feedback_context_from_settlements(
            [event["content"]],
            event["content"]["game"],
            before_target={
                "date": "2100-01-01",
                "period": 999999999,
            },
        )
        assert feedback["probability_score_aggregate"][
            "settlement_count"
        ] == 1
        assert "actual" not in str(
            feedback["probability_score_aggregate"]
        )
    summary = build_summary(ledger)
    monitor = summary[
        "probability_stacking_joint_sequential_monitor"
    ]
    assert monitor["common_observed_pairs"] == 1
    assert monitor["evaluated_pairs_per_game"] == 0
    assert monitor["next_checkpoint"] == 52
    score_monitor = summary[
        "probability_score_joint_sequential_monitor"
    ]
    assert score_monitor["common_observed_scores"] == 1
    assert score_monitor["evaluated_scores_per_game"] == 0
    assert score_monitor["next_checkpoint"] == 52
    assert summary["probability_stacking_promotion_gate"][
        "reason"
    ] == "waiting_for_outcome_and_probability_calibration"
    for game in (SUPER, LOTTO649):
        score_summary = summary["games"][game][
            "probability_stacking_shadow_vs_coverage"
        ]["probability_score_vs_uniform"]
        assert score_summary["registered_capsules"] == 1
        assert score_summary["eligible_scores"] == 1
        assert math.isclose(
            score_summary[
                "mean_main_information_gain_vs_uniform"
            ],
            -score_summary["mean_main_regret_vs_uniform"],
            rel_tol=0.0,
            abs_tol=1e-15,
        )
    assert verify_registry(ledger)["settlements"] == 2


def test_null_safe_shadow_settles_exact_subset_score_and_updates_next_gate_only(
    tmp_path,
):
    ledger = Ledger(tmp_path / "null-safe-settlement.jsonl")
    for game in (SUPER, LOTTO649):
        preregister_decision(
            ledger,
            _decision(game),
            registered_at="2099-01-01T12:00:00+08:00",
            probability_stacking_candidate=(
                _probability_stacking_candidate()
            ),
            null_safe_probability_candidate=(
                _null_safe_probability_candidate()
            ),
        )

    settlements = settle_ready(
        ledger,
        FakeStore(
            {
                SUPER: [_draw(SUPER)],
                LOTTO649: [_draw(LOTTO649)],
            }
        ),
    )

    assert len(settlements) == 2
    for event in settlements:
        shadow = event["content"][
            "null_safe_probability_shadow"
        ]
        score = shadow["proper_score"]
        assert shadow["eligible"] is True
        assert shadow["verdict"] == "tie"
        assert (
            shadow["null_safe_minus_coverage_union_main_hits"]
            == 0
        )
        assert score["main_gate_active_for_scored_target"] is False
        assert score["main_safe_verdict"] == "tie_uniform"
        assert score["main_safe_regret_vs_uniform"] == pytest.approx(
            0.0,
            abs=1e-12,
        )
        assert score["main_updated_e_process"]["sequence"] == (
            score["main_prior_e_process"]["sequence"] + 1
        )
        assert "actual" not in json.dumps(score)
        if event["content"]["game"] == SUPER:
            assert (
                score["special_gate_active_for_scored_target"]
                is False
            )
            assert score["special_safe_verdict"] == "tie_uniform"
            assert score["special_updated_e_process"][
                "sequence"
            ] == (
                score["special_prior_e_process"]["sequence"] + 1
            )
        else:
            assert score["special_safe_verdict"] == "not_applicable"
    summary = build_summary(ledger)
    for game in (SUPER, LOTTO649):
        row = summary["games"][game][
            "null_safe_probability_shadow"
        ]
        assert row["registered_shadows"] == 1
        assert row["eligible_scores"] == 1
        assert row["historical_backfill_allowed"] is False
        assert row["main_gate_activations_at_registration"] == 0
        assert row["mean_main_safe_regret_vs_uniform"] == (
            pytest.approx(0.0, abs=1e-12)
        )
        assert row["latest_main_updated_e_process"][
            "sequence"
        ] == (
            _null_safe_probability_candidate()["models"][game][
                "main_e_process"
            ]["sequence"]
            + 1
        )
    assert verify_registry(ledger)["settlements"] == 2


def test_probability_stacking_joint_monitor_requires_guardrails():
    positive = {
        game: {
            "union_main_hits": [1.0] * 52,
            "best_main_hits": [0.0] * 52,
            "any_three_plus": [0.0] * 52,
            "any_prize": [0.0] * 52,
        }
        for game in (SUPER, LOTTO649)
    }
    supported = _joint_probability_stacking_monitor(positive)

    assert supported["supported"] is True
    assert supported["evaluated_pairs_per_game"] == 52
    assert supported["look_lower_tail_alpha"] == 0.005

    negative_guardrail = deepcopy(positive)
    negative_guardrail[SUPER]["any_prize"] = [-1.0] * 52
    rejected = _joint_probability_stacking_monitor(
        negative_guardrail
    )
    assert rejected["supported"] is False
    assert rejected["games"][SUPER]["guardrails_passed"] is False


def test_probability_score_joint_monitor_requires_both_games_and_special_guardrail():
    positive = {
        SUPER: {
            "main_information_gain": [0.02] * 52,
            "special_information_gain": [0.01] * 52,
        },
        LOTTO649: {
            "main_information_gain": [0.03] * 52,
        },
    }
    supported = _joint_probability_score_monitor(positive)

    assert supported["supported"] is True
    assert supported["evaluated_scores_per_game"] == 52
    assert supported["look_lower_tail_alpha"] == 0.005
    assert supported["historical_backfill_allowed"] is False

    negative_main = deepcopy(positive)
    negative_main[LOTTO649]["main_information_gain"] = [-0.01] * 52
    rejected_main = _joint_probability_score_monitor(negative_main)
    assert rejected_main["supported"] is False
    assert rejected_main["games"][LOTTO649]["main_supported"] is False

    negative_special = deepcopy(positive)
    negative_special[SUPER]["special_information_gain"] = [-0.01] * 52
    rejected_special = _joint_probability_score_monitor(
        negative_special
    )
    assert rejected_special["supported"] is False
    assert rejected_special["games"][SUPER][
        "special_guardrail_passed"
    ] is False

    uniform_null = deepcopy(positive)
    uniform_null[SUPER]["main_information_gain"] = [0.0] * 52
    uniform_null[LOTTO649]["main_information_gain"] = [0.0] * 52
    rejected_null = _joint_probability_score_monitor(uniform_null)
    assert rejected_null["supported"] is False
    assert all(
        row["main_supported"] is False
        for row in rejected_null["games"].values()
    )

    unequal_prefixes = deepcopy(positive)
    unequal_prefixes[SUPER]["main_information_gain"] = [0.02] * 104
    unequal_prefixes[SUPER]["special_information_gain"] = [0.01] * 104
    common_only = _joint_probability_score_monitor(
        unequal_prefixes
    )
    assert common_only["observed_scores_by_game"] == {
        SUPER: 104,
        LOTTO649: 52,
    }
    assert common_only["common_observed_scores"] == 52
    assert common_only["evaluated_scores_per_game"] == 52


def test_probability_stacking_promotion_requires_outcome_and_calibration():
    outcome = _joint_probability_stacking_monitor(
        {
            game: {
                "union_main_hits": [1.0] * 52,
                "best_main_hits": [0.0] * 52,
                "any_three_plus": [0.0] * 52,
                "any_prize": [0.0] * 52,
            }
            for game in (SUPER, LOTTO649)
        }
    )
    collecting_score = _joint_probability_score_monitor(
        {
            SUPER: {
                "main_information_gain": [],
                "special_information_gain": [],
            },
            LOTTO649: {"main_information_gain": []},
        }
    )
    gate = _probability_stacking_promotion_gate(
        outcome,
        collecting_score,
    )

    assert outcome["supported"] is True
    assert gate["supported"] is False
    assert gate["reason"] == "waiting_for_probability_calibration"

    supported_score = _joint_probability_score_monitor(
        {
            SUPER: {
                "main_information_gain": [0.02] * 52,
                "special_information_gain": [0.01] * 52,
            },
            LOTTO649: {
                "main_information_gain": [0.03] * 52,
            },
        }
    )
    promoted = _probability_stacking_promotion_gate(
        outcome,
        supported_score,
    )
    assert promoted["supported"] is True
    assert promoted["status"] == "supported"


def test_v5_stacking_settlements_do_not_backfill_v6_score_monitor(
    tmp_path,
):
    path = tmp_path / "legacy-v5.jsonl"
    ledger = Ledger(path)
    for game in (SUPER, LOTTO649):
        preregister_decision(
            ledger,
            _decision(game),
            registered_at="2099-01-01T12:00:00+08:00",
            probability_stacking_candidate=(
                _probability_stacking_candidate()
            ),
        )
    events = ledger.read_all()
    previous_line = None
    rebuilt_lines = []
    for event in events:
        content = event["content"]
        content["coverage_experiment_id"] = (
            COVERAGE_FORWARD_EXPERIMENT_ID_V5
        )
        metadata = content["arms"][ARM_COVERAGE]["metadata"]
        metadata["experiment_id"] = (
            COVERAGE_FORWARD_EXPERIMENT_ID_V5
        )
        shadow = metadata["probability_stacking_shadow"]
        shadow.pop("score_capsule")
        evidence = {
            "candidate_hash": shadow["candidate_hash"],
            "protocol_hash": shadow["protocol_hash"],
            "game": content["game"],
            "target": content["target"],
            "source_decision_hash": shadow[
                "source_decision_hash"
            ],
            "selected_main_numbers": shadow[
                "selected_main_numbers"
            ],
            "selected_specials": shadow["selected_specials"],
            "ticket_main_probability_mass": shadow[
                "ticket_main_probability_mass"
            ],
            "structure": shadow["structure"],
        }
        shadow["support_evidence_hash"] = canonical_hash(evidence)
        event["content_hash"] = canonical_hash(content)
        event["prev_line_hash"] = (
            hashlib.sha256(previous_line.encode("utf-8")).hexdigest()
            if previous_line is not None
            else None
        )
        previous_line = json.dumps(event, ensure_ascii=False)
        rebuilt_lines.append(previous_line)
    path.write_text(
        "\n".join(rebuilt_lines) + "\n",
        encoding="utf-8",
    )

    assert verify_registry(ledger)["registrations"] == 2
    settlements = settle_ready(
        ledger,
        FakeStore(
            {
                SUPER: [_draw(SUPER)],
                LOTTO649: [_draw(LOTTO649)],
            }
        ),
    )
    assert all(
        "proper_score"
        not in event["content"]["probability_stacking_shadow"]
        for event in settlements
    )
    summary = build_summary(ledger)
    assert summary[
        "probability_stacking_joint_sequential_monitor"
    ]["common_observed_pairs"] == 1
    assert summary[
        "probability_score_joint_sequential_monitor"
    ]["common_observed_scores"] == 0
    for game in (SUPER, LOTTO649):
        score_summary = summary["games"][game][
            "probability_stacking_shadow_vs_coverage"
        ]["probability_score_vs_uniform"]
        assert score_summary["registered_capsules"] == 0
        assert score_summary["eligible_scores"] == 0


def test_super_special_frequency_shadow_is_frozen_without_changing_arm(
    tmp_path,
):
    ledger = Ledger(tmp_path / "forward.jsonl")
    registration = preregister_decision(
        ledger,
        _decision(SUPER),
        registered_at="2099-01-01T12:00:00+08:00",
        mechanism_candidate=_mechanism_candidate(),
    )
    content = registration["event"]["content"]
    coverage = content["arms"][ARM_COVERAGE]
    shadow = coverage["metadata"]["special_frequency_shadow"]

    assert set(content["arms"]) == set(ARMS)
    assert shadow["candidate_hash"] == _mechanism_candidate()[
        "candidate_hash"
    ]
    assert [
        ticket["numbers"] for ticket in shadow["tickets"]
    ] == [ticket["numbers"] for ticket in coverage["tickets"]]
    assert sorted(
        ticket["special"] for ticket in shadow["tickets"]
    ) == [1, 2, 3, 4, 5]
    assert shadow[
        "theoretical_structural_probability_unchanged"
    ] is True
    assert verify_registry(ledger)["registrations"] == 1


def test_super_special_frequency_shadow_settles_from_preregistration(
    tmp_path,
):
    ledger = Ledger(tmp_path / "forward.jsonl")
    preregister_decision(
        ledger,
        _decision(SUPER),
        registered_at="2099-01-01T12:00:00+08:00",
        mechanism_candidate=_mechanism_candidate(),
    )

    settlement = settle_ready(
        ledger, FakeStore({SUPER: [_draw(SUPER)]})
    )[0]["content"]
    shadow = settlement["special_frequency_shadow"]

    assert shadow["candidate_hash"] == _mechanism_candidate()[
        "candidate_hash"
    ]
    assert shadow["verdict"] in {
        "shadow_win",
        "coverage_win",
        "tie",
    }
    assert isinstance(
        shadow["shadow_minus_coverage_any_prize"], int
    )
    assert verify_registry(ledger)["settlements"] == 1


def test_super_profit_common_special_shadow_is_preregistered_as_v4(
    tmp_path,
):
    ledger = Ledger(tmp_path / "forward.jsonl")
    registration = preregister_decision(
        ledger,
        _decision(SUPER),
        registered_at="2099-01-01T12:00:00+08:00",
        profit_common_special_candidate=(
            _profit_common_special_candidate()
        ),
    )
    content = registration["event"]["content"]
    coverage = content["arms"][ARM_COVERAGE]
    profit = coverage["metadata"]["profit_portfolio_shadows"]
    common = profit["common_special_shadow"]

    assert content["coverage_experiment_id"] == (
        "profit-common-special-shadow-forward-v4"
    )
    assert common["experiment_id"] == (
        COMMON_SPECIAL_SHADOW_EXPERIMENT_ID
    )
    assert common["candidate_hash"] == (
        _profit_common_special_candidate()["candidate_hash"]
    )
    assert common["selected_special"] == 2
    for portfolio_id in (GUARDED_PROFIT, UNCONSTRAINED_PROFIT):
        assert [
            ticket["numbers"]
            for ticket in common["portfolios"][portfolio_id][
                "tickets"
            ]
        ] == [
            ticket["numbers"]
            for ticket in profit["portfolios"][portfolio_id][
                "tickets"
            ]
        ]
    settlement_content = settle_ready(
        ledger, FakeStore({SUPER: [_draw(SUPER)]})
    )[0]["content"]
    settlement = settlement_content["profit_portfolio_shadows"]
    common_settlement = settlement["common_special_shadow"]
    assert common_settlement["candidate_hash"] == (
        _profit_common_special_candidate()["candidate_hash"]
    )
    assert set(common_settlement["portfolios"]) == {
        GUARDED_PROFIT,
        UNCONSTRAINED_PROFIT,
    }
    assert all(
        row["verdict"]
        in {"common_special_win", "baseline_special_win", "tie"}
        for row in common_settlement["portfolios"].values()
    )
    feedback_review = settlement_content["postmortem"][
        "profit_portfolio_review"
    ]["common_special_shadow"]
    assert "selected_special" not in str(feedback_review)
    assert "ticket_results" not in str(feedback_review)
    summary = build_summary(ledger)["games"][SUPER][
        "profit_common_special_shadow_vs_baseline"
    ]
    assert summary["status"] == "collecting_forward_data"
    assert summary["registered_shadows"] == 1
    assert summary["selected_special"] == 2
    assert all(
        row["eligible_pairs"] == 1
        and row["sequential_monitor"]["next_checkpoint"] == 52
        for row in summary["portfolios"].values()
    )
    assert verify_registry(ledger)["settlements"] == 1


def test_registry_rejects_rehashed_v4_common_shadow_removal(
    tmp_path,
):
    path = tmp_path / "forward.jsonl"
    ledger = Ledger(path)
    preregister_decision(
        ledger,
        _decision(SUPER),
        registered_at="2099-01-01T12:00:00+08:00",
        profit_common_special_candidate=(
            _profit_common_special_candidate()
        ),
    )
    event = json.loads(path.read_text(encoding="utf-8"))
    shadow = event["content"]["arms"][ARM_COVERAGE]["metadata"][
        "profit_portfolio_shadows"
    ]
    shadow.pop("common_special_shadow")
    payload = {
        key: value
        for key, value in shadow.items()
        if key != "shadow_hash"
    }
    shadow["shadow_hash"] = canonical_hash(payload)
    event["content_hash"] = canonical_hash(event["content"])
    path.write_text(
        json.dumps(event, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="獲利 forward shadow"):
        verify_registry(ledger)


def test_registry_rejects_rehashed_special_shadow_ticket_tampering(
    tmp_path,
):
    path = tmp_path / "forward.jsonl"
    ledger = Ledger(path)
    preregister_decision(
        ledger,
        _decision(SUPER),
        registered_at="2099-01-01T12:00:00+08:00",
        mechanism_candidate=_mechanism_candidate(),
    )
    event = json.loads(path.read_text(encoding="utf-8"))
    shadow = event["content"]["arms"][ARM_COVERAGE]["metadata"][
        "special_frequency_shadow"
    ]
    shadow["tickets"][0]["special"] = 8
    shadow["selection_hash"] = canonical_hash(
        {"game": SUPER, "tickets": shadow["tickets"]}
    )
    event["content_hash"] = canonical_hash(event["content"])
    path.write_text(
        json.dumps(event, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="第二區 forward shadow"):
        verify_registry(ledger)


def test_registry_rejects_rehashed_profit_shadow_ticket_tampering(
    tmp_path,
):
    path = tmp_path / "forward.jsonl"
    ledger = Ledger(path)
    preregister_decision(
        ledger,
        _decision(SUPER),
        registered_at="2099-01-01T12:00:00+08:00",
    )
    event = json.loads(path.read_text(encoding="utf-8"))
    shadow = event["content"]["arms"][ARM_COVERAGE]["metadata"][
        "profit_portfolio_shadows"
    ]
    portfolio = shadow["portfolios"][GUARDED_PROFIT]
    portfolio["tickets"][0]["numbers"][0] = 38
    portfolio["selection_hash"] = canonical_hash(
        {"game": SUPER, "tickets": portfolio["tickets"]}
    )
    shadow_payload = {
        key: value
        for key, value in shadow.items()
        if key != "shadow_hash"
    }
    shadow["shadow_hash"] = canonical_hash(shadow_payload)
    event["content_hash"] = canonical_hash(event["content"])
    path.write_text(
        json.dumps(event, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="獲利 forward shadow"):
        verify_registry(ledger)


def test_registry_rejects_rehashed_probability_capsule_ticket_mismatch(
    tmp_path,
):
    path = tmp_path / "forward.jsonl"
    ledger = Ledger(path)
    preregister_decision(
        ledger,
        _decision(SUPER),
        registered_at="2099-01-01T12:00:00+08:00",
        probability_stacking_candidate=(
            _probability_stacking_candidate()
        ),
    )
    event = json.loads(path.read_text(encoding="utf-8"))
    shadow = event["content"]["arms"][ARM_COVERAGE]["metadata"][
        "probability_stacking_shadow"
    ]
    capsule = shadow["score_capsule"]
    selected = shadow["selected_main_numbers"]
    unselected = next(
        number for number in range(1, 39) if number not in selected
    )
    selected_number = selected[0]
    selected_index = selected_number - 1
    unselected_index = unselected - 1
    (
        capsule["main_probability_mass"][selected_index],
        capsule["main_probability_mass"][unselected_index],
    ) = (
        capsule["main_probability_mass"][unselected_index],
        capsule["main_probability_mass"][selected_index],
    )
    capsule["capsule_hash"] = canonical_hash(
        {
            key: value
            for key, value in capsule.items()
            if key != "capsule_hash"
        }
    )
    shadow["support_evidence_hash"] = canonical_hash(
        {
            "candidate_hash": shadow["candidate_hash"],
            "protocol_hash": shadow["protocol_hash"],
            "game": SUPER,
            "target": event["content"]["target"],
            "source_decision_hash": shadow[
                "source_decision_hash"
            ],
            "selected_main_numbers": shadow[
                "selected_main_numbers"
            ],
            "selected_specials": shadow["selected_specials"],
            "ticket_main_probability_mass": shadow[
                "ticket_main_probability_mass"
            ],
            "structure": shadow["structure"],
            "score_capsule_hash": capsule["capsule_hash"],
        }
    )
    event["content_hash"] = canonical_hash(event["content"])
    path.write_text(
        json.dumps(event, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="stacking shadow 登記不符"):
        verify_registry(ledger)


def test_registry_rejects_profit_settlement_without_preregistration(
    tmp_path,
):
    fresh_ledger = Ledger(tmp_path / "fresh.jsonl")
    preregister_decision(
        fresh_ledger,
        _decision(SUPER),
        registered_at="2099-01-01T12:00:00+08:00",
    )
    source_shadow = settle_ready(
        fresh_ledger, FakeStore({SUPER: [_draw(SUPER)]})
    )[0]["content"]["profit_portfolio_shadows"]

    path = tmp_path / "forward.jsonl"
    ledger = Ledger(path)
    preregister_decision(
        ledger,
        _decision(SUPER),
        registered_at="2099-01-01T12:00:00+08:00",
    )
    event = json.loads(path.read_text(encoding="utf-8"))
    metadata = event["content"]["arms"][ARM_COVERAGE]["metadata"]
    metadata["profit_portfolio_shadows"] = None
    metadata["profit_portfolio_shadows_error_type"] = "ValueError"
    event["content_hash"] = canonical_hash(event["content"])
    path.write_text(
        json.dumps(event, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    settle_ready(ledger, FakeStore({SUPER: [_draw(SUPER)]}))
    lines = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    forged = deepcopy(lines[-1]["content"])
    forged["profit_portfolio_shadows"] = source_shadow
    lines[-1]["content"] = forged
    lines[-1]["content_hash"] = canonical_hash(forged)
    path.write_text(
        "\n".join(
            json.dumps(line, ensure_ascii=False) for line in lines
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="未預註冊獲利 shadow"):
        verify_registry(ledger)


def test_registry_detects_last_line_content_tampering(tmp_path):
    path = tmp_path / "forward.jsonl"
    ledger = Ledger(path)
    preregister_decision(
        ledger,
        _decision(SUPER),
        registered_at="2099-01-01T12:00:00+08:00",
    )
    event = json.loads(path.read_text(encoding="utf-8"))
    event["content"]["arms"][ARM_RULE]["tickets"][0]["numbers"][0] = 38
    path.write_text(json.dumps(event, ensure_ascii=False) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="content_hash"):
        verify_registry(ledger)


def test_registry_rejects_rehashed_but_inconsistent_postmortem(
    tmp_path,
):
    path = tmp_path / "forward.jsonl"
    ledger = Ledger(path)
    preregister_decision(
        ledger,
        _decision(SUPER),
        registered_at="2099-01-01T12:00:00+08:00",
    )
    settle_ready(ledger, FakeStore({SUPER: [_draw(SUPER)]}))
    lines = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    settlement = lines[-1]
    postmortem = settlement["content"]["postmortem"]
    postmortem["diagnostic_flags"] = ["forged_causal_story"]
    postmortem["postmortem_hash"] = canonical_hash(
        {
            key: value
            for key, value in postmortem.items()
            if key != "postmortem_hash"
        }
    )
    settlement["content_hash"] = canonical_hash(
        settlement["content"]
    )
    path.write_text(
        "\n".join(
            json.dumps(line, ensure_ascii=False)
            for line in lines
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="flags 不完整"):
        verify_registry(ledger)


def test_registry_rejects_rehashed_profit_postmortem_tampering(
    tmp_path,
):
    path = tmp_path / "forward.jsonl"
    ledger = Ledger(path)
    preregister_decision(
        ledger,
        _decision(SUPER),
        registered_at="2099-01-01T12:00:00+08:00",
    )
    settle_ready(ledger, FakeStore({SUPER: [_draw(SUPER)]}))
    lines = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    settlement = lines[-1]
    postmortem = settlement["content"]["postmortem"]
    postmortem["profit_portfolio_review"]["portfolios"][
        GUARDED_PROFIT
    ]["net_delta_vs_coverage_ntd"] += 1
    postmortem["postmortem_hash"] = canonical_hash(
        {
            key: value
            for key, value in postmortem.items()
            if key != "postmortem_hash"
        }
    )
    settlement["content_hash"] = canonical_hash(
        settlement["content"]
    )
    path.write_text(
        "\n".join(
            json.dumps(line, ensure_ascii=False)
            for line in lines
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="比較值"):
        verify_registry(ledger)


def test_registry_rejects_semantically_inconsistent_qwen_telemetry(tmp_path):
    path = tmp_path / "forward.jsonl"
    ledger = Ledger(path)
    preregister_decision(
        ledger,
        _decision(SUPER),
        registered_at="2099-01-01T12:00:00+08:00",
    )
    event = json.loads(path.read_text(encoding="utf-8"))
    event["content"]["arms"][ARM_QWEN]["metadata"]["telemetry"][
        "outcome"
    ] = "error"
    event["content_hash"] = canonical_hash(event["content"])
    path.write_text(
        json.dumps(event, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="來源與遙測結果矛盾"):
        verify_registry(ledger)


def test_registry_rejects_forged_coverage_probability_even_with_new_hash(
    tmp_path,
):
    path = tmp_path / "forward.jsonl"
    ledger = Ledger(path)
    preregister_decision(
        ledger,
        _decision(SUPER),
        registered_at="2099-01-01T12:00:00+08:00",
    )
    event = json.loads(path.read_text(encoding="utf-8"))
    event["content"]["arms"][ARM_COVERAGE]["metadata"][
        "exact_probability_delta"
    ] = 0.5
    event["content_hash"] = canonical_hash(event["content"])
    path.write_text(
        json.dumps(event, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="coverage 前向來源"):
        verify_registry(ledger)


def test_registry_rejects_forged_consensus_support_even_with_new_hash(
    tmp_path,
):
    path = tmp_path / "forward.jsonl"
    ledger = Ledger(path)
    preregister_decision(
        ledger,
        _decision(SUPER),
        registered_at="2099-01-01T12:00:00+08:00",
    )
    event = json.loads(path.read_text(encoding="utf-8"))
    event["content"]["arms"][ARM_COVERAGE]["metadata"][
        "support_evidence_hash"
    ] = "f" * 63
    event["content_hash"] = canonical_hash(event["content"])
    path.write_text(
        json.dumps(event, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="coverage 前向來源"):
        verify_registry(ledger)


def test_registry_rejects_forged_structural_proof_even_with_new_hash(
    tmp_path,
):
    path = tmp_path / "forward.jsonl"
    ledger = Ledger(path)
    preregister_decision(
        ledger,
        _decision(SUPER),
        registered_at="2099-01-01T12:00:00+08:00",
    )
    event = json.loads(path.read_text(encoding="utf-8"))
    event["content"]["arms"][ARM_COVERAGE]["metadata"][
        "structural_optimum_proof"
    ]["certificate_hash"] = "f" * 64
    event["content_hash"] = canonical_hash(event["content"])
    path.write_text(
        json.dumps(event, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="coverage 前向來源"):
        verify_registry(ledger)


def test_registry_rejects_forged_feedback_context_even_with_new_hash(
    tmp_path,
):
    path = tmp_path / "forward.jsonl"
    ledger = Ledger(path)
    preregister_decision(
        ledger,
        _decision(SUPER),
        registered_at="2099-01-01T12:00:00+08:00",
    )
    event = json.loads(path.read_text(encoding="utf-8"))
    metadata = event["content"]["arms"][ARM_QWEN]["metadata"]
    context = metadata["feedback_context"]
    context["honesty_note"] = "forged but rehashed"
    context["feedback_hash"] = canonical_hash(
        {
            key: value
            for key, value in context.items()
            if key != "feedback_hash"
        }
    )
    metadata["feedback_provenance"]["feedback_hash"] = context[
        "feedback_hash"
    ]
    event["content_hash"] = canonical_hash(event["content"])
    path.write_text(
        json.dumps(event, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="誠實聲明不符"):
        verify_registry(ledger)


def test_registry_rejects_fallback_source_with_success_telemetry(tmp_path):
    path = tmp_path / "forward.jsonl"
    ledger = Ledger(path)
    preregister_decision(
        ledger,
        _decision(SUPER),
        registered_at="2099-01-01T12:00:00+08:00",
    )
    event = json.loads(path.read_text(encoding="utf-8"))
    event["content"]["arms"][ARM_QWEN][
        "source"
    ] = "deterministic_fallback"
    event["content_hash"] = canonical_hash(event["content"])
    path.write_text(
        json.dumps(event, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="降級來源與遙測結果矛盾"):
        verify_registry(ledger)


def test_summary_stays_collecting_until_preregistered_forward_sample_exists(
    tmp_path,
):
    ledger = Ledger(tmp_path / "forward.jsonl")
    preregister_decision(
        ledger,
        _decision(SUPER),
        registered_at="2099-01-01T12:00:00+08:00",
    )
    settle_ready(ledger, FakeStore({SUPER: [_draw(SUPER)]}))
    summary = build_summary(ledger)

    assert summary["evidence_status"] == "collecting_forward_data"
    assert summary["recommendation"] == "keep_rule_as_control"
    assert summary["games"][SUPER]["eligible_qwen_rule_pairs"] == 1
    assert summary["games"][LOTTO649]["eligible_qwen_rule_pairs"] == 0
    assert summary["verification"]["chain_valid"] is True
    assert summary["methodology"]["monitoring_checkpoints"] == [
        52,
        104,
        208,
        416,
        832,
    ]
    assert summary["methodology"]["monitoring_protocol_id"] == (
        MONITORING_PROTOCOL_ID
    )
    null_safe_rule = summary["methodology"][
        "null_safe_probability_rule"
    ]
    assert "既有 v6 登記" in null_safe_rule
    assert "不得推進 e-process" in null_safe_rule
    assert "完整 v7 結算帳本決定性重建" in null_safe_rule
    joint = summary["qwen_joint_sequential_monitor"]
    assert joint["protocol_id"] == MONITORING_PROTOCOL_ID
    assert joint["observed_pairs_by_game"] == {
        SUPER: 1,
        LOTTO649: 0,
    }
    assert joint["common_observed_pairs"] == 0
    assert joint["evaluated_pairs_per_game"] == 0
    assert joint["next_checkpoint"] == 52
    assert joint["games"] == {}
    monitor = summary["games"][SUPER]["qwen_vs_rule"][
        "sequential_monitor"
    ]
    assert monitor["observed_pairs"] == 1
    assert monitor["evaluated_pairs"] == 0
    assert monitor["next_checkpoint"] == 52
    qwen_summary = summary["games"][SUPER]["qwen_vs_rule"]
    assert qwen_summary["enough_data"] is False
    assert qwen_summary["positive_gate"] is False
    assert qwen_summary["mean_best_main_hits_delta"] is None
    assert qwen_summary["joint_checkpoint_evaluation"] is None
    assert (
        summary["operations"]["games"][SUPER]["status"]
        == "collecting_operational_data"
    )
    assert (
        summary["operations"]["deployment_gate"]["status"]
        == "collecting_joint_evidence"
    )
    profit_summary = summary["games"][SUPER][
        "profit_portfolio_shadows_vs_coverage"
    ]
    assert profit_summary["status"] == "collecting_forward_data"
    assert set(profit_summary["portfolios"]) == {
        GUARDED_PROFIT,
        UNCONSTRAINED_PROFIT,
    }
    for portfolio in profit_summary["portfolios"].values():
        assert portfolio["registered_shadows"] == 1
        assert portfolio["eligible_pairs"] == 1
        assert portfolio["sequential_monitor"]["next_checkpoint"] == 52
        assert portfolio["sequential_monitor"][
            "comparison_family_size"
        ] == 2
        assert portfolio["sequential_monitor"][
            "look_lower_tail_alpha"
        ] == 0.0025
        assert portfolio["status"] == "collecting_forward_data"
        assert portfolio["exact_metrics"][
            "empirical_floor_strict_profit"
        ]["denominator"] == 22_085_448
    assert (
        summary["games"][LOTTO649][
            "profit_portfolio_shadows_vs_coverage"
        ]["status"]
        == "not_applicable"
    )


def test_positive_block_bootstrap_interval_is_deterministic():
    differences = [1.0] * 60
    first = _block_bootstrap_ci(differences, game=SUPER)
    second = _block_bootstrap_ci(differences, game=SUPER)
    assert first == second == (1.0, 1.0)


def test_sequential_monitor_uses_only_completed_checkpoints():
    before = _sequential_monitor([1.0] * 51, game="test")
    first = _sequential_monitor([1.0] * 52, game="test")
    between = _sequential_monitor(
        [1.0] * 52 + [-100.0] * 51,
        game="test",
    )
    second = _sequential_monitor(
        [1.0] * 52 + [-100.0] * 52,
        game="test",
    )
    delayed = _sequential_monitor(
        [0.0] * 52 + [1.0] * 52,
        game="delayed",
    )

    assert before["evaluated_pairs"] == 0
    assert before["next_checkpoint"] == 52
    assert first["evaluated_pairs"] == 52
    assert first["supported"] is True
    assert between["observed_pairs"] == 103
    assert between["evaluated_pairs"] == 52
    assert between["mean_delta"] == 1
    assert between["supported"] is True
    assert second["evaluated_pairs"] == 52
    assert second["supported"] is True
    assert second["stopped_early"] is True
    assert second["next_checkpoint"] is None
    assert delayed["evaluated_pairs"] == 104
    assert delayed["supported"] is True


def test_sequential_monitor_alpha_spending_and_final_decision():
    final = _sequential_monitor(
        [0.0] * MONITORING_CHECKPOINTS[-1],
        game="final",
    )

    assert (
        MONITORING_LOOK_LOWER_TAIL_ALPHA
        * len(MONITORING_CHECKPOINTS)
        == MONITORING_FAMILY_LOWER_TAIL_ALPHA
    )
    assert final["evaluated_pairs"] == 832
    assert final["next_checkpoint"] is None
    assert final["final"] is True
    assert final["status"] == "not_supported_final"


def test_profit_monitor_splits_alpha_across_two_structures():
    monitor = _sequential_monitor(
        [1.0] * 52,
        game="profit-family",
        comparison_family_size=2,
    )

    assert monitor["protocol_id"] == MONITORING_PROTOCOL_ID
    assert monitor["comparison_family_size"] == 2
    assert monitor["look_lower_tail_alpha"] == 0.0025
    assert monitor["stream_family_lower_tail_alpha"] == 0.0125
    assert monitor["family_lower_tail_alpha"] == 0.025
    assert monitor["supported"] is True


def test_qwen_joint_monitor_never_combines_different_checkpoints():
    monitor = _joint_qwen_monitor(
        {
            SUPER: {
                "primary": [1.0] * 52 + [-100.0] * 52,
                "total": [0.0] * 104,
            },
            LOTTO649: {
                "primary": [0.0] * 52 + [1.0] * 52,
                "total": [0.0] * 104,
            },
        }
    )

    assert monitor["evaluated_pairs_per_game"] == 104
    assert monitor["completed_looks"][0]["games"][SUPER][
        "primary_supported"
    ] is True
    assert monitor["completed_looks"][0]["games"][LOTTO649][
        "primary_supported"
    ] is False
    assert monitor["completed_looks"][1]["games"][SUPER][
        "primary_supported"
    ] is False
    assert monitor["completed_looks"][1]["games"][LOTTO649][
        "primary_supported"
    ] is True
    assert monitor["supported"] is False
    assert monitor["status"] == "collecting_forward_data"
    assert monitor["next_checkpoint"] == 208


def test_qwen_joint_monitor_supports_only_same_common_checkpoint():
    delayed = [0.0] * 52 + [1.0] * 52
    monitor = _joint_qwen_monitor(
        {
            SUPER: {
                "primary": delayed,
                "total": [0.0] * 104,
            },
            LOTTO649: {
                "primary": delayed,
                "total": [0.0] * 104,
            },
        }
    )

    assert monitor["protocol_id"] == MONITORING_PROTOCOL_ID
    assert monitor["evaluated_pairs_per_game"] == 104
    assert monitor["supported"] is True
    assert monitor["status"] == "supported"
    assert monitor["next_checkpoint"] is None
    assert all(
        row["primary_supported"]
        and row["total_guardrail_passed"]
        for row in monitor["games"].values()
    )


def test_qwen_joint_monitor_uses_only_shared_completed_prefix():
    monitor = _joint_qwen_monitor(
        {
            SUPER: {
                "primary": [0.0] * 103,
                "total": [0.0] * 103,
            },
            LOTTO649: {
                "primary": [0.0] * 104,
                "total": [0.0] * 104,
            },
        }
    )

    assert monitor["observed_pairs_by_game"] == {
        SUPER: 103,
        LOTTO649: 104,
    }
    assert monitor["common_observed_pairs"] == 103
    assert monitor["evaluated_pairs_per_game"] == 52
    assert monitor["next_checkpoint"] == 104
    assert monitor["supported"] is False


def test_qwen_joint_monitor_reaches_joint_final_only_at_832():
    monitor = _joint_qwen_monitor(
        {
            game: {
                "primary": [0.0] * 832,
                "total": [0.0] * 832,
            }
            for game in (SUPER, LOTTO649)
        }
    )

    assert monitor["evaluated_pairs_per_game"] == 832
    assert monitor["final"] is True
    assert monitor["status"] == "not_supported_final"
    assert monitor["next_checkpoint"] is None


@pytest.mark.parametrize(
    "streams",
    [
        {
            SUPER: {"primary": [0.0], "total": []},
            LOTTO649: {"primary": [], "total": []},
        },
        {
            SUPER: {"primary": [float("nan")], "total": [0.0]},
            LOTTO649: {"primary": [], "total": []},
        },
        {
            SUPER: {"primary": [], "total": []},
        },
        {
            SUPER: {
                "primary": [0.0],
                "total": [0.0],
                "unexpected": [],
            },
            LOTTO649: {"primary": [], "total": []},
        },
        {
            SUPER: {"primary": [float("inf")], "total": [0.0]},
            LOTTO649: {"primary": [], "total": []},
        },
    ],
)
def test_qwen_joint_monitor_rejects_broken_metric_grain(streams):
    with pytest.raises(ValueError, match="Qwen joint monitor"):
        _joint_qwen_monitor(streams)


def test_alpha_spending_controls_normal_null_repeated_looks():
    rng = random.Random(20260719)
    threshold = NormalDist().inv_cdf(
        1 - MONITORING_LOOK_LOWER_TAIL_ALPHA
    )
    simulations = 5_000
    rejected = 0
    for _ in range(simulations):
        total = 0.0
        checkpoint_index = 0
        crossed = False
        for draw_index in range(1, MONITORING_CHECKPOINTS[-1] + 1):
            total += rng.gauss(0, 1)
            if draw_index == MONITORING_CHECKPOINTS[
                checkpoint_index
            ]:
                crossed = crossed or (
                    total / math.sqrt(draw_index) > threshold
                )
                checkpoint_index += 1
                if checkpoint_index == len(MONITORING_CHECKPOINTS):
                    break
        rejected += int(crossed)

    assert rejected / simulations < 0.03


def test_reconcile_settles_before_registering_both_next_targets(tmp_path):
    manifest = {
        "games": {
            SUPER: {"next_decision": _decision(SUPER)},
            LOTTO649: {"next_decision": _decision(LOTTO649)},
        }
    }
    first = reconcile_forward_registry(
        tmp_path,
        FakeStore(),
        manifest,
        registered_at="2099-01-01T12:00:00+08:00",
    )
    second = reconcile_forward_registry(
        tmp_path,
        FakeStore({SUPER: [_draw(SUPER)]}),
        manifest,
        registered_at="2099-01-02T12:00:00+08:00",
    )

    assert first["settlements_created"] == 0
    assert all(
        item["status"] == "created"
        for item in first["registrations"].values()
    )
    assert second["settlements_created"] == 1
    assert all(
        item["status"] == "existing"
        for item in second["registrations"].values()
    )
    assert Path(second["status_path"]).exists()
    assert second["summary"]["verification"] == {
        "chain_valid": True,
        "events": 3,
        "registrations": 2,
        "settlements": 1,
        "pending": 1,
    }


def test_new_reveal_settles_old_targets_then_freezes_new_targets_once(
    tmp_path,
):
    first_manifest = {
        "games": {
            SUPER: {"next_decision": _decision(SUPER)},
            LOTTO649: {"next_decision": _decision(LOTTO649)},
        }
    }
    next_manifest = {
        "games": {
            SUPER: {
                "next_decision": _decision(
                    SUPER,
                    date="2099-01-08",
                    period=188000002,
                )
            },
            LOTTO649: {
                "next_decision": _decision(
                    LOTTO649,
                    date="2099-01-09",
                    period=188000002,
                )
            },
        }
    }
    revealed_store = FakeStore(
        {
            SUPER: [_draw(SUPER)],
            LOTTO649: [_draw(LOTTO649)],
        }
    )

    first = reconcile_forward_registry(
        tmp_path,
        FakeStore(),
        first_manifest,
        registered_at="2099-01-01T12:00:00+08:00",
    )
    advanced = reconcile_forward_registry(
        tmp_path,
        revealed_store,
        next_manifest,
        registered_at="2099-01-07T12:00:00+08:00",
    )
    repeated = reconcile_forward_registry(
        tmp_path,
        revealed_store,
        next_manifest,
        registered_at="2099-01-07T13:00:00+08:00",
    )

    assert first["summary"]["verification"]["pending"] == 2
    assert advanced["settlements_created"] == 2
    assert all(
        registration["status"] == "created"
        for registration in advanced["registrations"].values()
    )
    assert advanced["summary"]["verification"] == {
        "chain_valid": True,
        "events": 6,
        "registrations": 4,
        "settlements": 2,
        "pending": 2,
    }
    assert (
        advanced["summary"]["feedback_memory"][SUPER][
            "settlement_count"
        ]
        == 1
    )
    assert (
        advanced["summary"]["feedback_memory"][LOTTO649][
            "settlement_count"
        ]
        == 1
    )
    assert repeated["settlements_created"] == 0
    assert all(
        registration["status"] == "existing"
        for registration in repeated["registrations"].values()
    )
    assert repeated["summary"]["verification"]["events"] == 6


def test_predecision_settlement_builds_feedback_before_new_registration(
    tmp_path,
):
    manifest = {
        "games": {
            SUPER: {"next_decision": _decision(SUPER)},
            LOTTO649: {"next_decision": _decision(LOTTO649)},
        }
    }
    reconcile_forward_registry(
        tmp_path,
        FakeStore(),
        manifest,
        registered_at="2099-01-01T12:00:00+08:00",
    )

    settled = settle_forward_registry(
        tmp_path,
        FakeStore({SUPER: [_draw(SUPER)]}),
    )
    feedback = feedback_for_target(
        tmp_path,
        SUPER,
        {"date": "2099-01-08", "period": 188000002},
    )

    assert settled["settlements_created"] == 1
    assert settled["summary"]["verification"]["settlements"] == 1
    assert feedback["settlement_count"] == 1
    assert feedback["as_of_target"] == {
        "date": "2099-01-05",
        "period": 188000001,
    }


def test_staggered_real_draw_order_preserves_both_initial_registrations(
    tmp_path,
):
    initial_targets = {
        SUPER: {"date": "2026-07-20", "period": 115000058},
        LOTTO649: {"date": "2026-07-21", "period": 115000072},
    }
    next_targets = {
        SUPER: {"date": "2026-07-23", "period": 115000059},
        LOTTO649: {"date": "2026-07-24", "period": 115000073},
    }

    def draw_for(game):
        target = initial_targets[game]
        return Draw(
            game=game,
            period=target["period"],
            date=target["date"],
            numbers=(1, 2, 3, 4, 5, 6),
            special=8 if game == SUPER else 7,
        )

    def decision_with_settled_feedback(game):
        target = next_targets[game]
        decision = _decision(
            game,
            date=target["date"],
            period=target["period"],
        )
        context = feedback_for_target(tmp_path, game, target)
        provenance = {
            "experiment_id": context["experiment_id"],
            "status": "verified",
            "feedback_hash": context["feedback_hash"],
            "settlement_count": context["settlement_count"],
            "as_of_target": context["as_of_target"],
            "source_postmortem_hashes": context[
                "source_postmortem_hashes"
            ],
        }
        judge = decision["adjudication"]["judge"]
        judge["feedback_context"] = context
        judge["feedback_provenance"] = provenance
        decision.pop("decision_hash")
        decision["decision_hash"] = canonical_hash(decision)
        return decision

    initial_manifest = {
        "games": {
            game: {
                "next_decision": _decision(
                    game,
                    date=target["date"],
                    period=target["period"],
                )
            }
            for game, target in initial_targets.items()
        }
    }
    first = reconcile_forward_registry(
        tmp_path,
        FakeStore(),
        initial_manifest,
        registered_at="2026-07-18T12:00:00+08:00",
    )
    ledger = Ledger(
        tmp_path / "simulation" / "forward" / "ledger.jsonl"
    )
    original_events = deepcopy(ledger.events_of("forward_preregister"))
    original_hashes = {
        game: first["registrations"][game]["registration_hash"]
        for game in (SUPER, LOTTO649)
    }

    first_settlement = settle_forward_registry(
        tmp_path,
        FakeStore({SUPER: [draw_for(SUPER)]}),
    )
    stage_one_manifest = {
        "games": {
            SUPER: {
                "next_decision": decision_with_settled_feedback(SUPER)
            },
            LOTTO649: {
                "next_decision": _decision(
                    LOTTO649,
                    date=initial_targets[LOTTO649]["date"],
                    period=initial_targets[LOTTO649]["period"],
                )
            },
        }
    }
    stage_one = reconcile_forward_registry(
        tmp_path,
        FakeStore({SUPER: [draw_for(SUPER)]}),
        stage_one_manifest,
        registered_at="2026-07-20T22:00:00+08:00",
    )

    assert first_settlement["settlements_created"] == 1
    assert stage_one["registrations"][SUPER]["status"] == "created"
    assert stage_one["registrations"][LOTTO649] == {
        "status": "existing",
        "registration_hash": original_hashes[LOTTO649],
    }
    assert stage_one["summary"]["verification"] == {
        "chain_valid": True,
        "events": 4,
        "registrations": 3,
        "settlements": 1,
        "pending": 2,
    }
    super_memory = stage_one["summary"]["feedback_memory"][SUPER]
    assert super_memory["settlement_count"] == 1
    assert (
        stage_one_manifest["games"][SUPER]["next_decision"][
            "adjudication"
        ]["judge"]["feedback_provenance"]["status"]
        == "verified"
    )

    second_settlement = settle_forward_registry(
        tmp_path,
        FakeStore(
            {
                SUPER: [draw_for(SUPER)],
                LOTTO649: [draw_for(LOTTO649)],
            }
        ),
    )
    stage_two_manifest = {
        "games": {
            SUPER: {
                "next_decision": decision_with_settled_feedback(SUPER)
            },
            LOTTO649: {
                "next_decision": decision_with_settled_feedback(
                    LOTTO649
                )
            },
        }
    }
    stage_two = reconcile_forward_registry(
        tmp_path,
        FakeStore(
            {
                SUPER: [draw_for(SUPER)],
                LOTTO649: [draw_for(LOTTO649)],
            }
        ),
        stage_two_manifest,
        registered_at="2026-07-21T22:00:00+08:00",
    )

    assert second_settlement["settlements_created"] == 1
    assert stage_two["registrations"][SUPER]["status"] == "existing"
    assert stage_two["registrations"][LOTTO649]["status"] == "created"
    assert stage_two["summary"]["verification"] == {
        "chain_valid": True,
        "events": 6,
        "registrations": 4,
        "settlements": 2,
        "pending": 2,
    }
    assert ledger.events_of("forward_preregister")[:2] == original_events
    assert {
        event["content_hash"]
        for event in ledger.events_of("forward_preregister")[:2]
    } == set(original_hashes.values())
    for game in (SUPER, LOTTO649):
        next_decision = stage_two_manifest["games"][game][
            "next_decision"
        ]
        provenance = next_decision["adjudication"]["judge"][
            "feedback_provenance"
        ]
        context = next_decision["adjudication"]["judge"][
            "feedback_context"
        ]
        assert provenance["status"] == "verified"
        assert provenance["settlement_count"] == 1
        assert provenance["feedback_hash"] == context["feedback_hash"]
        assert (
            provenance["source_postmortem_hashes"]
            == context["source_postmortem_hashes"]
        )
    assert verify_registry(ledger) == stage_two["summary"]["verification"]


def test_next_qwen_registration_must_archive_exact_settled_context(
    tmp_path,
):
    initial_manifest = {
        "games": {
            SUPER: {"next_decision": _decision(SUPER)},
            LOTTO649: {"next_decision": _decision(LOTTO649)},
        }
    }
    reconcile_forward_registry(
        tmp_path,
        FakeStore(),
        initial_manifest,
        registered_at="2099-01-01T12:00:00+08:00",
    )
    settle_forward_registry(
        tmp_path,
        FakeStore({SUPER: [_draw(SUPER)]}),
    )
    decision = _decision(
        SUPER,
        date="2099-01-08",
        period=188000002,
    )
    context = feedback_for_target(
        tmp_path,
        SUPER,
        decision["target"],
    )
    judge = decision["adjudication"]["judge"]
    judge["feedback_context"] = context
    judge["feedback_provenance"] = {
        "experiment_id": context["experiment_id"],
        "status": "verified",
        "feedback_hash": context["feedback_hash"],
        "settlement_count": context["settlement_count"],
        "as_of_target": context["as_of_target"],
        "source_postmortem_hashes": context[
            "source_postmortem_hashes"
        ],
    }
    decision.pop("decision_hash")
    decision["decision_hash"] = canonical_hash(decision)

    registered = preregister_decision(
        Ledger(
            tmp_path
            / "simulation"
            / "forward"
            / "ledger.jsonl"
        ),
        decision,
        registered_at="2099-01-07T12:00:00+08:00",
    )
    qwen = registered["event"]["content"]["arms"][ARM_QWEN]

    assert context["settlement_count"] == 1
    assert qwen["eligible"] is True
    assert qwen["metadata"]["feedback_context"] == context
    assert verify_registry(
        Ledger(
            tmp_path
            / "simulation"
            / "forward"
            / "ledger.jsonl"
        )
    )["registrations"] == 3
