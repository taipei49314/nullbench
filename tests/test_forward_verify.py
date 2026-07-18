"""前向 A/B 一鍵驗收入口測試。"""
from copy import deepcopy

import pytest

import forward_verify
from engine.agent_loop import canonical_hash
from engine.decision_observatory import OPS_EXPERIMENT_ID
from engine.forward_feedback import FEEDBACK_HONESTY_NOTE


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


def _valid_result():
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
            "verification": {
                "chain_valid": True,
                "registrations": 2,
            },
            "games": {"super": {}, "lotto649": {}},
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
        lambda result: result["summary"].update({"games": {}}),
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
