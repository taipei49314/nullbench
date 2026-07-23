"""真實前向閉環 Goal 的唯讀驗收測試。"""
from __future__ import annotations

from copy import deepcopy

from engine.agent_loop import canonical_hash
from engine.forward_feedback import (
    FEEDBACK_EXPERIMENT_ID,
    FEEDBACK_GUARDRAILS,
    FEEDBACK_HONESTY_NOTE,
)
from engine.forward_lab import (
    ARM_COVERAGE,
    ARM_QWEN,
    COVERAGE_FORWARD_EXPERIMENT_ID,
    COVERAGE_FORWARD_EXPERIMENT_ID_V4,
    COVERAGE_FORWARD_EXPERIMENT_ID_V5,
    COVERAGE_FORWARD_EXPERIMENT_ID_V6,
    MONITORING_PROTOCOL_ID,
)
from engine.games import LOTTO649, SUPER
from goal_verify import evaluate_goal_state
from research.structural_optimum import structural_proof_reference


def _event(event_type: str, content: dict) -> dict:
    return {
        "type": event_type,
        "content": content,
        "content_hash": canonical_hash(content),
    }


def _forward_snapshot(registry_summary: dict) -> dict:
    return {
        "verification": registry_summary,
        "methodology": {
            "monitoring_protocol_id": MONITORING_PROTOCOL_ID
        },
        "qwen_joint_sequential_monitor": {
            "protocol_id": MONITORING_PROTOCOL_ID
        },
    }


def _feedback(game: str, old_target: dict, new_target: dict, marker: str):
    row = {
        "target": deepcopy(old_target),
        "postmortem_hash": marker * 64,
        "qwen_minus_rule_best_main_hits": 0,
        "qwen_minus_random_best_main_hits": 1,
        "qwen_union_size": 24,
        "rule_union_size": 25,
        "qwen_repeated_miss_number_count": 0,
        "diagnostic_flags": ["qwen_tie_rule_best"],
    }
    context = {
        "schema_version": "1",
        "experiment_id": FEEDBACK_EXPERIMENT_ID,
        "game": game,
        "before_target": deepcopy(new_target),
        "settlement_count": 1,
        "maximum_window": 13,
        "as_of_target": deepcopy(old_target),
        "source_postmortem_hashes": [marker * 64],
        "aggregate": {
            "mean_qwen_minus_rule_best_main_hits": 0.0,
            "mean_qwen_minus_random_best_main_hits": 1.0,
            "mean_qwen_union_size": 24.0,
            "mean_rule_union_size": 25.0,
            "diagnostic_flag_counts": {"qwen_tie_rule_best": 1},
            "latest_diagnostic_flags": ["qwen_tie_rule_best"],
        },
        "rows": [row],
        "guardrails": list(FEEDBACK_GUARDRAILS),
        "honesty_note": FEEDBACK_HONESTY_NOTE,
    }
    context["feedback_hash"] = canonical_hash(context)
    provenance = {
        "experiment_id": FEEDBACK_EXPERIMENT_ID,
        "status": "verified",
        "feedback_hash": context["feedback_hash"],
        "settlement_count": 1,
        "as_of_target": deepcopy(old_target),
        "source_postmortem_hashes": [marker * 64],
    }
    return context, provenance


def _complete_inputs():
    events = []
    expected = {}
    manifest = {"games": {}}
    source_dates = {}
    for index, game in enumerate((SUPER, LOTTO649), 1):
        old_target = {
            "date": f"2099-01-0{index}",
            "period": 188000000 + index,
        }
        new_target = {
            "date": f"2099-01-0{index + 2}",
            "period": 188000002 + index,
        }
        initial = {
            "game": game,
            "target": old_target,
            "late": False,
            "arms": {
                ARM_QWEN: {
                    "eligible": True,
                    "source": "ollama",
                    "metadata": {"model": "qwen3:8b"},
                }
            },
        }
        initial_event = _event("forward_preregister", initial)
        expected[game] = {
            "target": old_target,
            "registration_hash": initial_event["content_hash"],
        }
        marker = str(index)
        settlement = {
            "game": game,
            "target": old_target,
            "registration_hash": initial_event["content_hash"],
            "qwen_vs_rule": {"eligible": True},
            "postmortem": {"postmortem_hash": marker * 64},
        }
        context, provenance = _feedback(
            game, old_target, new_target, marker
        )
        decision_hash = canonical_hash(
            {"game": game, "target": new_target}
        )
        next_registration = {
            "game": game,
            "target": new_target,
            "source_decision_hash": decision_hash,
            "arms": {
                ARM_QWEN: {
                    "eligible": True,
                    "source": "ollama",
                    "metadata": {
                        "model": "qwen3:8b",
                        "feedback_context": context,
                        "feedback_provenance": provenance,
                    },
                },
                ARM_COVERAGE: {
                    "eligible": True,
                    "source": (
                        "deterministic_consensus_disjoint_selector"
                    ),
                    "metadata": {
                        "experiment_id": (
                            COVERAGE_FORWARD_EXPERIMENT_ID
                        ),
                        "support_evidence_hash": "a" * 64,
                        "structural_optimum_proof": (
                            structural_proof_reference()
                        ),
                        "selected_structure": {
                            "main_union_size": 30,
                            "maximum_pairwise_main_overlap": 0,
                        },
                        "exact_probability_delta": 0.01,
                        "exact_any_prize_probability_delta": 0.02,
                    },
                },
            },
        }
        events.extend(
            [
                initial_event,
                _event("forward_settlement", settlement),
                _event("forward_preregister", next_registration),
            ]
        )
        manifest["games"][game] = {
            "last_target": old_target,
            "next_decision": {
                "target": new_target,
                "decision_hash": decision_hash,
                "adjudication": {
                    "judge": {"feedback_provenance": provenance}
                },
            },
        }
        source_dates[game] = old_target["date"]
    registry_summary = {
        "chain_valid": True,
        "events": 6,
        "registrations": 4,
        "settlements": 2,
        "pending": 2,
    }
    return {
        "events": events,
        "registry_summary": registry_summary,
        "automation_status": {
            "watcher_state": "online",
            "consecutive_failures": 0,
            "last_success_at": "2099-01-03T22:00:00+08:00",
            "heartbeat_at": "2099-01-03T22:00:20+08:00",
        },
        "automation_history": {"chain_valid": True},
        "forward_snapshot": _forward_snapshot(registry_summary),
        "manifest": manifest,
        "shadow_research": {
            "generated_at": "2099-01-03T22:00:00+08:00",
            "data_quality": {"source_last_dates": source_dates},
            "records_integrity": {"unchanged": True},
        },
        "expected": expected,
        "observed_at": "2099-01-03T22:00:30+08:00",
    }


def test_goal_requires_both_real_closed_loops():
    inputs = _complete_inputs()

    result = evaluate_goal_state(**inputs)

    assert result["status"] == "complete"
    assert result["audit_state"] == "complete"
    assert result["failures"] == []
    assert all(
        game["feedback_status"] == "verified"
        for game in result["games"].values()
    )
    assert all(
        game["coverage_status"] == "qualified"
        and game["coverage_exact_probability_delta"] == 0.01
        and game["coverage_any_prize_probability_delta"] == 0.02
        for game in result["games"].values()
    )


def test_goal_accepts_current_v4_v5_or_v6_coverage_registration():
    inputs = _complete_inputs()
    next_registration_event = next(
        event
        for event in inputs["events"]
        if event["type"] == "forward_preregister"
        and event["content"]["game"] == SUPER
        and event["content"]["target"]
        != inputs["expected"][SUPER]["target"]
    )
    for experiment_id in (
        COVERAGE_FORWARD_EXPERIMENT_ID_V4,
        COVERAGE_FORWARD_EXPERIMENT_ID_V5,
        COVERAGE_FORWARD_EXPERIMENT_ID_V6,
    ):
        changed = deepcopy(inputs)
        changed_event = next(
            event
            for event in changed["events"]
            if event["content_hash"]
            == next_registration_event["content_hash"]
        )
        changed_event["content"]["arms"][ARM_COVERAGE][
            "metadata"
        ]["experiment_id"] = experiment_id
        changed_event["content_hash"] = canonical_hash(
            changed_event["content"]
        )

        result = evaluate_goal_state(**changed)

        assert result["status"] == "complete"
        assert result["failures"] == []


def test_goal_requires_frozen_monitoring_v2_snapshot():
    inputs = _complete_inputs()
    inputs["forward_snapshot"]["methodology"][
        "monitoring_protocol_id"
    ] = "stale"

    result = evaluate_goal_state(**inputs)

    assert result["status"] == "incomplete"
    assert "forward_monitoring_protocol_not_current" in result["failures"]


def test_goal_refuses_missing_settlement_and_replacement_registration():
    inputs = _complete_inputs()
    inputs["observed_at"] = "2098-12-31T21:59:30+08:00"
    inputs["automation_status"]["last_success_at"] = (
        "2098-12-31T21:59:00+08:00"
    )
    inputs["automation_status"]["heartbeat_at"] = (
        "2098-12-31T21:59:20+08:00"
    )
    inputs["events"] = [
        event
        for event in inputs["events"]
        if not (
            event["type"] == "forward_settlement"
            and event["content"]["game"] == SUPER
        )
        and not (
            event["type"] == "forward_preregister"
            and event["content"]["game"] == SUPER
            and event["content"]["target"]
            != inputs["expected"][SUPER]["target"]
        )
    ]
    inputs["registry_summary"] = {
        "chain_valid": True,
        "events": 4,
        "registrations": 3,
        "settlements": 1,
        "pending": 2,
    }
    inputs["forward_snapshot"] = _forward_snapshot(
        inputs["registry_summary"]
    )

    result = evaluate_goal_state(**inputs)

    assert result["status"] == "incomplete"
    assert result["audit_state"] == "waiting"
    assert "super:settlement_missing" in result["failures"]
    assert "super:next_registration_missing" in result["failures"]
    assert result["games"][SUPER]["official_result_overdue"] is False


def test_goal_blocks_when_official_result_is_overdue():
    inputs = _complete_inputs()
    inputs["observed_at"] = "2099-01-01T22:00:00+08:00"
    inputs["automation_status"]["last_success_at"] = (
        "2099-01-01T21:59:30+08:00"
    )
    inputs["automation_status"]["heartbeat_at"] = (
        "2099-01-01T21:59:50+08:00"
    )
    inputs["events"] = [
        event
        for event in inputs["events"]
        if not (
            event["type"] == "forward_settlement"
            and event["content"]["game"] == SUPER
        )
        and not (
            event["type"] == "forward_preregister"
            and event["content"]["game"] == SUPER
            and event["content"]["target"]
            != inputs["expected"][SUPER]["target"]
        )
    ]
    inputs["registry_summary"] = {
        "chain_valid": True,
        "events": 4,
        "registrations": 3,
        "settlements": 1,
        "pending": 2,
    }
    inputs["forward_snapshot"] = _forward_snapshot(
        inputs["registry_summary"]
    )

    result = evaluate_goal_state(**inputs)

    assert result["status"] == "incomplete"
    assert result["audit_state"] == "blocked"
    assert "super:settlement_missing" in result["failures"]
    assert "super:official_result_overdue" in result["failures"]
    assert result["games"][SUPER]["official_result_overdue"] is True
    assert (
        result["games"][SUPER]["official_result_deadline"]
        == "2099-01-01T22:00:00+08:00"
    )


def test_goal_refuses_changed_original_registration_hash():
    inputs = _complete_inputs()
    inputs["expected"][LOTTO649]["registration_hash"] = "f" * 64

    result = evaluate_goal_state(**inputs)

    assert result["status"] == "incomplete"
    assert result["audit_state"] == "blocked"
    assert "lotto649:initial_registration_missing" in result["failures"]


def test_goal_requires_qualified_coverage_on_next_registration():
    inputs = _complete_inputs()
    next_registration = next(
        event["content"]
        for event in inputs["events"]
        if event["type"] == "forward_preregister"
        and event["content"]["game"] == SUPER
        and event["content"]["target"]
        != inputs["expected"][SUPER]["target"]
    )
    next_registration["arms"].pop(ARM_COVERAGE)
    for event in inputs["events"]:
        if event.get("content") is next_registration:
            event["content_hash"] = canonical_hash(next_registration)

    result = evaluate_goal_state(**inputs)

    assert result["status"] == "incomplete"
    assert result["audit_state"] == "blocked"
    assert "super:next_coverage_not_qualified" in result["failures"]


def test_goal_rejects_unverified_structural_proof_reference():
    inputs = _complete_inputs()
    next_registration = next(
        event["content"]
        for event in inputs["events"]
        if event["type"] == "forward_preregister"
        and event["content"]["game"] == SUPER
        and event["content"]["target"]
        != inputs["expected"][SUPER]["target"]
    )
    next_registration["arms"][ARM_COVERAGE]["metadata"][
        "structural_optimum_proof"
    ]["certificate_hash"] = "f" * 64
    for event in inputs["events"]:
        if event.get("content") is next_registration:
            event["content_hash"] = canonical_hash(next_registration)

    result = evaluate_goal_state(**inputs)

    assert result["status"] == "incomplete"
    assert "super:next_coverage_not_qualified" in result["failures"]


def test_goal_refuses_stale_watcher_heartbeat():
    inputs = _complete_inputs()
    inputs["automation_status"]["heartbeat_at"] = (
        "2099-01-03T21:55:00+08:00"
    )

    result = evaluate_goal_state(**inputs)

    assert result["status"] == "incomplete"
    assert result["audit_state"] == "blocked"
    assert "watcher_heartbeat_stale" in result["failures"]
    assert result["watcher"]["heartbeat_age_seconds"] == 330
    assert result["watcher"]["maximum_heartbeat_age_seconds"] == 120
