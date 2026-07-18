"""已結算前向預測的受限錯誤診斷與下一輪回饋記憶。

只輸出可量化的組合層觀察，不把單期漏號解釋為因果，也不把實際開獎號碼
直接餵給終局裁判追號。
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import statistics

from .agent_loop import canonical_hash
from .ledger import Ledger


FEEDBACK_EXPERIMENT_ID = "settled-forward-feedback-v1"
FORWARD_EXPERIMENT_ID = "final-judge-forward-v1"
FEEDBACK_WINDOW = 13
ARM_RULE = "rule_five"
ARM_QWEN = "qwen_five"
ARM_RANDOM = "random_five"
POSTMORTEM_FIELDS = {
    "schema_version",
    "experiment_id",
    "game",
    "target",
    "registration_hash",
    "eligible_qwen_rule_pair",
    "observed_metrics",
    "diagnostic_flags",
    "guardrails",
    "interpretation",
    "postmortem_hash",
}
POSTMORTEM_METRIC_FIELDS = {
    "qwen_best_main_hits",
    "rule_best_main_hits",
    "random_best_main_hits",
    "qwen_minus_rule_best_main_hits",
    "qwen_minus_random_best_main_hits",
    "qwen_union_size",
    "rule_union_size",
    "qwen_union_main_hits",
    "rule_union_main_hits",
    "qwen_missed_actual_count",
    "qwen_repeated_miss_number_count",
    "qwen_repeated_miss_slots",
}
FEEDBACK_FIELDS = {
    "schema_version",
    "experiment_id",
    "game",
    "before_target",
    "settlement_count",
    "maximum_window",
    "as_of_target",
    "source_postmortem_hashes",
    "aggregate",
    "rows",
    "guardrails",
    "honesty_note",
    "feedback_hash",
}
FEEDBACK_ROW_FIELDS = {
    "target",
    "postmortem_hash",
    "qwen_minus_rule_best_main_hits",
    "qwen_minus_random_best_main_hits",
    "qwen_union_size",
    "rule_union_size",
    "qwen_repeated_miss_number_count",
    "diagnostic_flags",
}
FEEDBACK_AGGREGATE_FIELDS = {
    "mean_qwen_minus_rule_best_main_hits",
    "mean_qwen_minus_random_best_main_hits",
    "mean_qwen_union_size",
    "mean_rule_union_size",
    "diagnostic_flag_counts",
    "latest_diagnostic_flags",
}
POSTMORTEM_ALLOWED_FLAGS = {
    "qwen_above_rule_best",
    "qwen_below_rule_best",
    "qwen_tie_rule_best",
    "qwen_above_random_best",
    "qwen_below_random_best",
    "qwen_tie_random_best",
    "qwen_lower_union_than_rule",
    "qwen_lower_union_hits_than_rule",
    "qwen_repetition_without_hit",
    "qwen_no_three_plus_ticket",
}
POSTMORTEM_GUARDRAILS = [
    "single_draw_is_not_causal_evidence",
    "do_not_chase_missed_numbers",
    "do_not_promote_hot_or_cold_numbers_from_this_draw",
    "portfolio_structure_changes_require_repeated_forward_evidence",
]
POSTMORTEM_INTERPRETATION = (
    "本診斷只描述已凍結五注的覆蓋、重複與相對命中；"
    "不聲稱解釋獨立隨機開獎的原因。"
)
FEEDBACK_GUARDRAILS = [
    "feedback_contains_no_raw_draw_numbers",
    "never_treat_single_draw_as_causal",
    "never_chase_previous_missed_numbers",
    "use_only_as_portfolio_structure_guardrail",
]
FEEDBACK_HONESTY_NOTE = (
    "回饋只來自嚴格早於本目標期的已結算前向登記，"
    "不含原始開獎號碼，也不改變合法組合等機率事實。"
)


def _target_order(target: dict) -> tuple[str, int]:
    return str(target["date"]), int(target["period"])


def _signed_outcome(value: int) -> str:
    return "above" if value > 0 else "below" if value < 0 else "tie"


def build_postmortem(
    registration: dict,
    arm_results: dict,
    comparison: dict,
) -> dict:
    """從同一期已凍結三臂與揭曉結果建立固定、非因果診斷。"""
    qwen = arm_results[ARM_QWEN]
    rule = arm_results[ARM_RULE]
    random_arm = arm_results[ARM_RANDOM]
    qwen_minus_random = (
        qwen["best_main_hits"] - random_arm["best_main_hits"]
    )
    flags = [
        f"qwen_{_signed_outcome(comparison['qwen_minus_rule_best_main_hits'])}_rule_best",
        f"qwen_{_signed_outcome(qwen_minus_random)}_random_best",
    ]
    if qwen["union_size"] < rule["union_size"]:
        flags.append("qwen_lower_union_than_rule")
    if qwen["union_main_hits"] < rule["union_main_hits"]:
        flags.append("qwen_lower_union_hits_than_rule")
    repeated_miss_slots = sum(
        int(item["selected_count"])
        for item in qwen["repeated_but_missed"]
    )
    if repeated_miss_slots >= 6:
        flags.append("qwen_repetition_without_hit")
    if qwen["best_main_hits"] < 3:
        flags.append("qwen_no_three_plus_ticket")

    payload = {
        "schema_version": "1",
        "experiment_id": FEEDBACK_EXPERIMENT_ID,
        "game": registration["game"],
        "target": deepcopy(registration["target"]),
        "registration_hash": registration["registration_hash"],
        "eligible_qwen_rule_pair": bool(comparison["eligible"]),
        "observed_metrics": {
            "qwen_best_main_hits": qwen["best_main_hits"],
            "rule_best_main_hits": rule["best_main_hits"],
            "random_best_main_hits": random_arm["best_main_hits"],
            "qwen_minus_rule_best_main_hits": comparison[
                "qwen_minus_rule_best_main_hits"
            ],
            "qwen_minus_random_best_main_hits": qwen_minus_random,
            "qwen_union_size": qwen["union_size"],
            "rule_union_size": rule["union_size"],
            "qwen_union_main_hits": qwen["union_main_hits"],
            "rule_union_main_hits": rule["union_main_hits"],
            "qwen_missed_actual_count": len(
                qwen["missed_actual_numbers"]
            ),
            "qwen_repeated_miss_number_count": len(
                qwen["repeated_but_missed"]
            ),
            "qwen_repeated_miss_slots": repeated_miss_slots,
        },
        "diagnostic_flags": sorted(flags),
        "guardrails": list(POSTMORTEM_GUARDRAILS),
        "interpretation": POSTMORTEM_INTERPRETATION,
    }
    payload["postmortem_hash"] = canonical_hash(payload)
    return payload


def verify_postmortem(postmortem: dict) -> None:
    if not isinstance(postmortem, dict) or set(postmortem) != POSTMORTEM_FIELDS:
        raise ValueError("前向錯誤診斷欄位不符")
    if postmortem.get("schema_version") != "1":
        raise ValueError("前向錯誤診斷 schema 不符")
    if postmortem.get("experiment_id") != FEEDBACK_EXPERIMENT_ID:
        raise ValueError("前向錯誤診斷版本不符")
    payload = {
        key: value
        for key, value in postmortem.items()
        if key != "postmortem_hash"
    }
    if postmortem.get("postmortem_hash") != canonical_hash(payload):
        raise ValueError("前向錯誤診斷雜湊不符")
    flags = postmortem.get("diagnostic_flags")
    if (
        not isinstance(flags, list)
        or flags != sorted(set(flags))
        or not set(flags) <= POSTMORTEM_ALLOWED_FLAGS
    ):
        raise ValueError("前向錯誤診斷 flags 不完整")
    if (
        not isinstance(postmortem.get("observed_metrics"), dict)
        or set(postmortem["observed_metrics"]) != POSTMORTEM_METRIC_FIELDS
    ):
        raise ValueError("前向錯誤診斷 metrics 不完整")
    if (
        postmortem.get("guardrails") != POSTMORTEM_GUARDRAILS
        or postmortem.get("interpretation")
        != POSTMORTEM_INTERPRETATION
    ):
        raise ValueError("前向錯誤診斷防追號護欄不符")


def _event_content(event: dict) -> dict:
    content = event.get("content")
    if not isinstance(content, dict):
        raise ValueError("前向帳本事件缺少 content")
    if event.get("content_hash") != canonical_hash(content):
        raise ValueError("前向帳本事件 content_hash 不符")
    return content


def _mean(values: list[float]) -> float | None:
    return round(statistics.fmean(values), 4) if values else None


def _feedback_aggregate(rows: list[dict]) -> dict:
    flag_counts = Counter(
        flag for row in rows for flag in row["diagnostic_flags"]
    )
    return {
        "mean_qwen_minus_rule_best_main_hits": _mean(
            [
                float(row["qwen_minus_rule_best_main_hits"])
                for row in rows
            ]
        ),
        "mean_qwen_minus_random_best_main_hits": _mean(
            [
                float(row["qwen_minus_random_best_main_hits"])
                for row in rows
            ]
        ),
        "mean_qwen_union_size": _mean(
            [float(row["qwen_union_size"]) for row in rows]
        ),
        "mean_rule_union_size": _mean(
            [float(row["rule_union_size"]) for row in rows]
        ),
        "diagnostic_flag_counts": dict(sorted(flag_counts.items())),
        "latest_diagnostic_flags": (
            list(rows[-1]["diagnostic_flags"]) if rows else []
        ),
    }


def build_feedback_context(
    ledger: Ledger,
    game: str,
    *,
    before_target: dict,
    limit: int = FEEDBACK_WINDOW,
) -> dict:
    """建立嚴格早於下一目標期的最近已結算記憶。"""
    if not ledger.verify_chain():
        raise ValueError("前向帳本雜湊鏈中斷")
    settlements = [
        _event_content(event)
        for event in ledger.events_of("forward_settlement")
    ]
    return build_feedback_context_from_settlements(
        settlements,
        game,
        before_target=before_target,
        limit=limit,
    )


def build_feedback_context_from_settlements(
    settlements: list[dict],
    game: str,
    *,
    before_target: dict,
    limit: int = FEEDBACK_WINDOW,
) -> dict:
    """從呼叫端已依帳本順序驗證的結算內容建立受限回饋。"""
    if not 1 <= limit <= FEEDBACK_WINDOW:
        raise ValueError(
            f"feedback limit 必須介於 1 與 {FEEDBACK_WINDOW}"
        )
    cutoff = _target_order(before_target)
    rows = []
    for content in settlements:
        if not isinstance(content, dict):
            raise ValueError("前向結算內容不完整")
        if (
            content.get("experiment_id") != FORWARD_EXPERIMENT_ID
            or content.get("game") != game
            or _target_order(content["target"]) >= cutoff
        ):
            continue
        postmortem = content.get("postmortem")
        if not isinstance(postmortem, dict):
            continue
        verify_postmortem(postmortem)
        metrics = postmortem["observed_metrics"]
        rows.append(
            {
                "target": deepcopy(postmortem["target"]),
                "postmortem_hash": postmortem["postmortem_hash"],
                "qwen_minus_rule_best_main_hits": metrics[
                    "qwen_minus_rule_best_main_hits"
                ],
                "qwen_minus_random_best_main_hits": metrics[
                    "qwen_minus_random_best_main_hits"
                ],
                "qwen_union_size": metrics["qwen_union_size"],
                "rule_union_size": metrics["rule_union_size"],
                "qwen_repeated_miss_number_count": metrics[
                    "qwen_repeated_miss_number_count"
                ],
                "diagnostic_flags": list(
                    postmortem["diagnostic_flags"]
                ),
            }
        )
    rows = sorted(rows, key=lambda row: _target_order(row["target"]))[
        -limit:
    ]
    context = {
        "schema_version": "1",
        "experiment_id": FEEDBACK_EXPERIMENT_ID,
        "game": game,
        "before_target": {
            "date": str(before_target["date"]),
            "period": int(before_target["period"]),
        },
        "settlement_count": len(rows),
        "maximum_window": limit,
        "as_of_target": (
            deepcopy(rows[-1]["target"]) if rows else None
        ),
        "source_postmortem_hashes": [
            row["postmortem_hash"] for row in rows
        ],
        "aggregate": _feedback_aggregate(rows),
        "rows": rows,
        "guardrails": list(FEEDBACK_GUARDRAILS),
        "honesty_note": FEEDBACK_HONESTY_NOTE,
    }
    context["feedback_hash"] = canonical_hash(context)
    verify_feedback_context(context, game=game, target=before_target)
    return context


def verify_feedback_context(
    context: dict,
    *,
    game: str,
    target: dict,
) -> None:
    if not isinstance(context, dict) or set(context) != FEEDBACK_FIELDS:
        raise ValueError("下一輪回饋記憶欄位不符")
    if context.get("schema_version") != "1":
        raise ValueError("下一輪回饋記憶 schema 不符")
    if context.get("experiment_id") != FEEDBACK_EXPERIMENT_ID:
        raise ValueError("下一輪回饋記憶版本不符")
    if context.get("game") != game:
        raise ValueError("下一輪回饋記憶遊戲不符")
    if context.get("before_target") != {
        "date": str(target["date"]),
        "period": int(target["period"]),
    }:
        raise ValueError("下一輪回饋記憶目標不符")
    payload = {
        key: value
        for key, value in context.items()
        if key != "feedback_hash"
    }
    if context.get("feedback_hash") != canonical_hash(payload):
        raise ValueError("下一輪回饋記憶雜湊不符")
    rows = context.get("rows")
    if not isinstance(rows, list):
        raise ValueError("下一輪回饋記憶 rows 不完整")
    if context.get("settlement_count") != len(rows):
        raise ValueError("下一輪回饋記憶筆數不符")
    maximum_window = context.get("maximum_window")
    if (
        not isinstance(maximum_window, int)
        or not 1 <= maximum_window <= FEEDBACK_WINDOW
        or len(rows) > maximum_window
    ):
        raise ValueError("下一輪回饋記憶視窗不符")
    if any(
        not isinstance(row, dict) or set(row) != FEEDBACK_ROW_FIELDS
        for row in rows
    ):
        raise ValueError("下一輪回饋記憶 row 欄位不符")
    if any(
        not isinstance(row["diagnostic_flags"], list)
        or row["diagnostic_flags"]
        != sorted(set(row["diagnostic_flags"]))
        or not set(row["diagnostic_flags"])
        <= POSTMORTEM_ALLOWED_FLAGS
        for row in rows
    ):
        raise ValueError("下一輪回饋記憶 flags 不符")
    cutoff = _target_order(target)
    if any(
        _target_order(row["target"]) >= cutoff
        for row in rows
    ):
        raise ValueError("下一輪回饋記憶含目標期或未來資料")
    ordered = sorted(rows, key=lambda row: _target_order(row["target"]))
    if rows != ordered:
        raise ValueError("下一輪回饋記憶順序不符")
    source_hashes = context.get("source_postmortem_hashes")
    row_hashes = [row["postmortem_hash"] for row in rows]
    if source_hashes != row_hashes or len(set(row_hashes)) != len(row_hashes):
        raise ValueError("下一輪回饋來源雜湊筆數不符")
    expected_as_of = deepcopy(rows[-1]["target"]) if rows else None
    if context.get("as_of_target") != expected_as_of:
        raise ValueError("下一輪回饋 as_of_target 不符")
    aggregate = context.get("aggregate")
    if (
        not isinstance(aggregate, dict)
        or set(aggregate) != FEEDBACK_AGGREGATE_FIELDS
        or aggregate != _feedback_aggregate(rows)
    ):
        raise ValueError("下一輪回饋彙總不符")
    if context.get("guardrails") != FEEDBACK_GUARDRAILS:
        raise ValueError("下一輪回饋防追號護欄不符")
    if context.get("honesty_note") != FEEDBACK_HONESTY_NOTE:
        raise ValueError("下一輪回饋誠實聲明不符")
