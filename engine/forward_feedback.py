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
from research.probability_stacking import (
    verify_probability_score_result,
)


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
POSTMORTEM_PROFIT_FIELD = "profit_portfolio_review"
POSTMORTEM_PROBABILITY_SCORE_FIELD = "probability_score_review"
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
FEEDBACK_PROFIT_FIELD = "profit_portfolio_aggregate"
FEEDBACK_PROBABILITY_SCORE_FIELD = "probability_score_aggregate"
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
FEEDBACK_ROW_PROFIT_FIELD = "profit_portfolio_review"
FEEDBACK_ROW_PROBABILITY_SCORE_FIELD = "probability_score_review"
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
PROFIT_SHADOW_EXPERIMENT_ID = "profit-portfolio-forward-shadows-v1"
PROFIT_OBJECTIVE = "empirical_floor_stress_strict_profit"
PROFIT_PORTFOLIO_IDS = ("guarded_profit", "unconstrained_profit")
PROFIT_FIVE_TICKET_COST_NTD = 500
PROFIT_REVIEW_FIELDS = {
    "experiment_id",
    "objective",
    "five_ticket_cost_ntd",
    "eligible",
    "coverage",
    "portfolios",
    "interpretation",
}
PROFIT_COMMON_SPECIAL_FIELD = "common_special_shadow"
PROFIT_COMMON_SPECIAL_EXPERIMENT_ID = (
    "profit-common-special-forward-shadow-v1"
)
PROFIT_COMMON_SPECIAL_REVIEW_FIELDS = {
    "experiment_id",
    "objective",
    "eligible",
    "portfolios",
    "interpretation",
}
PROFIT_COMMON_SPECIAL_PORTFOLIO_FIELDS = {
    "eligible",
    "empirical_floor_stress_strict_profit",
    "empirical_floor_stress_net_ntd",
    "strict_profit_delta_vs_baseline",
    "net_delta_vs_baseline_ntd",
    "verdict",
}
PROFIT_COVERAGE_FIELDS = {
    "empirical_floor_stress_strict_profit",
    "empirical_floor_stress_net_ntd",
}
PROFIT_PORTFOLIO_REVIEW_FIELDS = {
    "eligible",
    "empirical_floor_stress_strict_profit",
    "empirical_floor_stress_net_ntd",
    "strict_profit_delta_vs_coverage",
    "net_delta_vs_coverage_ntd",
    "verdict",
}
PROFIT_REVIEW_INTERPRETATION = (
    "只比較開獎前已凍結且同為五注成本的歷史最低實領壓力測試；"
    "單期結果不是因果證據，且本摘要不含原始號碼或個別票券。"
)
PROFIT_COMMON_SPECIAL_INTERPRETATION = (
    "只彙總共同第二區與同一主號結構 baseline 的前向配對結果；"
    "不含候選號、原始開獎號碼或個別票券，單期不得用來追號。"
)


def _target_order(target: dict) -> tuple[str, int]:
    return str(target["date"]), int(target["period"])


def _signed_outcome(value: int) -> str:
    return "above" if value > 0 else "below" if value < 0 else "tie"


def _build_profit_review(profit_shadow_settlement: dict) -> dict:
    coverage_result = profit_shadow_settlement["coverage_result"]
    coverage_strict_profit = bool(
        coverage_result["empirical_floor_stress_strict_profit"]
    )
    coverage_net = int(
        coverage_result["empirical_floor_stress_net_ntd"]
    )
    portfolios = {}
    for portfolio_id in PROFIT_PORTFOLIO_IDS:
        source = profit_shadow_settlement["portfolios"][portfolio_id]
        result = source["result"]
        strict_profit = bool(
            result["empirical_floor_stress_strict_profit"]
        )
        net_ntd = int(result["empirical_floor_stress_net_ntd"])
        strict_profit_delta = int(strict_profit) - int(
            coverage_strict_profit
        )
        portfolios[portfolio_id] = {
            "eligible": bool(source["eligible"]),
            "empirical_floor_stress_strict_profit": strict_profit,
            "empirical_floor_stress_net_ntd": net_ntd,
            "strict_profit_delta_vs_coverage": strict_profit_delta,
            "net_delta_vs_coverage_ntd": net_ntd - coverage_net,
            "verdict": (
                "shadow_win"
                if strict_profit_delta > 0
                else "coverage_win"
                if strict_profit_delta < 0
                else "tie"
            ),
        }
    review = {
        "experiment_id": profit_shadow_settlement["experiment_id"],
        "objective": PROFIT_OBJECTIVE,
        "five_ticket_cost_ntd": int(
            coverage_result["five_ticket_cost_ntd"]
        ),
        "eligible": bool(profit_shadow_settlement["eligible"]),
        "coverage": {
            "empirical_floor_stress_strict_profit": (
                coverage_strict_profit
            ),
            "empirical_floor_stress_net_ntd": coverage_net,
        },
        "portfolios": portfolios,
        "interpretation": PROFIT_REVIEW_INTERPRETATION,
    }
    common_source = profit_shadow_settlement.get(
        PROFIT_COMMON_SPECIAL_FIELD
    )
    if common_source is not None:
        common_portfolios = {}
        for portfolio_id in PROFIT_PORTFOLIO_IDS:
            source = common_source["portfolios"][portfolio_id]
            result = source["result"]
            baseline = portfolios[portfolio_id]
            strict_profit = bool(
                result["empirical_floor_stress_strict_profit"]
            )
            net_ntd = int(
                result["empirical_floor_stress_net_ntd"]
            )
            strict_delta = int(strict_profit) - int(
                baseline[
                    "empirical_floor_stress_strict_profit"
                ]
            )
            net_delta = (
                net_ntd
                - baseline["empirical_floor_stress_net_ntd"]
            )
            common_portfolios[portfolio_id] = {
                "eligible": bool(source["eligible"]),
                "empirical_floor_stress_strict_profit": (
                    strict_profit
                ),
                "empirical_floor_stress_net_ntd": net_ntd,
                "strict_profit_delta_vs_baseline": strict_delta,
                "net_delta_vs_baseline_ntd": net_delta,
                "verdict": (
                    "common_special_win"
                    if strict_delta > 0
                    else "baseline_special_win"
                    if strict_delta < 0
                    else "tie"
                ),
            }
        review[PROFIT_COMMON_SPECIAL_FIELD] = {
            "experiment_id": common_source["experiment_id"],
            "objective": PROFIT_OBJECTIVE,
            "eligible": bool(common_source["eligible"]),
            "portfolios": common_portfolios,
            "interpretation": (
                PROFIT_COMMON_SPECIAL_INTERPRETATION
            ),
        }
    return review


def _build_probability_score_review(
    probability_stacking_settlement: dict,
    *,
    game: str,
) -> dict | None:
    proper_score = probability_stacking_settlement.get(
        "proper_score"
    )
    if proper_score is None:
        return None
    verify_probability_score_result(proper_score, game=game)
    if (
        probability_stacking_settlement.get("candidate_hash")
        != proper_score["candidate_hash"]
        or probability_stacking_settlement.get("protocol_hash")
        != proper_score["protocol_hash"]
        or probability_stacking_settlement.get("eligible")
        != proper_score["eligible"]
    ):
        raise ValueError("機率 proper-score 與 stacking 結算來源不符")
    return deepcopy(proper_score)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _verify_profit_review(review: dict) -> None:
    expected_fields = set(PROFIT_REVIEW_FIELDS)
    if isinstance(review, dict) and PROFIT_COMMON_SPECIAL_FIELD in review:
        expected_fields.add(PROFIT_COMMON_SPECIAL_FIELD)
    if not isinstance(review, dict) or set(review) != expected_fields:
        raise ValueError("獲利回顧欄位不符")
    if review.get("experiment_id") != PROFIT_SHADOW_EXPERIMENT_ID:
        raise ValueError("獲利回顧版本不符")
    if review.get("objective") != PROFIT_OBJECTIVE:
        raise ValueError("獲利回顧目標不符")
    if (
        not _is_int(review.get("five_ticket_cost_ntd"))
        or review["five_ticket_cost_ntd"]
        != PROFIT_FIVE_TICKET_COST_NTD
        or type(review.get("eligible")) is not bool
        or review.get("interpretation") != PROFIT_REVIEW_INTERPRETATION
    ):
        raise ValueError("獲利回顧方法不符")
    coverage = review.get("coverage")
    if (
        not isinstance(coverage, dict)
        or set(coverage) != PROFIT_COVERAGE_FIELDS
        or type(
            coverage.get("empirical_floor_stress_strict_profit")
        )
        is not bool
        or not _is_int(
            coverage.get("empirical_floor_stress_net_ntd")
        )
        or coverage["empirical_floor_stress_net_ntd"]
        < -PROFIT_FIVE_TICKET_COST_NTD
        or coverage["empirical_floor_stress_strict_profit"]
        != (coverage["empirical_floor_stress_net_ntd"] > 0)
    ):
        raise ValueError("獲利回顧 coverage 不符")
    portfolios = review.get("portfolios")
    if (
        not isinstance(portfolios, dict)
        or set(portfolios) != set(PROFIT_PORTFOLIO_IDS)
    ):
        raise ValueError("獲利回顧策略不符")
    coverage_strict_profit = coverage[
        "empirical_floor_stress_strict_profit"
    ]
    coverage_net = coverage["empirical_floor_stress_net_ntd"]
    for portfolio_id in PROFIT_PORTFOLIO_IDS:
        row = portfolios[portfolio_id]
        if (
            not isinstance(row, dict)
            or set(row) != PROFIT_PORTFOLIO_REVIEW_FIELDS
            or type(row.get("eligible")) is not bool
            or row["eligible"] != review["eligible"]
            or type(
                row.get("empirical_floor_stress_strict_profit")
            )
            is not bool
            or not _is_int(
                row.get("empirical_floor_stress_net_ntd")
            )
            or row["empirical_floor_stress_net_ntd"]
            < -PROFIT_FIVE_TICKET_COST_NTD
            or row["empirical_floor_stress_strict_profit"]
            != (row["empirical_floor_stress_net_ntd"] > 0)
            or not _is_int(
                row.get("strict_profit_delta_vs_coverage")
            )
            or not _is_int(row.get("net_delta_vs_coverage_ntd"))
        ):
            raise ValueError("獲利回顧策略結果不符")
        strict_profit_delta = int(
            row["empirical_floor_stress_strict_profit"]
        ) - int(coverage_strict_profit)
        net_delta = (
            row["empirical_floor_stress_net_ntd"] - coverage_net
        )
        verdict = (
            "shadow_win"
            if strict_profit_delta > 0
            else "coverage_win"
            if strict_profit_delta < 0
            else "tie"
        )
        if (
            row["strict_profit_delta_vs_coverage"]
            != strict_profit_delta
            or row["net_delta_vs_coverage_ntd"] != net_delta
            or row.get("verdict") != verdict
        ):
            raise ValueError("獲利回顧比較值不符")
    common = review.get(PROFIT_COMMON_SPECIAL_FIELD)
    if common is None:
        return
    if (
        not isinstance(common, dict)
        or set(common) != PROFIT_COMMON_SPECIAL_REVIEW_FIELDS
        or common.get("experiment_id")
        != PROFIT_COMMON_SPECIAL_EXPERIMENT_ID
        or common.get("objective") != PROFIT_OBJECTIVE
        or type(common.get("eligible")) is not bool
        or common["eligible"] != review["eligible"]
        or common.get("interpretation")
        != PROFIT_COMMON_SPECIAL_INTERPRETATION
        or not isinstance(common.get("portfolios"), dict)
        or set(common["portfolios"]) != set(PROFIT_PORTFOLIO_IDS)
    ):
        raise ValueError("共同第二區獲利回顧不符")
    for portfolio_id in PROFIT_PORTFOLIO_IDS:
        row = common["portfolios"][portfolio_id]
        baseline = portfolios[portfolio_id]
        if (
            not isinstance(row, dict)
            or set(row)
            != PROFIT_COMMON_SPECIAL_PORTFOLIO_FIELDS
            or type(row.get("eligible")) is not bool
            or row["eligible"] != common["eligible"]
            or type(
                row.get("empirical_floor_stress_strict_profit")
            )
            is not bool
            or not _is_int(
                row.get("empirical_floor_stress_net_ntd")
            )
            or row["empirical_floor_stress_net_ntd"]
            < -PROFIT_FIVE_TICKET_COST_NTD
            or row["empirical_floor_stress_strict_profit"]
            != (row["empirical_floor_stress_net_ntd"] > 0)
            or not _is_int(
                row.get("strict_profit_delta_vs_baseline")
            )
            or not _is_int(row.get("net_delta_vs_baseline_ntd"))
        ):
            raise ValueError("共同第二區獲利回顧結果不符")
        strict_delta = int(
            row["empirical_floor_stress_strict_profit"]
        ) - int(
            baseline["empirical_floor_stress_strict_profit"]
        )
        net_delta = (
            row["empirical_floor_stress_net_ntd"]
            - baseline["empirical_floor_stress_net_ntd"]
        )
        verdict = (
            "common_special_win"
            if strict_delta > 0
            else "baseline_special_win"
            if strict_delta < 0
            else "tie"
        )
        if (
            row["strict_profit_delta_vs_baseline"]
            != strict_delta
            or row["net_delta_vs_baseline_ntd"] != net_delta
            or row.get("verdict") != verdict
        ):
            raise ValueError("共同第二區獲利回顧比較值不符")


def build_postmortem(
    registration: dict,
    arm_results: dict,
    comparison: dict,
    profit_shadow_settlement: dict | None = None,
    probability_stacking_settlement: dict | None = None,
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
    if profit_shadow_settlement is not None:
        payload[POSTMORTEM_PROFIT_FIELD] = _build_profit_review(
            profit_shadow_settlement
        )
    if probability_stacking_settlement is not None:
        probability_review = _build_probability_score_review(
            probability_stacking_settlement,
            game=registration["game"],
        )
        if probability_review is not None:
            payload[POSTMORTEM_PROBABILITY_SCORE_FIELD] = (
                probability_review
            )
    payload["postmortem_hash"] = canonical_hash(payload)
    return payload


def verify_postmortem(postmortem: dict) -> None:
    if not isinstance(postmortem, dict):
        raise ValueError("前向錯誤診斷欄位不符")
    expected_fields = set(POSTMORTEM_FIELDS)
    if POSTMORTEM_PROFIT_FIELD in postmortem:
        expected_fields.add(POSTMORTEM_PROFIT_FIELD)
    if POSTMORTEM_PROBABILITY_SCORE_FIELD in postmortem:
        expected_fields.add(POSTMORTEM_PROBABILITY_SCORE_FIELD)
    if set(postmortem) != expected_fields:
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
    if POSTMORTEM_PROFIT_FIELD in postmortem:
        if postmortem.get("game") != "super":
            raise ValueError("獲利回顧僅適用威力彩")
        _verify_profit_review(postmortem[POSTMORTEM_PROFIT_FIELD])
    if POSTMORTEM_PROBABILITY_SCORE_FIELD in postmortem:
        verify_probability_score_result(
            postmortem[POSTMORTEM_PROBABILITY_SCORE_FIELD],
            game=postmortem["game"],
        )


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


def _profit_feedback_aggregate(rows: list[dict]) -> dict:
    reviews = [
        row[FEEDBACK_ROW_PROFIT_FIELD]
        for row in rows
        if FEEDBACK_ROW_PROFIT_FIELD in row
    ]
    eligible_reviews = [
        review for review in reviews if review["eligible"]
    ]
    portfolios = {}
    for portfolio_id in PROFIT_PORTFOLIO_IDS:
        eligible_rows = [
            review["portfolios"][portfolio_id]
            for review in eligible_reviews
            if review["portfolios"][portfolio_id]["eligible"]
        ]
        verdict_counts = Counter(
            row["verdict"] for row in eligible_rows
        )
        latest = eligible_rows[-1] if eligible_rows else None
        portfolios[portfolio_id] = {
            "registered_settlement_count": len(reviews),
            "eligible_pair_count": len(eligible_rows),
            "shadow_strict_profit_count": sum(
                int(row["empirical_floor_stress_strict_profit"])
                for row in eligible_rows
            ),
            "coverage_strict_profit_count": sum(
                int(
                    review["coverage"][
                        "empirical_floor_stress_strict_profit"
                    ]
                )
                for review in eligible_reviews
                if review["portfolios"][portfolio_id]["eligible"]
            ),
            "strict_profit_delta_sum": sum(
                row["strict_profit_delta_vs_coverage"]
                for row in eligible_rows
            ),
            "mean_net_delta_vs_coverage_ntd": _mean(
                [
                    float(row["net_delta_vs_coverage_ntd"])
                    for row in eligible_rows
                ]
            ),
            "latest_strict_profit": (
                latest["empirical_floor_stress_strict_profit"]
                if latest is not None
                else None
            ),
            "latest_strict_profit_delta_vs_coverage": (
                latest["strict_profit_delta_vs_coverage"]
                if latest is not None
                else None
            ),
            "latest_net_delta_vs_coverage_ntd": (
                latest["net_delta_vs_coverage_ntd"]
                if latest is not None
                else None
            ),
            "verdict_counts": dict(sorted(verdict_counts.items())),
        }
    aggregate = {
        "objective": PROFIT_OBJECTIVE,
        "settlement_count": len(reviews),
        "eligible_settlement_count": len(eligible_reviews),
        "portfolios": portfolios,
    }
    common_pairs = [
        (review, review[PROFIT_COMMON_SPECIAL_FIELD])
        for review in reviews
        if PROFIT_COMMON_SPECIAL_FIELD in review
    ]
    eligible_common_pairs = [
        (review, common)
        for review, common in common_pairs
        if common["eligible"]
    ]
    if common_pairs:
        common_portfolios = {}
        for portfolio_id in PROFIT_PORTFOLIO_IDS:
            eligible_rows = [
                (review, common["portfolios"][portfolio_id])
                for review, common in eligible_common_pairs
                if common["portfolios"][portfolio_id]["eligible"]
            ]
            verdict_counts = Counter(
                row["verdict"] for _, row in eligible_rows
            )
            latest = (
                eligible_rows[-1][1] if eligible_rows else None
            )
            common_portfolios[portfolio_id] = {
                "registered_settlement_count": len(common_pairs),
                "eligible_pair_count": len(eligible_rows),
                "common_special_strict_profit_count": sum(
                    int(
                        row[
                            "empirical_floor_stress_strict_profit"
                        ]
                    )
                    for _, row in eligible_rows
                ),
                "baseline_special_strict_profit_count": sum(
                    int(
                        review["portfolios"][portfolio_id][
                            "empirical_floor_stress_strict_profit"
                        ]
                    )
                    for review, _ in eligible_rows
                ),
                "strict_profit_delta_sum": sum(
                    row["strict_profit_delta_vs_baseline"]
                    for _, row in eligible_rows
                ),
                "mean_net_delta_vs_baseline_ntd": _mean(
                    [
                        float(row["net_delta_vs_baseline_ntd"])
                        for _, row in eligible_rows
                    ]
                ),
                "latest_strict_profit_delta_vs_baseline": (
                    latest["strict_profit_delta_vs_baseline"]
                    if latest is not None
                    else None
                ),
                "latest_net_delta_vs_baseline_ntd": (
                    latest["net_delta_vs_baseline_ntd"]
                    if latest is not None
                    else None
                ),
                "verdict_counts": dict(
                    sorted(verdict_counts.items())
                ),
            }
        aggregate[PROFIT_COMMON_SPECIAL_FIELD] = {
            "objective": PROFIT_OBJECTIVE,
            "settlement_count": len(common_pairs),
            "eligible_settlement_count": len(
                eligible_common_pairs
            ),
            "portfolios": common_portfolios,
        }
    return aggregate


def _score_mean(values: list[float]) -> float | None:
    return round(statistics.fmean(values), 12) if values else None


def _probability_score_feedback_aggregate(
    rows: list[dict],
) -> dict:
    reviews = [
        row[FEEDBACK_ROW_PROBABILITY_SCORE_FIELD]
        for row in rows
        if FEEDBACK_ROW_PROBABILITY_SCORE_FIELD in row
    ]
    eligible = [review for review in reviews if review["eligible"]]
    main_verdict_counts = Counter(
        review["main_verdict"] for review in eligible
    )
    aggregate = {
        "settlement_count": len(reviews),
        "eligible_settlement_count": len(eligible),
        "mean_main_log_loss": _score_mean(
            [float(review["main_log_loss"]) for review in eligible]
        ),
        "mean_uniform_main_log_loss": _score_mean(
            [
                float(review["uniform_main_log_loss"])
                for review in eligible
            ]
        ),
        "mean_main_regret_vs_uniform": _score_mean(
            [
                float(review["main_regret_vs_uniform"])
                for review in eligible
            ]
        ),
        "latest_main_regret_vs_uniform": (
            float(eligible[-1]["main_regret_vs_uniform"])
            if eligible
            else None
        ),
        "main_verdict_counts": dict(
            sorted(main_verdict_counts.items())
        ),
    }
    special = [
        review
        for review in eligible
        if review["special_regret_vs_uniform"] is not None
    ]
    if special:
        special_verdict_counts = Counter(
            review["special_verdict"] for review in special
        )
        aggregate["special"] = {
            "eligible_settlement_count": len(special),
            "mean_log_loss": _score_mean(
                [
                    float(review["special_log_loss"])
                    for review in special
                ]
            ),
            "mean_uniform_log_loss": _score_mean(
                [
                    float(review["uniform_special_log_loss"])
                    for review in special
                ]
            ),
            "mean_regret_vs_uniform": _score_mean(
                [
                    float(review["special_regret_vs_uniform"])
                    for review in special
                ]
            ),
            "latest_regret_vs_uniform": float(
                special[-1]["special_regret_vs_uniform"]
            ),
            "verdict_counts": dict(
                sorted(special_verdict_counts.items())
            ),
        }
    return aggregate


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
        row = {
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
        if POSTMORTEM_PROFIT_FIELD in postmortem:
            row[FEEDBACK_ROW_PROFIT_FIELD] = deepcopy(
                postmortem[POSTMORTEM_PROFIT_FIELD]
            )
        if POSTMORTEM_PROBABILITY_SCORE_FIELD in postmortem:
            row[FEEDBACK_ROW_PROBABILITY_SCORE_FIELD] = deepcopy(
                postmortem[POSTMORTEM_PROBABILITY_SCORE_FIELD]
            )
        rows.append(row)
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
    if any(FEEDBACK_ROW_PROFIT_FIELD in row for row in rows):
        context[FEEDBACK_PROFIT_FIELD] = _profit_feedback_aggregate(
            rows
        )
    if any(
        FEEDBACK_ROW_PROBABILITY_SCORE_FIELD in row for row in rows
    ):
        context[FEEDBACK_PROBABILITY_SCORE_FIELD] = (
            _probability_score_feedback_aggregate(rows)
        )
    context["feedback_hash"] = canonical_hash(context)
    verify_feedback_context(context, game=game, target=before_target)
    return context


def verify_feedback_context(
    context: dict,
    *,
    game: str,
    target: dict,
) -> None:
    if not isinstance(context, dict):
        raise ValueError("下一輪回饋記憶欄位不符")
    expected_fields = set(FEEDBACK_FIELDS)
    if FEEDBACK_PROFIT_FIELD in context:
        expected_fields.add(FEEDBACK_PROFIT_FIELD)
    if FEEDBACK_PROBABILITY_SCORE_FIELD in context:
        expected_fields.add(FEEDBACK_PROBABILITY_SCORE_FIELD)
    if set(context) != expected_fields:
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
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("下一輪回饋記憶 row 欄位不符")
        expected_row_fields = set(FEEDBACK_ROW_FIELDS)
        if FEEDBACK_ROW_PROFIT_FIELD in row:
            expected_row_fields.add(FEEDBACK_ROW_PROFIT_FIELD)
        if FEEDBACK_ROW_PROBABILITY_SCORE_FIELD in row:
            expected_row_fields.add(
                FEEDBACK_ROW_PROBABILITY_SCORE_FIELD
            )
        if set(row) != expected_row_fields:
            raise ValueError("下一輪回饋記憶 row 欄位不符")
        if FEEDBACK_ROW_PROFIT_FIELD in row:
            _verify_profit_review(row[FEEDBACK_ROW_PROFIT_FIELD])
        if FEEDBACK_ROW_PROBABILITY_SCORE_FIELD in row:
            verify_probability_score_result(
                row[FEEDBACK_ROW_PROBABILITY_SCORE_FIELD],
                game=game,
            )
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
    has_profit_rows = any(
        FEEDBACK_ROW_PROFIT_FIELD in row for row in rows
    )
    if has_profit_rows != (FEEDBACK_PROFIT_FIELD in context):
        raise ValueError("下一輪獲利回饋來源不符")
    if has_profit_rows and context[FEEDBACK_PROFIT_FIELD] != (
        _profit_feedback_aggregate(rows)
    ):
        raise ValueError("下一輪獲利回饋彙總不符")
    has_probability_score_rows = any(
        FEEDBACK_ROW_PROBABILITY_SCORE_FIELD in row
        for row in rows
    )
    if has_probability_score_rows != (
        FEEDBACK_PROBABILITY_SCORE_FIELD in context
    ):
        raise ValueError("下一輪機率評分回饋來源不符")
    if (
        has_probability_score_rows
        and context[FEEDBACK_PROBABILITY_SCORE_FIELD]
        != _probability_score_feedback_aggregate(rows)
    ):
        raise ValueError("下一輪機率評分回饋彙總不符")
    if context.get("guardrails") != FEEDBACK_GUARDRAILS:
        raise ValueError("下一輪回饋防追號護欄不符")
    if context.get("honesty_note") != FEEDBACK_HONESTY_NOTE:
        raise ValueError("下一輪回饋誠實聲明不符")
