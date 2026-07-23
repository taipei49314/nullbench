"""前向 A/B 一鍵驗收入口測試。"""
from copy import deepcopy

import pytest

import forward_verify
from engine.agent_loop import canonical_hash
from engine.decision_observatory import OPS_EXPERIMENT_ID
from engine.forward_feedback import FEEDBACK_HONESTY_NOTE
from engine.forward_lab import (
    MONITORING_CHECKPOINTS,
    MONITORING_PROTOCOL_ID,
    PROBABILITY_SCORE_MONITORING_PROTOCOL_ID,
    PROBABILITY_STACKING_MONITORING_PROTOCOL_ID,
    PROBABILITY_STACKING_PROMOTION_GATE_ID,
)
from research.profit_portfolio_forward import (
    COMMON_SPECIAL_SHADOW_EXPERIMENT_ID,
    EXPERIMENT_ID as PROFIT_SHADOW_EXPERIMENT_ID,
    PORTFOLIO_IDS as PROFIT_PORTFOLIO_IDS,
)
from research.probability_stacking import (
    FORWARD_EXPERIMENT_ID as PROBABILITY_STACKING_EXPERIMENT_ID,
    SCORE_CAPSULE_EXPERIMENT_ID,
)
from research.null_safe_probability import (
    FORWARD_EXPERIMENT_ID as NULL_SAFE_PROBABILITY_EXPERIMENT_ID,
    SCORE_CAPSULE_EXPERIMENT_ID as NULL_SAFE_SCORE_CAPSULE_EXPERIMENT_ID,
)


def _empty_feedback(game):
    context = {
        "schema_version": "1",
        "experiment_id": "settled-forward-feedback-v1",
        "game": game,
        "before_target": {
            "date": "9999-12-31",
            "period": 9_999_999_999,
        },
        "settlement_count": 0,
        "maximum_window": 13,
        "as_of_target": None,
        "source_postmortem_hashes": [],
        "aggregate": {
            "mean_qwen_minus_rule_best_main_hits": None,
            "mean_qwen_minus_random_best_main_hits": None,
            "mean_qwen_union_size": None,
            "mean_rule_union_size": None,
            "diagnostic_flag_counts": {},
            "latest_diagnostic_flags": [],
        },
        "rows": [],
        "guardrails": [
            "feedback_contains_no_raw_draw_numbers",
            "never_treat_single_draw_as_causal",
            "never_chase_previous_missed_numbers",
            "use_only_as_portfolio_structure_guardrail",
        ],
        "honesty_note": FEEDBACK_HONESTY_NOTE,
    }
    context["feedback_hash"] = canonical_hash(context)
    return context


def _monitor(comparison_family_size=1):
    return {
        "protocol_id": MONITORING_PROTOCOL_ID,
        "comparison_family_size": comparison_family_size,
        "look_lower_tail_alpha": 0.025
        / len(MONITORING_CHECKPOINTS)
        / comparison_family_size,
        "stream_family_lower_tail_alpha": (
            0.025 / comparison_family_size
        ),
        "family_lower_tail_alpha": 0.025,
        "status": "collecting_forward_data",
    }


def _valid_result():
    games = {
        game: {
            "qwen_vs_rule": {
                "sequential_monitor": _monitor(),
                "joint_checkpoint_evaluation": None,
                "enough_data": False,
                "positive_gate": False,
            },
            "profit_portfolio_shadows_vs_coverage": {
                "experiment_id": PROFIT_SHADOW_EXPERIMENT_ID,
                "status": (
                    "not_applicable"
                    if game == "lotto649"
                    else "collecting_forward_data"
                ),
                "portfolios": {
                    portfolio_id: {
                        "sequential_monitor": _monitor(2)
                    }
                    for portfolio_id in PROFIT_PORTFOLIO_IDS
                },
            },
            "profit_common_special_shadow_vs_baseline": {
                "experiment_id": (
                    COMMON_SPECIAL_SHADOW_EXPERIMENT_ID
                ),
                "status": (
                    "not_applicable"
                    if game == "lotto649"
                    else "not_registered"
                ),
                "portfolios": {
                    portfolio_id: {
                        "sequential_monitor": _monitor(2)
                    }
                    for portfolio_id in PROFIT_PORTFOLIO_IDS
                },
            },
            "probability_stacking_shadow_vs_coverage": {
                "experiment_id": (
                    PROBABILITY_STACKING_EXPERIMENT_ID
                ),
                "registered_shadows": 0,
                "eligible_pairs": 0,
                "candidate_hash": None,
                "status": "collecting_forward_data",
                "joint_checkpoint_evaluation": None,
                "probability_score_vs_uniform": {
                    "experiment_id": SCORE_CAPSULE_EXPERIMENT_ID,
                    "registered_capsules": 0,
                    "eligible_scores": 0,
                    "special_applicable": game == "super",
                    "status": "collecting_forward_data",
                    "joint_checkpoint_evaluation": None,
                },
            },
            "null_safe_probability_shadow": {
                "experiment_id": (
                    NULL_SAFE_PROBABILITY_EXPERIMENT_ID
                ),
                "score_capsule_experiment_id": (
                    NULL_SAFE_SCORE_CAPSULE_EXPERIMENT_ID
                ),
                "registered_shadows": 0,
                "eligible_scores": 0,
                "candidate_hash": None,
                "historical_backfill_allowed": False,
                "main_gate_activations_at_registration": 0,
                "special_gate_activations_at_registration": (
                    0 if game == "super" else None
                ),
                "mean_main_safe_regret_vs_uniform": None,
                "mean_special_safe_regret_vs_uniform": None,
                "latest_main_updated_e_process": None,
                "latest_special_updated_e_process": None,
                "status": "collecting_forward_data",
            },
        }
        for game in ("super", "lotto649")
    }
    return {
        "registrations": {
            "super": {
                "status": "created",
                "registration_hash": "super-sha",
            },
            "lotto649": {
                "status": "existing",
                "registration_hash": "lotto-sha",
            },
        },
        "summary": {
            "evidence_status": "collecting_forward_data",
            "methodology": {
                "monitoring_protocol_id": MONITORING_PROTOCOL_ID,
                "monitoring_checkpoints": list(
                    MONITORING_CHECKPOINTS
                ),
                "probability_score_monitoring_protocol_id": (
                    PROBABILITY_SCORE_MONITORING_PROTOCOL_ID
                ),
                "probability_stacking_promotion_gate_id": (
                    PROBABILITY_STACKING_PROMOTION_GATE_ID
                ),
                "null_safe_probability_rule": (
                    "future-only exact subset score"
                ),
            },
            "qwen_joint_sequential_monitor": {
                "protocol_id": MONITORING_PROTOCOL_ID,
                "observed_pairs_by_game": {
                    "super": 0,
                    "lotto649": 0,
                },
                "common_observed_pairs": 0,
                "evaluated_pairs_per_game": 0,
                "next_checkpoint": 52,
                "look_lower_tail_alpha": 0.005,
                "family_lower_tail_alpha": 0.025,
                "intersection_union_test": True,
                "games": {},
                "supported": False,
                "final": False,
                "status": "collecting_forward_data",
            },
            "probability_stacking_joint_sequential_monitor": {
                "protocol_id": (
                    PROBABILITY_STACKING_MONITORING_PROTOCOL_ID
                ),
                "experiment_id": (
                    PROBABILITY_STACKING_EXPERIMENT_ID
                ),
                "observed_pairs_by_game": {
                    "super": 0,
                    "lotto649": 0,
                },
                "common_observed_pairs": 0,
                "evaluated_pairs_per_game": 0,
                "next_checkpoint": 52,
                "look_lower_tail_alpha": 0.005,
                "intersection_union_test": True,
                "games": {},
                "supported": False,
                "final": False,
                "status": "collecting_forward_data",
            },
            "probability_score_joint_sequential_monitor": {
                "protocol_id": (
                    PROBABILITY_SCORE_MONITORING_PROTOCOL_ID
                ),
                "experiment_id": SCORE_CAPSULE_EXPERIMENT_ID,
                "observed_scores_by_game": {
                    "super": 0,
                    "lotto649": 0,
                },
                "common_observed_scores": 0,
                "evaluated_scores_per_game": 0,
                "next_checkpoint": 52,
                "look_lower_tail_alpha": 0.005,
                "intersection_union_test": True,
                "historical_backfill_allowed": False,
                "games": {},
                "supported": False,
                "final": False,
                "status": "collecting_forward_data",
            },
            "probability_stacking_promotion_gate": {
                "protocol_id": (
                    PROBABILITY_STACKING_PROMOTION_GATE_ID
                ),
                "outcome_monitor_protocol_id": (
                    PROBABILITY_STACKING_MONITORING_PROTOCOL_ID
                ),
                "probability_score_monitor_protocol_id": (
                    PROBABILITY_SCORE_MONITORING_PROTOCOL_ID
                ),
                "outcome_supported": False,
                "probability_score_supported": False,
                "requires_both": True,
                "supported": False,
                "final": False,
                "status": "collecting_forward_data",
                "reason": (
                    "waiting_for_outcome_and_probability_calibration"
                ),
            },
            "verification": {
                "chain_valid": True,
                "registrations": 2,
            },
            "games": games,
            "feedback_memory": {
                "super": _empty_feedback("super"),
                "lotto649": _empty_feedback("lotto649"),
            },
            "operations": {
                "experiment_id": OPS_EXPERIMENT_ID,
                "games": {"super": {}, "lotto649": {}},
                "deployment_gate": {
                    "status": "collecting_joint_evidence"
                },
            },
        },
    }


def test_stage_commands_cover_core_and_sync_tests():
    commands = forward_verify.stage_test_commands("python")
    assert [stage for stage, _ in commands] == [
        "forward_core",
        "sync_integration",
    ]
    assert all(command[:6] == [
        "python",
        "-B",
        "-X",
        "utf8",
        "-m",
        "pytest",
    ] for _, command in commands)
    assert all(
        "tests/test_forward_feedback.py" in command
        for _, command in commands
    )
    assert "tests/test_profit_portfolio_forward.py" in commands[0][1]


def test_run_resolves_platform_launcher(monkeypatch, tmp_path):
    captured = {}

    monkeypatch.setattr(
        forward_verify.shutil,
        "which",
        lambda executable: "C:/tools/npm.cmd",
    )
    monkeypatch.setattr(
        forward_verify.subprocess,
        "run",
        lambda command, **kwargs: captured.update(
            {"command": command, **kwargs}
        ),
    )

    forward_verify._run(["npm", "test"], cwd=tmp_path)

    assert captured == {
        "command": ["C:/tools/npm.cmd", "test"],
        "cwd": tmp_path,
        "check": True,
    }


def test_formal_forward_result_requires_chain_and_both_games():
    forward_verify.verify_forward_result(_valid_result())


def test_joint_monitor_contract_accepts_same_checkpoint_support():
    game_rows = {
        game: {
            "observed_prefix_pairs": 52,
            "primary_supported": True,
            "total_guardrail_passed": True,
        }
        for game in ("super", "lotto649")
    }
    monitor = {
        "protocol_id": MONITORING_PROTOCOL_ID,
        "observed_pairs_by_game": {
            "super": 60,
            "lotto649": 52,
        },
        "common_observed_pairs": 52,
        "evaluated_pairs_per_game": 52,
        "next_checkpoint": None,
        "look_lower_tail_alpha": 0.005,
        "family_lower_tail_alpha": 0.025,
        "intersection_union_test": True,
        "games": game_rows,
        "supported": True,
        "final": True,
        "status": "supported",
    }

    assert forward_verify._valid_joint_monitor(monitor) is True

    broken = deepcopy(monitor)
    broken["games"]["super"]["primary_supported"] = False
    assert forward_verify._valid_joint_monitor(broken) is False

    broken = deepcopy(monitor)
    broken.update(
        {
            "evaluated_pairs_per_game": 0,
            "games": {},
            "next_checkpoint": 52,
        }
    )
    assert forward_verify._valid_joint_monitor(broken) is False


def test_probability_stacking_monitor_requires_same_checkpoint_guardrails():
    monitor = {
        "protocol_id": (
            PROBABILITY_STACKING_MONITORING_PROTOCOL_ID
        ),
        "experiment_id": PROBABILITY_STACKING_EXPERIMENT_ID,
        "observed_pairs_by_game": {
            "super": 52,
            "lotto649": 52,
        },
        "common_observed_pairs": 52,
        "evaluated_pairs_per_game": 52,
        "next_checkpoint": None,
        "look_lower_tail_alpha": 0.005,
        "intersection_union_test": True,
        "games": {
            game: {
                "observed_prefix_pairs": 52,
                "primary_supported": True,
                "guardrails_passed": True,
            }
            for game in ("super", "lotto649")
        },
        "supported": True,
        "final": True,
        "status": "supported",
    }

    assert (
        forward_verify._valid_probability_stacking_joint_monitor(
            monitor
        )
        is True
    )
    monitor["games"]["super"]["guardrails_passed"] = False
    assert (
        forward_verify._valid_probability_stacking_joint_monitor(
            monitor
        )
        is False
    )


def test_probability_score_monitor_and_promotion_gate_contract():
    monitor = {
        "protocol_id": PROBABILITY_SCORE_MONITORING_PROTOCOL_ID,
        "experiment_id": SCORE_CAPSULE_EXPERIMENT_ID,
        "observed_scores_by_game": {
            "super": 52,
            "lotto649": 52,
        },
        "common_observed_scores": 52,
        "evaluated_scores_per_game": 52,
        "next_checkpoint": None,
        "look_lower_tail_alpha": 0.005,
        "intersection_union_test": True,
        "historical_backfill_allowed": False,
        "games": {
            "super": {
                "observed_prefix_scores": 52,
                "main_supported": True,
                "special_applicable": True,
                "mean_special_information_gain_vs_uniform": 0.01,
                "special_guardrail_passed": True,
            },
            "lotto649": {
                "observed_prefix_scores": 52,
                "main_supported": True,
                "special_applicable": False,
                "mean_special_information_gain_vs_uniform": None,
                "special_guardrail_passed": True,
            },
        },
        "supported": True,
        "final": True,
        "status": "supported",
    }
    assert (
        forward_verify._valid_probability_score_joint_monitor(
            monitor
        )
        is True
    )

    broken = deepcopy(monitor)
    broken["historical_backfill_allowed"] = True
    assert (
        forward_verify._valid_probability_score_joint_monitor(
            broken
        )
        is False
    )

    outcome = deepcopy(
        _valid_result()["summary"][
            "probability_stacking_joint_sequential_monitor"
        ]
    )
    gate = {
        "protocol_id": PROBABILITY_STACKING_PROMOTION_GATE_ID,
        "outcome_monitor_protocol_id": (
            PROBABILITY_STACKING_MONITORING_PROTOCOL_ID
        ),
        "probability_score_monitor_protocol_id": (
            PROBABILITY_SCORE_MONITORING_PROTOCOL_ID
        ),
        "outcome_supported": False,
        "probability_score_supported": True,
        "requires_both": True,
        "supported": False,
        "final": False,
        "status": "collecting_forward_data",
        "reason": "waiting_for_outcome_evidence",
    }
    assert forward_verify._valid_probability_stacking_promotion_gate(
        gate,
        outcome_monitor=outcome,
        score_monitor=monitor,
    )
    gate["supported"] = True
    assert not forward_verify._valid_probability_stacking_promotion_gate(
        gate,
        outcome_monitor=outcome,
        score_monitor=monitor,
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda result: result["summary"]["verification"].update(
            {"chain_valid": False}
        ),
        lambda result: result["summary"]["verification"].update(
            {"registrations": 1}
        ),
        lambda result: result.update({"registrations": {}}),
        lambda result: result["summary"].update(
            {"evidence_status": "unknown"}
        ),
        lambda result: result["summary"]["methodology"].update(
            {"monitoring_protocol_id": "wrong"}
        ),
        lambda result: result["summary"]["methodology"].update(
            {"probability_stacking_promotion_gate_id": "wrong"}
        ),
        lambda result: result["summary"][
            "qwen_joint_sequential_monitor"
        ].update({"protocol_id": "wrong"}),
        lambda result: result["summary"][
            "qwen_joint_sequential_monitor"
        ].update({"common_observed_pairs": 1}),
        lambda result: result["summary"][
            "probability_stacking_joint_sequential_monitor"
        ].update({"protocol_id": "wrong"}),
        lambda result: result["summary"][
            "probability_score_joint_sequential_monitor"
        ].update({"historical_backfill_allowed": True}),
        lambda result: result["summary"][
            "probability_stacking_promotion_gate"
        ].update({"requires_both": False}),
        lambda result: result["summary"].update({"games": {}}),
        lambda result: result["summary"]["games"]["super"][
            "qwen_vs_rule"
        ]["sequential_monitor"].update({"protocol_id": "wrong"}),
        lambda result: result["summary"]["games"]["super"].pop(
            "profit_portfolio_shadows_vs_coverage"
        ),
        lambda result: result["summary"]["games"]["super"][
            "profit_portfolio_shadows_vs_coverage"
        ]["portfolios"][PROFIT_PORTFOLIO_IDS[0]][
            "sequential_monitor"
        ].update({"look_lower_tail_alpha": 0.005}),
        lambda result: result["summary"]["games"]["super"].pop(
            "profit_common_special_shadow_vs_baseline"
        ),
        lambda result: result["summary"]["games"]["super"].pop(
            "probability_stacking_shadow_vs_coverage"
        ),
        lambda result: result["summary"]["games"]["super"][
            "probability_stacking_shadow_vs_coverage"
        ].pop("probability_score_vs_uniform"),
        lambda result: result["summary"]["games"]["super"].pop(
            "null_safe_probability_shadow"
        ),
        lambda result: result["summary"].update(
            {"feedback_memory": {}}
        ),
        lambda result: result["summary"]["operations"].update(
            {"experiment_id": "wrong"}
        ),
        lambda result: result["summary"]["operations"].update(
            {"deployment_gate": {"status": "unknown"}}
        ),
    ],
)
def test_formal_forward_result_rejects_missing_evidence(mutation):
    result = deepcopy(_valid_result())
    mutation(result)
    with pytest.raises(RuntimeError, match="前向終局裁判 A/B 驗收失敗"):
        forward_verify.verify_forward_result(result)
