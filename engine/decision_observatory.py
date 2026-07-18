"""終局裁判的前向運作與決策品質觀測。

這個 sidecar 不改寫 ``final-judge-forward-v1`` 的命中門檻。它只使用帶有
``final-judge-ops-v1`` 標記的新登記；舊登記不回填延遲或 token 數。
"""
from __future__ import annotations

import math
import statistics
from collections import Counter

from .games import GAME_NAMES, LOTTO649, SUPER


OPS_EXPERIMENT_ID = "final-judge-ops-v1"
MIN_OPERATIONAL_OBSERVATIONS = 10
OPERATIONAL_WINDOW = 52
QUALITY_WINDOW = 13
MAX_FALLBACK_RATE = 0.10
MIN_TELEMETRY_COMPLETENESS = 0.90
MAX_P95_WALL_DURATION_MS = 300_000

ARM_RULE = "rule_five"
ARM_QWEN = "qwen_five"
ARM_RANDOM = "random_five"


def _quantile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _mean(values: list[float]) -> float | None:
    return round(statistics.fmean(values), 4) if values else None


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _registration_order(item: tuple[str, dict]) -> tuple[str, int]:
    content = item[1]
    return content["target"]["date"], int(content["target"]["period"])


def _quality_summary(
    instrumented_hashes: set[str],
    settlements: list[dict],
    *,
    game: str,
) -> dict:
    eligible = [
        settlement
        for settlement in settlements
        if settlement["game"] == game
        and settlement["registration_hash"] in instrumented_hashes
        and settlement["qwen_vs_rule"]["eligible"]
    ]
    eligible = sorted(
        eligible,
        key=lambda item: (
            item["target"]["date"],
            int(item["target"]["period"]),
        ),
    )[-QUALITY_WINDOW:]
    qwen_best = [
        float(item["arm_results"][ARM_QWEN]["best_main_hits"])
        for item in eligible
    ]
    rule_best = [
        float(item["arm_results"][ARM_RULE]["best_main_hits"])
        for item in eligible
    ]
    random_best = [
        float(item["arm_results"][ARM_RANDOM]["best_main_hits"])
        for item in eligible
    ]
    return {
        "window_draws": len(eligible),
        "maximum_window_draws": QUALITY_WINDOW,
        "mean_best_main_hits": {
            ARM_QWEN: _mean(qwen_best),
            ARM_RULE: _mean(rule_best),
            ARM_RANDOM: _mean(random_best),
        },
        "qwen_minus_rule_best_main_hits": _mean(
            [qwen - rule for qwen, rule in zip(qwen_best, rule_best)]
        ),
        "qwen_minus_random_best_main_hits": _mean(
            [
                qwen - random_score
                for qwen, random_score in zip(qwen_best, random_best)
            ]
        ),
    }


def _game_summary(
    game: str,
    registrations: dict[str, dict],
    settlements: list[dict],
) -> dict:
    game_items = sorted(
        (
            (registration_hash, content)
            for registration_hash, content in registrations.items()
            if content["game"] == game
        ),
        key=_registration_order,
    )
    instrumented_all = [
        item
        for item in game_items
        if item[1].get("ops_experiment_id") == OPS_EXPERIMENT_ID
    ]
    window = instrumented_all[-OPERATIONAL_WINDOW:]
    telemetry_rows = []
    diagnostics_rows = []
    source_counts = Counter()
    for _, content in window:
        qwen = content["arms"][ARM_QWEN]
        source_counts[qwen.get("source") or "unknown"] += 1
        metadata = qwen.get("metadata") or {}
        telemetry = metadata.get("telemetry")
        if isinstance(telemetry, dict):
            telemetry_rows.append(telemetry)
        diagnostics = metadata.get("selection_diagnostics")
        if isinstance(diagnostics, dict):
            diagnostics_rows.append(diagnostics)

    attempts = len(window)
    successes = source_counts["ollama"]
    fallbacks = attempts - successes
    complete = sum(row.get("complete") is True for row in telemetry_rows)
    wall_durations = [
        float(row["wall_duration_ms"])
        for row in telemetry_rows
        if isinstance(row.get("wall_duration_ms"), (int, float))
    ]
    eval_counts = [
        float(row["eval_count"])
        for row in telemetry_rows
        if isinstance(row.get("eval_count"), (int, float))
    ]
    token_rates = [
        float(row["eval_tokens_per_second"])
        for row in telemetry_rows
        if isinstance(row.get("eval_tokens_per_second"), (int, float))
    ]
    completeness = _rate(complete, attempts)
    fallback_rate = _rate(fallbacks, attempts)
    p95_wall = _quantile(wall_durations, 0.95)
    enough = attempts >= MIN_OPERATIONAL_OBSERVATIONS
    completeness_ok = (
        completeness is not None
        and completeness >= MIN_TELEMETRY_COMPLETENESS
    )
    fallback_ok = (
        fallback_rate is not None
        and fallback_rate <= MAX_FALLBACK_RATE
    )
    latency_ok = (
        p95_wall is not None
        and p95_wall <= MAX_P95_WALL_DURATION_MS
    )
    alerts = []
    if enough and not completeness_ok:
        alerts.append("telemetry_incomplete")
    if enough and not fallback_ok:
        alerts.append("fallback_rate_high")
    if enough and not latency_ok:
        alerts.append("latency_p95_high")
    if not enough:
        status = "collecting_operational_data"
    elif completeness_ok and fallback_ok and latency_ok:
        status = "operationally_healthy"
    else:
        status = "operationally_degraded"

    instrumented_hashes = {
        registration_hash
        for registration_hash, _ in instrumented_all
    }
    return {
        "game_name": GAME_NAMES[game],
        "status": status,
        "legacy_uninstrumented_registrations": (
            len(game_items) - len(instrumented_all)
        ),
        "instrumented_registrations": len(instrumented_all),
        "window_attempts": attempts,
        "successful_qwen_calls": successes,
        "fallback_calls": fallbacks,
        "fallback_rate": fallback_rate,
        "telemetry_complete_calls": complete,
        "telemetry_completeness": completeness,
        "latency_ms": {
            "p50": (
                round(_quantile(wall_durations, 0.50), 3)
                if wall_durations
                else None
            ),
            "p95": round(p95_wall, 3) if p95_wall is not None else None,
            "maximum_allowed_p95": MAX_P95_WALL_DURATION_MS,
        },
        "tokens": {
            "total_eval_count": int(sum(eval_counts)),
            "mean_eval_count": _mean(eval_counts),
            "mean_eval_tokens_per_second": _mean(token_rates),
        },
        "selection": {
            "diagnostic_samples": len(diagnostics_rows),
            "mean_main_number_union_size": _mean(
                [
                    float(row["main_number_union_size"])
                    for row in diagnostics_rows
                    if isinstance(
                        row.get("main_number_union_size"),
                        (int, float),
                    )
                ]
            ),
            "mean_source_agent_count": _mean(
                [
                    float(row["source_agent_count"])
                    for row in diagnostics_rows
                    if isinstance(
                        row.get("source_agent_count"),
                        (int, float),
                    )
                ]
            ),
            "mean_pairwise_main_overlap": _mean(
                [
                    float(row["mean_pairwise_main_overlap"])
                    for row in diagnostics_rows
                    if isinstance(
                        row.get("mean_pairwise_main_overlap"),
                        (int, float),
                    )
                ]
            ),
        },
        "quality": _quality_summary(
            instrumented_hashes,
            settlements,
            game=game,
        ),
        "gates": {
            "enough_observations": enough,
            "telemetry_complete": completeness_ok,
            "fallback_rate": fallback_ok,
            "latency": latency_ok,
            "healthy": (
                enough and completeness_ok and fallback_ok and latency_ok
            ),
        },
        "alerts": alerts,
    }


def build_observatory(
    registrations: dict[str, dict],
    settlements: list[dict],
    *,
    performance_status: str,
) -> dict:
    games = {
        game: _game_summary(game, registrations, settlements)
        for game in (SUPER, LOTTO649)
    }
    operations_ready = all(
        summary["gates"]["healthy"] for summary in games.values()
    )
    performance_ready = performance_status != "collecting_forward_data"
    performance_positive = performance_status == "qwen_advantage_supported"
    if not performance_ready or any(
        summary["status"] == "collecting_operational_data"
        for summary in games.values()
    ):
        deployment_status = "collecting_joint_evidence"
        recommendation = "keep_rule_as_control"
    elif not performance_positive:
        deployment_status = "blocked_by_forward_accuracy"
        recommendation = "keep_rule_as_control"
    elif not operations_ready:
        deployment_status = "blocked_by_operational_quality"
        recommendation = "keep_rule_as_control"
    else:
        deployment_status = "eligible_for_qwen_shadow_promotion"
        recommendation = "qwen_shadow_with_rule_control"
    return {
        "schema_version": "1",
        "experiment_id": OPS_EXPERIMENT_ID,
        "methodology": {
            "operational_window": OPERATIONAL_WINDOW,
            "quality_window": QUALITY_WINDOW,
            "minimum_observations_per_game": MIN_OPERATIONAL_OBSERVATIONS,
            "maximum_fallback_rate": MAX_FALLBACK_RATE,
            "minimum_telemetry_completeness": MIN_TELEMETRY_COMPLETENESS,
            "maximum_p95_wall_duration_ms": MAX_P95_WALL_DURATION_MS,
            "deployment_rule": (
                "原前向命中門檻通過，且兩款遊戲最近 52 次中的至少 10 次"
                "儀器化呼叫同時通過完整度、降級率與 p95 延遲，才可進入"
                "Qwen shadow promotion；不會自動移除規則控制組。"
            ),
        },
        "games": games,
        "deployment_gate": {
            "performance_status": performance_status,
            "operations_ready": operations_ready,
            "status": deployment_status,
            "recommendation": recommendation,
        },
        "honesty_note": (
            "只統計帶 final-judge-ops-v1 標記的開獎前登記；"
            "既有登記缺少的延遲與 token 數不回填。"
        ),
    }
