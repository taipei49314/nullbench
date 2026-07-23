"""前向終局裁判 A/B 的分階段完整驗收入口。"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys

from engine.env import Env
from engine.decision_observatory import OPS_EXPERIMENT_ID
from engine.forward_feedback import (
    FEEDBACK_EXPERIMENT_ID,
    verify_feedback_context,
)
from engine.forward_lab import (
    MONITORING_CHECKPOINTS,
    MONITORING_FAMILY_LOWER_TAIL_ALPHA,
    MONITORING_PROTOCOL_ID,
    PROBABILITY_SCORE_MONITORING_PROTOCOL_ID,
    PROBABILITY_STACKING_MONITORING_PROTOCOL_ID,
    PROBABILITY_STACKING_PROMOTION_GATE_ID,
    reconcile_forward_registry,
)
from engine.games import LOTTO649, SUPER
from research.profit_portfolio_forward import (
    COMMON_SPECIAL_SHADOW_EXPERIMENT_ID,
    EXPERIMENT_ID as PROFIT_SHADOW_EXPERIMENT_ID,
    PORTFOLIO_IDS as PROFIT_PORTFOLIO_IDS,
)
from research.probability_stacking import (
    FORWARD_EXPERIMENT_ID as PROBABILITY_STACKING_EXPERIMENT_ID,
    LOOK_LOWER_TAIL_ALPHA as PROBABILITY_STACKING_LOOK_ALPHA,
    SCORE_CAPSULE_EXPERIMENT_ID,
)
from research.null_safe_probability import (
    FORWARD_EXPERIMENT_ID as NULL_SAFE_PROBABILITY_EXPERIMENT_ID,
    SCORE_CAPSULE_EXPERIMENT_ID as NULL_SAFE_SCORE_CAPSULE_EXPERIMENT_ID,
    validate_e_process_state,
)


ROOT = Path(__file__).resolve().parent
STAGE_TESTS = (
    (
        "forward_core",
        (
            "tests/test_forward_lab.py",
            "tests/test_profit_portfolio_forward.py",
            "tests/test_forward_feedback.py",
            "tests/test_qwen_judge.py",
            "tests/test_decision_observatory.py",
            "tests/test_null_safe_probability.py",
        ),
    ),
    (
        "sync_integration",
        (
            "tests/test_sync_service.py",
            "tests/test_forward_lab.py",
            "tests/test_forward_feedback.py",
        ),
    ),
)


def tree_hash(path: Path) -> str:
    digest = hashlib.sha256()
    for file in sorted(item for item in path.rglob("*") if item.is_file()):
        digest.update(file.relative_to(path).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(file.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _run(command: list[str], *, cwd: Path = ROOT) -> None:
    executable = shutil.which(command[0])
    resolved = [executable or command[0], *command[1:]]
    subprocess.run(resolved, cwd=cwd, check=True)


def stage_test_commands(
    python: str = sys.executable,
) -> list[tuple[str, list[str]]]:
    return [
        (
            stage,
            [
                python,
                "-B",
                "-X",
                "utf8",
                "-m",
                "pytest",
                *targets,
                "-q",
                "-p",
                "no:cacheprovider",
            ],
        )
        for stage, targets in STAGE_TESTS
    ]


def _valid_sequential_monitor(
    monitor: object,
    *,
    comparison_family_size: int,
) -> bool:
    if not isinstance(monitor, dict):
        return False
    expected_look_alpha = (
        MONITORING_FAMILY_LOWER_TAIL_ALPHA
        / len(MONITORING_CHECKPOINTS)
        / comparison_family_size
    )
    expected_stream_alpha = (
        MONITORING_FAMILY_LOWER_TAIL_ALPHA
        / comparison_family_size
    )
    return (
        monitor.get("protocol_id") == MONITORING_PROTOCOL_ID
        and monitor.get("comparison_family_size")
        == comparison_family_size
        and monitor.get("look_lower_tail_alpha")
        == expected_look_alpha
        and monitor.get("stream_family_lower_tail_alpha")
        == expected_stream_alpha
        and monitor.get("family_lower_tail_alpha")
        == MONITORING_FAMILY_LOWER_TAIL_ALPHA
        and monitor.get("status")
        in {
            "collecting_forward_data",
            "supported",
            "not_supported_final",
        }
    )


def _valid_joint_monitor(monitor: object) -> bool:
    if not isinstance(monitor, dict):
        return False
    observed = monitor.get("observed_pairs_by_game")
    if (
        monitor.get("protocol_id") != MONITORING_PROTOCOL_ID
        or not isinstance(observed, dict)
        or set(observed) != {SUPER, LOTTO649}
        or any(
            not isinstance(value, int) or value < 0
            for value in observed.values()
        )
        or monitor.get("common_observed_pairs")
        != min(observed.values())
        or monitor.get("look_lower_tail_alpha")
        != (
            MONITORING_FAMILY_LOWER_TAIL_ALPHA
            / len(MONITORING_CHECKPOINTS)
        )
        or monitor.get("family_lower_tail_alpha")
        != MONITORING_FAMILY_LOWER_TAIL_ALPHA
        or monitor.get("intersection_union_test") is not True
    ):
        return False
    evaluated = monitor.get("evaluated_pairs_per_game")
    if (
        evaluated not in (0, *MONITORING_CHECKPOINTS)
        or evaluated > monitor["common_observed_pairs"]
    ):
        return False
    status = monitor.get("status")
    supported = monitor.get("supported")
    final = monitor.get("final")
    if (
        status == "supported"
        and not (supported is True and final is True)
    ) or (
        status == "not_supported_final"
        and not (supported is False and final is True)
    ) or (
        status == "collecting_forward_data"
        and not (supported is False and final is False)
    ) or status not in {
        "collecting_forward_data",
        "supported",
        "not_supported_final",
    }:
        return False
    games = monitor.get("games")
    if evaluated == 0:
        return (
            status == "collecting_forward_data"
            and supported is False
            and final is False
            and games == {}
            and monitor.get("next_checkpoint")
            == MONITORING_CHECKPOINTS[0]
        )
    if (
        evaluated == MONITORING_CHECKPOINTS[-1]
        and final is not True
    ):
        return False
    expected_next_checkpoint = (
        None
        if final
        else MONITORING_CHECKPOINTS[
            MONITORING_CHECKPOINTS.index(evaluated) + 1
        ]
    )
    valid_games = (
        isinstance(games, dict)
        and set(games) == {SUPER, LOTTO649}
        and all(
            isinstance(row, dict)
            and row.get("observed_prefix_pairs") == evaluated
            and isinstance(row.get("primary_supported"), bool)
            and isinstance(row.get("total_guardrail_passed"), bool)
            for row in games.values()
        )
    )
    if not valid_games:
        return False
    gates_passed = all(
        row["primary_supported"]
        and row["total_guardrail_passed"]
        for row in games.values()
    )
    return (
        supported is gates_passed
        and monitor.get("next_checkpoint")
        == expected_next_checkpoint
    )


def _valid_probability_stacking_joint_monitor(
    monitor: object,
) -> bool:
    if not isinstance(monitor, dict):
        return False
    observed = monitor.get("observed_pairs_by_game")
    if (
        monitor.get("protocol_id")
        != PROBABILITY_STACKING_MONITORING_PROTOCOL_ID
        or monitor.get("experiment_id")
        != PROBABILITY_STACKING_EXPERIMENT_ID
        or not isinstance(observed, dict)
        or set(observed) != {SUPER, LOTTO649}
        or any(
            not isinstance(value, int) or value < 0
            for value in observed.values()
        )
        or monitor.get("common_observed_pairs")
        != min(observed.values())
        or monitor.get("look_lower_tail_alpha")
        != PROBABILITY_STACKING_LOOK_ALPHA
        or monitor.get("intersection_union_test") is not True
    ):
        return False
    evaluated = monitor.get("evaluated_pairs_per_game")
    if (
        evaluated not in (0, *MONITORING_CHECKPOINTS)
        or evaluated > monitor["common_observed_pairs"]
    ):
        return False
    status = monitor.get("status")
    supported = monitor.get("supported")
    final = monitor.get("final")
    if (
        status == "supported"
        and not (supported is True and final is True)
    ) or (
        status == "not_supported_final"
        and not (supported is False and final is True)
    ) or (
        status == "collecting_forward_data"
        and not (supported is False and final is False)
    ) or status not in {
        "collecting_forward_data",
        "supported",
        "not_supported_final",
    }:
        return False
    games = monitor.get("games")
    if evaluated == 0:
        return (
            games == {}
            and monitor.get("next_checkpoint")
            == MONITORING_CHECKPOINTS[0]
        )
    expected_next_checkpoint = (
        None
        if final
        else MONITORING_CHECKPOINTS[
            MONITORING_CHECKPOINTS.index(evaluated) + 1
        ]
    )
    valid_games = (
        isinstance(games, dict)
        and set(games) == {SUPER, LOTTO649}
        and all(
            isinstance(row, dict)
            and row.get("observed_prefix_pairs") == evaluated
            and isinstance(row.get("primary_supported"), bool)
            and isinstance(row.get("guardrails_passed"), bool)
            for row in games.values()
        )
    )
    if not valid_games:
        return False
    gates_passed = all(
        row["primary_supported"] and row["guardrails_passed"]
        for row in games.values()
    )
    return (
        supported is gates_passed
        and monitor.get("next_checkpoint")
        == expected_next_checkpoint
    )


def _valid_probability_score_joint_monitor(
    monitor: object,
) -> bool:
    if not isinstance(monitor, dict):
        return False
    observed = monitor.get("observed_scores_by_game")
    if (
        monitor.get("protocol_id")
        != PROBABILITY_SCORE_MONITORING_PROTOCOL_ID
        or monitor.get("experiment_id")
        != SCORE_CAPSULE_EXPERIMENT_ID
        or not isinstance(observed, dict)
        or set(observed) != {SUPER, LOTTO649}
        or any(
            not isinstance(value, int) or value < 0
            for value in observed.values()
        )
        or monitor.get("common_observed_scores")
        != min(observed.values())
        or monitor.get("look_lower_tail_alpha")
        != PROBABILITY_STACKING_LOOK_ALPHA
        or monitor.get("intersection_union_test") is not True
        or monitor.get("historical_backfill_allowed") is not False
    ):
        return False
    evaluated = monitor.get("evaluated_scores_per_game")
    if (
        evaluated not in (0, *MONITORING_CHECKPOINTS)
        or evaluated > monitor["common_observed_scores"]
    ):
        return False
    status = monitor.get("status")
    supported = monitor.get("supported")
    final = monitor.get("final")
    if (
        status == "supported"
        and not (supported is True and final is True)
    ) or (
        status == "not_supported_final"
        and not (supported is False and final is True)
    ) or (
        status == "collecting_forward_data"
        and not (supported is False and final is False)
    ) or status not in {
        "collecting_forward_data",
        "supported",
        "not_supported_final",
    }:
        return False
    games = monitor.get("games")
    if evaluated == 0:
        return (
            games == {}
            and monitor.get("next_checkpoint")
            == MONITORING_CHECKPOINTS[0]
        )
    expected_next_checkpoint = (
        None
        if final
        else MONITORING_CHECKPOINTS[
            MONITORING_CHECKPOINTS.index(evaluated) + 1
        ]
    )
    if (
        not isinstance(games, dict)
        or set(games) != {SUPER, LOTTO649}
    ):
        return False
    for game, row in games.items():
        if (
            not isinstance(row, dict)
            or row.get("observed_prefix_scores") != evaluated
            or not isinstance(row.get("main_supported"), bool)
            or not isinstance(
                row.get("special_guardrail_passed"), bool
            )
            or row.get("special_applicable") is (game != SUPER)
        ):
            return False
        if (
            game == LOTTO649
            and row.get(
                "mean_special_information_gain_vs_uniform"
            )
            is not None
        ):
            return False
    gates_passed = all(
        row["main_supported"]
        and row["special_guardrail_passed"]
        for row in games.values()
    )
    return (
        supported is gates_passed
        and monitor.get("next_checkpoint")
        == expected_next_checkpoint
    )


def _valid_probability_stacking_promotion_gate(
    gate: object,
    *,
    outcome_monitor: dict,
    score_monitor: dict,
) -> bool:
    if not isinstance(gate, dict):
        return False
    outcome_supported = outcome_monitor.get("supported") is True
    score_supported = score_monitor.get("supported") is True
    supported = outcome_supported and score_supported
    rejected_final = (
        outcome_monitor.get("final") is True
        and not outcome_supported
    ) or (
        score_monitor.get("final") is True
        and not score_supported
    )
    if supported:
        expected_status = "supported"
        expected_reason = (
            "outcome_and_probability_calibration_supported"
        )
    elif rejected_final:
        expected_status = "not_supported_final"
        expected_reason = (
            "outcome_evidence_not_supported_final"
            if outcome_monitor.get("final") is True
            and not outcome_supported
            else "probability_calibration_not_supported_final"
        )
    else:
        expected_status = "collecting_forward_data"
        expected_reason = (
            "waiting_for_probability_calibration"
            if outcome_supported
            else "waiting_for_outcome_evidence"
            if score_supported
            else "waiting_for_outcome_and_probability_calibration"
        )
    return (
        gate.get("protocol_id")
        == PROBABILITY_STACKING_PROMOTION_GATE_ID
        and gate.get("outcome_monitor_protocol_id")
        == PROBABILITY_STACKING_MONITORING_PROTOCOL_ID
        and gate.get("probability_score_monitor_protocol_id")
        == PROBABILITY_SCORE_MONITORING_PROTOCOL_ID
        and gate.get("outcome_supported") is outcome_supported
        and gate.get("probability_score_supported")
        is score_supported
        and gate.get("requires_both") is True
        and gate.get("supported") is supported
        and gate.get("final") is (supported or rejected_final)
        and gate.get("status") == expected_status
        and gate.get("reason") == expected_reason
    )


def verify_forward_result(result: dict) -> None:
    failures = []
    summary = result.get("summary", {})
    verification = summary.get("verification", {})
    if verification.get("chain_valid") is not True:
        failures.append("hash_chain")
    if verification.get("registrations", 0) < 2:
        failures.append("registrations")
    if summary.get("evidence_status") not in {
        "collecting_forward_data",
        "qwen_advantage_supported",
        "qwen_advantage_not_supported",
    }:
        failures.append("evidence_status")
    methodology = summary.get("methodology", {})
    if (
        methodology.get("monitoring_protocol_id")
        != MONITORING_PROTOCOL_ID
        or methodology.get("monitoring_checkpoints")
        != list(MONITORING_CHECKPOINTS)
        or methodology.get(
            "probability_score_monitoring_protocol_id"
        )
        != PROBABILITY_SCORE_MONITORING_PROTOCOL_ID
        or methodology.get(
            "probability_stacking_promotion_gate_id"
        )
        != PROBABILITY_STACKING_PROMOTION_GATE_ID
        or not isinstance(
            methodology.get("null_safe_probability_rule"), str
        )
    ):
        failures.append("monitoring_methodology")
    joint_monitor = summary.get("qwen_joint_sequential_monitor")
    if not _valid_joint_monitor(joint_monitor):
        failures.append("qwen_joint_monitor")
        joint_monitor = {}
    stacking_joint_monitor = summary.get(
        "probability_stacking_joint_sequential_monitor"
    )
    if not _valid_probability_stacking_joint_monitor(
        stacking_joint_monitor
    ):
        failures.append("probability_stacking_joint_monitor")
        stacking_joint_monitor = {}
    probability_score_joint_monitor = summary.get(
        "probability_score_joint_sequential_monitor"
    )
    if not _valid_probability_score_joint_monitor(
        probability_score_joint_monitor
    ):
        failures.append("probability_score_joint_monitor")
        probability_score_joint_monitor = {}
    probability_stacking_promotion_gate = summary.get(
        "probability_stacking_promotion_gate"
    )
    if not _valid_probability_stacking_promotion_gate(
        probability_stacking_promotion_gate,
        outcome_monitor=stacking_joint_monitor,
        score_monitor=probability_score_joint_monitor,
    ):
        failures.append("probability_stacking_promotion_gate")
    expected_evidence_status = (
        "qwen_advantage_supported"
        if joint_monitor.get("supported") is True
        else "qwen_advantage_not_supported"
        if joint_monitor.get("final") is True
        else "collecting_forward_data"
    )
    if summary.get("evidence_status") != expected_evidence_status:
        failures.append("joint_evidence_status")
    registrations = result.get("registrations", {})
    if set(registrations) != {SUPER, LOTTO649}:
        failures.append("game_coverage")
    elif any(
        registration.get("status") not in {"created", "existing"}
        or not registration.get("registration_hash")
        for registration in registrations.values()
    ):
        failures.append("registration_contract")
    games = summary.get("games", {})
    if set(games) != {SUPER, LOTTO649}:
        failures.append("summary_games")
    else:
        for game, game_summary in games.items():
            qwen = game_summary.get("qwen_vs_rule", {})
            if not _valid_sequential_monitor(
                qwen.get("sequential_monitor"),
                comparison_family_size=1,
            ):
                failures.append(f"qwen_monitor_{game}")
            joint_game = joint_monitor.get("games", {}).get(game)
            if (
                qwen.get("joint_checkpoint_evaluation")
                != joint_game
                or qwen.get("enough_data")
                is not (joint_game is not None)
                or qwen.get("positive_gate")
                is not bool(
                    joint_monitor.get("supported")
                    and joint_game
                    and joint_game.get("primary_supported")
                    and joint_game.get("total_guardrail_passed")
                )
            ):
                failures.append(f"qwen_joint_projection_{game}")
            profit = game_summary.get(
                "profit_portfolio_shadows_vs_coverage", {}
            )
            if (
                profit.get("experiment_id")
                != PROFIT_SHADOW_EXPERIMENT_ID
                or set(profit.get("portfolios", {}))
                != set(PROFIT_PORTFOLIO_IDS)
            ):
                failures.append(f"profit_shadow_{game}")
            elif any(
                not _valid_sequential_monitor(
                    row.get("sequential_monitor"),
                    comparison_family_size=len(
                        PROFIT_PORTFOLIO_IDS
                    ),
                )
                for row in profit["portfolios"].values()
            ):
                failures.append(
                    f"profit_shadow_monitor_{game}"
                )
            if (
                game == LOTTO649
                and profit.get("status") != "not_applicable"
            ):
                failures.append("profit_shadow_lotto_status")
            common_special = game_summary.get(
                "profit_common_special_shadow_vs_baseline", {}
            )
            if (
                common_special.get("experiment_id")
                != COMMON_SPECIAL_SHADOW_EXPERIMENT_ID
                or set(common_special.get("portfolios", {}))
                != set(PROFIT_PORTFOLIO_IDS)
                or common_special.get("status")
                not in {
                    "not_applicable",
                    "not_registered",
                    "collecting_forward_data",
                    "supported",
                    "not_supported_final",
                }
            ):
                failures.append(
                    f"profit_common_special_shadow_{game}"
                )
            elif any(
                not _valid_sequential_monitor(
                    row.get("sequential_monitor"),
                    comparison_family_size=len(
                        PROFIT_PORTFOLIO_IDS
                    ),
                )
                for row in common_special[
                    "portfolios"
                ].values()
            ):
                failures.append(
                    f"profit_common_special_monitor_{game}"
                )
            if (
                game == LOTTO649
                and common_special.get("status")
                != "not_applicable"
            ):
                failures.append(
                    "profit_common_special_lotto_status"
                )
            stacking = game_summary.get(
                "probability_stacking_shadow_vs_coverage", {}
            )
            stacking_joint_game = stacking_joint_monitor.get(
                "games", {}
            ).get(game)
            score_joint_game = probability_score_joint_monitor.get(
                "games", {}
            ).get(game)
            score_summary = stacking.get(
                "probability_score_vs_uniform", {}
            )
            if (
                stacking.get("experiment_id")
                != PROBABILITY_STACKING_EXPERIMENT_ID
                or stacking.get("status")
                != stacking_joint_monitor.get("status")
                or stacking.get("joint_checkpoint_evaluation")
                != stacking_joint_game
                or not isinstance(
                    stacking.get("registered_shadows"), int
                )
                or not isinstance(
                    stacking.get("eligible_pairs"), int
                )
                or (
                    stacking.get("candidate_hash") is not None
                    and (
                        not isinstance(
                            stacking.get("candidate_hash"), str
                        )
                        or len(stacking["candidate_hash"]) != 64
                    )
                )
                or score_summary.get("experiment_id")
                != SCORE_CAPSULE_EXPERIMENT_ID
                or score_summary.get("status")
                != probability_score_joint_monitor.get("status")
                or score_summary.get(
                    "joint_checkpoint_evaluation"
                )
                != score_joint_game
                or not isinstance(
                    score_summary.get("registered_capsules"), int
                )
                or not isinstance(
                    score_summary.get("eligible_scores"), int
                )
                or score_summary.get("special_applicable")
                is (game != SUPER)
            ):
                failures.append(
                    f"probability_stacking_shadow_{game}"
                )
            null_safe = game_summary.get(
                "null_safe_probability_shadow", {}
            )
            registered_null_safe = null_safe.get(
                "registered_shadows"
            )
            eligible_null_safe = null_safe.get("eligible_scores")
            candidate_hash = null_safe.get("candidate_hash")
            main_gate_activations = null_safe.get(
                "main_gate_activations_at_registration"
            )
            special_gate_activations = null_safe.get(
                "special_gate_activations_at_registration"
            )
            null_safe_invalid = (
                null_safe.get("experiment_id")
                != NULL_SAFE_PROBABILITY_EXPERIMENT_ID
                or null_safe.get("score_capsule_experiment_id")
                != NULL_SAFE_SCORE_CAPSULE_EXPERIMENT_ID
                or null_safe.get("historical_backfill_allowed")
                is not False
                or null_safe.get("status")
                != "collecting_forward_data"
                or not isinstance(registered_null_safe, int)
                or registered_null_safe < 0
                or not isinstance(eligible_null_safe, int)
                or not 0 <= eligible_null_safe <= registered_null_safe
                or (
                    candidate_hash is not None
                    and (
                        not isinstance(candidate_hash, str)
                        or len(candidate_hash) != 64
                    )
                )
                or (
                    registered_null_safe > 0
                    and candidate_hash is None
                )
                or not isinstance(main_gate_activations, int)
                or not 0
                <= main_gate_activations
                <= registered_null_safe
                or (
                    game == SUPER
                    and (
                        not isinstance(
                            special_gate_activations, int
                        )
                        or not 0
                        <= special_gate_activations
                        <= registered_null_safe
                    )
                )
                or (
                    game == LOTTO649
                    and special_gate_activations is not None
                )
                or any(
                    value is not None
                    and (
                        not isinstance(value, (int, float))
                        or not math.isfinite(float(value))
                    )
                    for value in (
                        null_safe.get(
                            "mean_main_safe_regret_vs_uniform"
                        ),
                        null_safe.get(
                            "mean_special_safe_regret_vs_uniform"
                        ),
                    )
                )
            )
            for state_field in (
                "latest_main_updated_e_process",
                "latest_special_updated_e_process",
            ):
                state = null_safe.get(state_field)
                if state is None:
                    continue
                try:
                    validate_e_process_state(state)
                except (TypeError, ValueError):
                    null_safe_invalid = True
            if (
                game == LOTTO649
                and null_safe.get(
                    "latest_special_updated_e_process"
                )
                is not None
            ):
                null_safe_invalid = True
            if null_safe_invalid:
                failures.append(
                    f"null_safe_probability_shadow_{game}"
                )
    feedback_memory = summary.get("feedback_memory", {})
    if set(feedback_memory) != {SUPER, LOTTO649}:
        failures.append("feedback_memory_games")
    else:
        for game, context in feedback_memory.items():
            try:
                verify_feedback_context(
                    context,
                    game=game,
                    target=context.get("before_target", {}),
                )
            except (KeyError, TypeError, ValueError):
                failures.append(f"feedback_memory_{game}")
            if (
                context.get("experiment_id")
                != FEEDBACK_EXPERIMENT_ID
            ):
                failures.append(f"feedback_experiment_{game}")
    operations = summary.get("operations", {})
    if operations.get("experiment_id") != OPS_EXPERIMENT_ID:
        failures.append("operations_experiment")
    if set(operations.get("games", {})) != {SUPER, LOTTO649}:
        failures.append("operations_games")
    if operations.get("deployment_gate", {}).get("status") not in {
        "collecting_joint_evidence",
        "blocked_by_forward_accuracy",
        "blocked_by_operational_quality",
        "eligible_for_qwen_shadow_promotion",
    }:
        failures.append("deployment_gate")
    if failures:
        raise RuntimeError(
            "前向終局裁判 A/B 驗收失敗：" + ", ".join(failures)
        )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="前向 A/B 分階段測試、目前下一期凍結與完整驗收"
    )
    parser.add_argument(
        "--tests-only",
        action="store_true",
        help="只跑階段與全套測試，不操作本地前向帳本",
    )
    args = parser.parse_args(argv)
    env = Env(ROOT)
    records_before = tree_hash(env.records)

    for stage, command in stage_test_commands():
        print(f"[gate-test] {stage}", flush=True)
        _run(command)

    full_suite = [
        sys.executable,
        "-B",
        "-X",
        "utf8",
        "-m",
        "pytest",
        "tests",
        "-q",
        "-p",
        "no:cacheprovider",
    ]
    print("[gate-test] full_suite_pre", flush=True)
    _run(full_suite)

    if not args.tests_only:
        manifest_path = ROOT / "simulation" / "results" / "manifest.json"
        if not manifest_path.exists():
            raise RuntimeError(
                "找不到 simulation/results/manifest.json；"
                "請先執行 python lotto.py loop"
            )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        print("[formal] settle and preregister current forward targets", flush=True)
        result = reconcile_forward_registry(
            ROOT,
            env.store,
            manifest,
        )
        verify_forward_result(result)

        print("[gate-test] frontend_test", flush=True)
        _run(["npm", "test", "--", "--run"], cwd=ROOT / "frontend")
        print("[gate-test] frontend_lint", flush=True)
        _run(["npm", "run", "lint"], cwd=ROOT / "frontend")
        print("[gate-test] frontend_build", flush=True)
        _run(["npm", "run", "build"], cwd=ROOT / "frontend")
        print("[gate-test] full_suite_post", flush=True)
        _run(full_suite)

    records_after = tree_hash(env.records)
    if records_before != records_after:
        raise RuntimeError("前向 A/B 驗收期間正式 records/ 遭到修改")
    print("[gate-test] git_diff_check", flush=True)
    _run(["git", "diff", "--check"])
    print(
        "前向終局裁判 A/B 各階段、帳本、前端與完整測試均通過。",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
