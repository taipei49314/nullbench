"""檢驗開獎星期條件頻率能否改善完整無序六號子集合機率。

唯一候選對每個正常開獎星期維護獨立的累積球號次數。第 t 期先以截至
第 t-1 期的同星期 state 預測，揭曉後才更新。正常星期外加開直接使用
精確均勻分布，且不污染任何正常星期 state。
"""
from __future__ import annotations

from datetime import date
import hashlib
import json
import math
from pathlib import Path
import statistics

from engine.agent_loop import canonical_hash
from engine.games import (
    DRAW_WEEKDAYS,
    GAME_NAMES,
    LOTTO649,
    PICK_N,
    POOL,
    SUPER,
)
from research.agent_ablation import block_bootstrap_ci
from research.draw_order_signal import load_and_profile_raw_game
from research.gates import tree_sha256
from research.persistent_bias_signal import (
    _safe_exp,
    _stable_floats,
    _update_label_counts,
    initial_label_counts,
    persistent_subset_probability,
)


EXPERIMENT_ID = "calendar-weekday-subset-audit-v1"
PROTOCOL_FILE = "CALENDAR_REGIME_PROTOCOL.md"
MODEL_ID = "weekday_dirichlet_1_regular"
ALPHA = 1.0
BOOTSTRAP_BLOCK = 13
BOOTSTRAP_SAMPLES = 2_000
RECENT_WINDOWS = (52, 104, 208)
E_VALUE_THRESHOLD = 60.0
GAMES = (SUPER, LOTTO649)
REGULAR_WEEKDAYS = {
    game: tuple(int(value) for value in DRAW_WEEKDAYS[game])
    for game in GAMES
}
FIELD_CLASSIFICATION = (
    {
        "field": "period",
        "availability": "pre_draw_schedule",
        "use": "identity_and_chronology_only",
    },
    {
        "field": "lotteryDate",
        "availability": "pre_draw_schedule",
        "use": "target_weekday_and_chronology",
    },
    {
        "field": "past same-weekday drawNumberSize[:6]",
        "availability": "post_draw_then_historical",
        "use": "only_model_feature_for_later_same_weekday_targets",
    },
    {
        "field": "current drawNumberSize[:6]",
        "availability": "post_draw",
        "use": "proper_score_target_then_future_state_update",
    },
    {
        "field": "off_schedule_draws",
        "availability": "pre_draw_schedule",
        "use": "exact_uniform_forecast_and_no_state_update",
    },
    {
        "field": "draw_order_second_zone_bonus_sales_prizes",
        "availability": "excluded_or_post_draw",
        "use": "excluded",
    },
)
PROTOCOL_CONFIG = {
    "games": list(GAMES),
    "models": ["uniform", MODEL_ID],
    "calendar_model": {
        "regular_weekdays": {
            game: list(REGULAR_WEEKDAYS[game]) for game in GAMES
        },
        "prior": "laplace",
        "alpha": ALPHA,
        "state": "separate_cumulative_main_number_counts_by_weekday",
        "sampling": "shared_label_weighted_without_replacement",
        "subset_probability": (
            "exact_64_state_sum_over_all_6_factorial_orders"
        ),
        "off_schedule": "exact_uniform_and_no_state_update",
    },
    "score": (
        "negative_log_probability_of_complete_unordered_"
        "six_number_subset"
    ),
    "control": "exact_discrete_uniform",
    "bootstrap": {
        "kind": "circular_moving_block",
        "block_draws": BOOTSTRAP_BLOCK,
        "samples": BOOTSTRAP_SAMPLES,
        "interval": 0.95,
    },
    "recent_windows": list(RECENT_WINDOWS),
    "activation_e_threshold": E_VALUE_THRESHOLD,
    "numeric_canonicalization": "15_significant_decimal_digits",
    "historical_use": "descriptive_diagnostic_only",
    "promotion_evidence": "new_future_preregistered_scores_only",
}
PROTOCOL_HASH = canonical_hash(PROTOCOL_CONFIG)


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def initial_weekday_counts(
    pool: int,
    regular_weekdays: tuple[int, ...],
) -> dict[int, list[int]]:
    if (
        not regular_weekdays
        or len(set(regular_weekdays)) != len(regular_weekdays)
        or any(
            not isinstance(weekday, int) or not 0 <= weekday <= 6
            for weekday in regular_weekdays
        )
    ):
        raise ValueError("正常開獎星期不合法")
    return {
        weekday: initial_label_counts(pool)
        for weekday in regular_weekdays
    }


def weekday_subset_probability(
    target_numbers: tuple[int, ...] | list[int],
    counts_by_weekday: dict[int, list[int]],
    *,
    pool: int,
    weekday: int,
    regular_weekdays: tuple[int, ...],
) -> float:
    """用 forecast 前的同星期 state 計算完整 subset 機率。"""
    if (
        not isinstance(weekday, int)
        or not 0 <= weekday <= 6
        or set(counts_by_weekday) != set(regular_weekdays)
    ):
        raise ValueError("星期模型 state 不合法")
    target = tuple(int(value) for value in target_numbers)
    if (
        len(target) != PICK_N
        or len(set(target)) != PICK_N
        or any(not 1 <= value <= pool for value in target)
    ):
        raise ValueError("目標主號必須是合法六號集合")
    if weekday not in regular_weekdays:
        return 1.0 / math.comb(pool, PICK_N)
    return persistent_subset_probability(
        target,
        counts_by_weekday[weekday],
        pool=pool,
        alpha=ALPHA,
    )


def evaluate_calendar_model(
    game: str,
    rows: list[dict],
    *,
    bootstrap_samples: int = BOOTSTRAP_SAMPLES,
) -> dict:
    if game not in GAMES or len(rows) < 2:
        raise ValueError("calendar weekday 模型輸入不合法")
    if (
        not isinstance(bootstrap_samples, int)
        or bootstrap_samples < 20
    ):
        raise ValueError("bootstrap_samples 至少為 20")
    pool = POOL[game]
    regular_weekdays = REGULAR_WEEKDAYS[game]
    counts_by_weekday = initial_weekday_counts(
        pool,
        regular_weekdays,
    )
    draw_counts = {weekday: 0 for weekday in range(7)}
    regrets: list[float] = []
    off_schedule_regrets: list[float] = []
    log_e_value = 0.0
    maximum_log_e_value = 0.0
    uniform_probability = 1.0 / math.comb(pool, PICK_N)
    previous_date: str | None = None

    for row in rows:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("date"), str)
            or "numbers" not in row
            or (
                previous_date is not None
                and row["date"] <= previous_date
            )
        ):
            raise ValueError(
                "calendar weekday 資料必須按日期嚴格遞增"
            )
        try:
            parsed_date = date.fromisoformat(row["date"])
        except ValueError as exc:
            raise ValueError("calendar weekday 日期不合法") from exc
        previous_date = row["date"]
        weekday = parsed_date.weekday()
        target = tuple(int(value) for value in row["numbers"])
        state_was_empty = (
            weekday in counts_by_weekday
            and sum(counts_by_weekday[weekday]) == 0
        )
        probability = weekday_subset_probability(
            target,
            counts_by_weekday,
            pool=pool,
            weekday=weekday,
            regular_weekdays=regular_weekdays,
        )
        if (
            (state_was_empty or weekday not in regular_weekdays)
            and not math.isclose(
                probability,
                uniform_probability,
                rel_tol=1e-12,
                abs_tol=1e-18,
            )
        ):
            raise RuntimeError(
                "零同星期歷史或正常星期外必須精確退回均勻"
            )
        regret = -math.log(probability) + math.log(
            uniform_probability
        )
        if not math.isfinite(regret):
            raise RuntimeError("calendar weekday regret 非有限")
        regrets.append(regret)
        draw_counts[weekday] += 1
        if weekday not in regular_weekdays:
            if abs(regret) > 1e-12:
                raise RuntimeError("正常星期外 regret 必須為零")
            off_schedule_regrets.append(regret)
        else:
            _update_label_counts(
                counts_by_weekday[weekday],
                target,
                pool=pool,
            )
        log_e_value -= regret
        maximum_log_e_value = max(
            maximum_log_e_value,
            log_e_value,
        )

    ci_low, ci_high = block_bootstrap_ci(
        regrets,
        samples=bootstrap_samples,
        block=BOOTSTRAP_BLOCK,
        seed=f"{EXPERIMENT_ID}|{game}|proper-score-regret",
    )
    half = len(regrets) // 2
    recent = {
        str(window): statistics.fmean(regrets[-window:])
        for window in RECENT_WINDOWS
    }
    criteria = {
        "mean_regret_negative": statistics.fmean(regrets) < 0,
        "bootstrap_upper_negative": ci_high < 0,
        "both_halves_nonpositive": (
            statistics.fmean(regrets[:half]) <= 0
            and statistics.fmean(regrets[half:]) <= 0
        ),
        "all_recent_windows_nonpositive": all(
            value <= 0 for value in recent.values()
        ),
        "final_e_value_at_least_60": (
            log_e_value >= math.log(E_VALUE_THRESHOLD)
        ),
    }
    final_counts = {
        str(weekday): counts_by_weekday[weekday][1:]
        for weekday in regular_weekdays
    }
    state_payload = {
        str(weekday): counts_by_weekday[weekday]
        for weekday in regular_weekdays
    }
    return {
        "game": game,
        "game_name": GAME_NAMES[game],
        "model": MODEL_ID,
        "draws": len(rows),
        "first_date": rows[0]["date"],
        "last_date": rows[-1]["date"],
        "regular_weekdays": list(regular_weekdays),
        "draws_by_weekday": {
            str(weekday): draw_counts[weekday]
            for weekday in range(7)
        },
        "regular_draws": sum(
            draw_counts[weekday] for weekday in regular_weekdays
        ),
        "off_schedule_draws": sum(
            draw_counts[weekday]
            for weekday in range(7)
            if weekday not in regular_weekdays
        ),
        "off_schedule_max_abs_regret": max(
            (abs(value) for value in off_schedule_regrets),
            default=0.0,
        ),
        "mean_regret_nats": statistics.fmean(regrets),
        "mean_information_gain_nats": -statistics.fmean(regrets),
        "bootstrap_95_low": ci_low,
        "bootstrap_95_high": ci_high,
        "first_half_mean_regret": statistics.fmean(
            regrets[:half]
        ),
        "second_half_mean_regret": statistics.fmean(
            regrets[half:]
        ),
        "recent_mean_regret": recent,
        "better_than_uniform_rate": (
            sum(value < 0 for value in regrets) / len(regrets)
        ),
        "final_log_e_value": log_e_value,
        "final_e_value": _safe_exp(log_e_value),
        "maximum_log_e_value": maximum_log_e_value,
        "maximum_e_value": _safe_exp(maximum_log_e_value),
        "score_trace_hash": canonical_hash(
            [_stable_floats(value) for value in regrets]
        ),
        "final_weekday_label_counts": final_counts,
        "final_state_hash": canonical_hash(state_payload),
        "future_challenger_criteria": criteria,
        "future_challenger_qualified": all(criteria.values()),
    }


def build_conclusion(diagnostics: dict[str, dict]) -> dict:
    if set(diagnostics) != set(GAMES):
        raise ValueError("calendar weekday 診斷遊戲不完整")
    qualified = all(
        diagnostics[game]["future_challenger_qualified"]
        for game in GAMES
    )
    return {
        "status": (
            "future_only_challenger_design_allowed"
            if qualified
            else "retain_existing_null_safe_protocol"
        ),
        "historical_promotion_eligible": False,
        "future_challenger_design_allowed": qualified,
        "watcher_integration_allowed": False,
        "selected_future_challenger": (
            MODEL_ID if qualified else None
        ),
        "probability_decision": (
            MODEL_ID if qualified else "uniform_null_safe"
        ),
        "reason": (
            "兩款遊戲同時通過固定星期條件完整 subset proper-score、"
            "穩定性與 e-value 門檻；仍只能另立 future-only shadow。"
            if qualified
            else "至少一款遊戲未通過星期條件完整 subset proper-score "
            "門檻；星期不得成為新 Agent 或 watcher 訊號。"
        ),
        "next_evidence": (
            "沒有合格候選時維持均勻 null-safe；30 號星期涵蓋率、月份"
            "切片或節日事後分組不能替代新的開獎前完整 subset score。"
        ),
    }


def run_calendar_regime_signal(
    *,
    base: Path,
    bootstrap_samples: int = BOOTSTRAP_SAMPLES,
) -> dict:
    """執行資料品質稽核與星期條件 prequential proper score。"""
    base = Path(base).resolve()
    records_before = tree_sha256(base / "records")
    protocol_path = base / PROTOCOL_FILE
    if not protocol_path.exists():
        raise RuntimeError(f"缺少預註冊檔：{PROTOCOL_FILE}")

    rows_by_game = {}
    quality_by_game = {}
    for game in GAMES:
        rows, profile = load_and_profile_raw_game(
            game,
            base=base,
        )
        rows_by_game[game] = rows
        quality_by_game[game] = profile
    diagnostics = {
        game: evaluate_calendar_model(
            game,
            rows_by_game[game],
            bootstrap_samples=bootstrap_samples,
        )
        for game in GAMES
    }
    raw_hashes = {
        game: quality_by_game[game]["raw_tree_sha256"]
        for game in GAMES
    }
    records_after = tree_sha256(base / "records")
    latest_date = max(
        diagnostics[game]["last_date"] for game in GAMES
    )
    protocol_snapshot = {
        **PROTOCOL_CONFIG,
        "bootstrap": {
            **PROTOCOL_CONFIG["bootstrap"],
            "samples": bootstrap_samples,
        },
    }
    result = {
        "schema_version": "1",
        "experiment_id": EXPERIMENT_ID,
        "generated_at": f"{latest_date}T23:59:59+08:00",
        "question": (
            "開獎前已知的正常星期，能否提高下一期完整無序六號"
            "子集合機率？"
        ),
        "protocol": {
            **protocol_snapshot,
            "protocol_hash": PROTOCOL_HASH,
            "protocol_file": PROTOCOL_FILE,
            "protocol_file_sha256": _file_sha256(protocol_path),
        },
        "field_classification": list(FIELD_CLASSIFICATION),
        "data_quality": {
            "status": "pass",
            "games": quality_by_game,
            "raw_files_total": sum(
                quality_by_game[game]["files"] for game in GAMES
            ),
            "draws_total": sum(
                quality_by_game[game]["draws"] for game in GAMES
            ),
            "raw_snapshot_hashes": raw_hashes,
            "combined_raw_snapshot_hash": canonical_hash(raw_hashes),
            "schedule_profile": {
                game: {
                    "regular_weekdays": diagnostics[game][
                        "regular_weekdays"
                    ],
                    "draws_by_weekday": diagnostics[game][
                        "draws_by_weekday"
                    ],
                    "regular_draws": diagnostics[game][
                        "regular_draws"
                    ],
                    "off_schedule_draws": diagnostics[game][
                        "off_schedule_draws"
                    ],
                }
                for game in GAMES
            },
            "lookahead_control": (
                "forecast_t 使用 update 前的同星期 state；"
                "正常星期外只評均勻且不更新正常星期 state。"
            ),
        },
        "diagnostics": diagnostics,
        "conclusion": build_conclusion(diagnostics),
        "records_integrity": {
            "before_sha256": records_before,
            "after_sha256": records_after,
            "unchanged": records_before == records_after,
        },
        "limitations": [
            "完整歷史已被其他研究使用，本結果只有描述性地位。",
            "只檢查固定星期條件，不搜尋月份、節日或日期交互作用。",
            "大樂透春節加開以均勻分布評分且不建立稀疏星期模型。",
            "固定 Laplace prior 是預註冊單一候選，不代表已知最佳。",
            "公平開獎下所有合法號碼組合理論等機率。",
            "純模擬，不構成購買或下注建議。",
        ],
    }
    result = _stable_floats(result)
    result["audit_hash"] = canonical_hash(result)
    validate_result(
        result,
        expected_bootstrap_samples=bootstrap_samples,
    )
    return result


def validate_result(
    result: dict,
    *,
    expected_bootstrap_samples: int = BOOTSTRAP_SAMPLES,
) -> dict:
    expected_keys = {
        "schema_version",
        "experiment_id",
        "generated_at",
        "question",
        "protocol",
        "field_classification",
        "data_quality",
        "diagnostics",
        "conclusion",
        "records_integrity",
        "limitations",
        "audit_hash",
    }
    if (
        not isinstance(result, dict)
        or set(result) != expected_keys
        or result.get("schema_version") != "1"
        or result.get("experiment_id") != EXPERIMENT_ID
    ):
        raise ValueError("calendar weekday 結果 schema 不合法")

    protocol = result["protocol"]
    expected_protocol = {
        **PROTOCOL_CONFIG,
        "bootstrap": {
            **PROTOCOL_CONFIG["bootstrap"],
            "samples": expected_bootstrap_samples,
        },
    }
    for key, value in expected_protocol.items():
        if protocol.get(key) != value:
            raise ValueError(
                f"calendar weekday protocol 欄位不符：{key}"
            )
    if (
        protocol.get("protocol_hash") != PROTOCOL_HASH
        or protocol.get("protocol_file") != PROTOCOL_FILE
        or not _is_sha256(protocol.get("protocol_file_sha256"))
        or result.get("field_classification")
        != list(FIELD_CLASSIFICATION)
    ):
        raise ValueError("calendar weekday protocol 或欄位分類不符")

    quality = result["data_quality"]
    games_quality = quality.get("games", {})
    schedule = quality.get("schedule_profile", {})
    if (
        quality.get("status") != "pass"
        or set(games_quality) != set(GAMES)
        or set(schedule) != set(GAMES)
        or set(quality.get("raw_snapshot_hashes", {}))
        != set(GAMES)
        or quality.get("raw_files_total")
        != sum(games_quality[game].get("files", -1) for game in GAMES)
        or quality.get("draws_total")
        != sum(games_quality[game].get("draws", -1) for game in GAMES)
        or not _is_sha256(
            quality.get("combined_raw_snapshot_hash")
        )
    ):
        raise ValueError("calendar weekday 資料品質摘要不合法")
    for game in GAMES:
        profile = games_quality[game]
        if (
            profile.get("status") != "pass"
            or profile.get("game") != game
            or profile.get("draws") != profile.get("unique_periods")
            or profile.get("draw_order_coverage_rate") != 1.0
            or any(
                profile.get(key) != 0
                for key in (
                    "required_nulls",
                    "duplicate_periods",
                    "duplicate_dates",
                    "invalid_number_rows",
                    "raw_ledger_mismatches",
                )
            )
            or not _is_sha256(profile.get("raw_tree_sha256"))
            or profile.get("ledger_verification", {}).get("lines")
            != profile.get("draws")
            or not _is_sha256(
                profile.get("ledger_verification", {}).get(
                    "last_event_hash"
                )
            )
            or not _is_sha256(
                profile.get("ledger_verification", {}).get(
                    "ledger_sha256"
                )
            )
        ):
            raise ValueError(
                f"{game} calendar weekday 資料品質不合法"
            )
    raw_hashes = {
        game: games_quality[game]["raw_tree_sha256"]
        for game in GAMES
    }
    if (
        quality["raw_snapshot_hashes"] != raw_hashes
        or quality["combined_raw_snapshot_hash"]
        != canonical_hash(raw_hashes)
    ):
        raise ValueError("calendar weekday raw hash 關聯不一致")

    diagnostics = result["diagnostics"]
    if set(diagnostics) != set(GAMES):
        raise ValueError("calendar weekday diagnostics 不完整")
    finite_fields = (
        "off_schedule_max_abs_regret",
        "mean_regret_nats",
        "mean_information_gain_nats",
        "bootstrap_95_low",
        "bootstrap_95_high",
        "first_half_mean_regret",
        "second_half_mean_regret",
        "better_than_uniform_rate",
        "final_log_e_value",
        "final_e_value",
        "maximum_log_e_value",
        "maximum_e_value",
    )
    for game in GAMES:
        row = diagnostics[game]
        draw_counts = row.get("draws_by_weekday", {})
        final_counts = row.get("final_weekday_label_counts", {})
        regular = REGULAR_WEEKDAYS[game]
        expected_schedule = {
            "regular_weekdays": list(regular),
            "draws_by_weekday": draw_counts,
            "regular_draws": row.get("regular_draws"),
            "off_schedule_draws": row.get("off_schedule_draws"),
        }
        if (
            row.get("game") != game
            or row.get("model") != MODEL_ID
            or row.get("draws") != games_quality[game]["draws"]
            or row.get("first_date")
            != games_quality[game]["date_range"][0]
            or row.get("last_date")
            != games_quality[game]["date_range"][1]
            or row.get("regular_weekdays") != list(regular)
            or set(draw_counts) != {str(value) for value in range(7)}
            or any(
                not isinstance(value, int) or value < 0
                for value in draw_counts.values()
            )
            or sum(draw_counts.values()) != row["draws"]
            or row.get("regular_draws")
            != sum(draw_counts[str(value)] for value in regular)
            or row.get("off_schedule_draws")
            != row["draws"] - row["regular_draws"]
            or row.get("off_schedule_max_abs_regret") != 0.0
            or schedule.get(game) != expected_schedule
            or any(
                not isinstance(row.get(field), (int, float))
                or isinstance(row.get(field), bool)
                or not math.isfinite(float(row[field]))
                for field in finite_fields
            )
            or set(row.get("recent_mean_regret", {}))
            != {str(window) for window in RECENT_WINDOWS}
            or set(final_counts) != {str(value) for value in regular}
            or not _is_sha256(row.get("score_trace_hash"))
        ):
            raise ValueError(
                f"{game} calendar weekday 診斷欄位不合法"
            )
        state_payload = {}
        for weekday in regular:
            counts = final_counts[str(weekday)]
            if (
                len(counts) != POOL[game]
                or any(
                    not isinstance(value, int) or value < 0
                    for value in counts
                )
                or sum(counts)
                != draw_counts[str(weekday)] * PICK_N
                or any(
                    value > draw_counts[str(weekday)]
                    for value in counts
                )
            ):
                raise ValueError(
                    f"{game} calendar weekday state 不合法"
                )
            state_payload[str(weekday)] = [0, *counts]
        if row.get("final_state_hash") != canonical_hash(state_payload):
            raise ValueError(
                f"{game} calendar weekday state hash 不一致"
            )
        if (
            not 0 <= row["better_than_uniform_rate"] <= 1
            or not math.isclose(
                row["mean_information_gain_nats"],
                -row["mean_regret_nats"],
                rel_tol=1e-12,
                abs_tol=1e-15,
            )
            or not math.isclose(
                row["final_log_e_value"],
                -row["mean_regret_nats"] * row["draws"],
                rel_tol=1e-11,
                abs_tol=1e-11,
            )
            or not math.isclose(
                row["final_e_value"],
                _safe_exp(row["final_log_e_value"]),
                rel_tol=1e-11,
                abs_tol=1e-300,
            )
            or row["maximum_log_e_value"] < 0
            or row["maximum_log_e_value"]
            < row["final_log_e_value"]
            or not math.isclose(
                row["maximum_e_value"],
                _safe_exp(row["maximum_log_e_value"]),
                rel_tol=1e-11,
                abs_tol=1e-15,
            )
        ):
            raise ValueError(
                f"{game} calendar weekday 數值關聯不一致"
            )
        recent = row["recent_mean_regret"]
        criteria = {
            "mean_regret_negative": row["mean_regret_nats"] < 0,
            "bootstrap_upper_negative": (
                row["bootstrap_95_high"] < 0
            ),
            "both_halves_nonpositive": (
                row["first_half_mean_regret"] <= 0
                and row["second_half_mean_regret"] <= 0
            ),
            "all_recent_windows_nonpositive": all(
                recent[str(window)] <= 0
                for window in RECENT_WINDOWS
            ),
            "final_e_value_at_least_60": (
                row["final_log_e_value"]
                >= math.log(E_VALUE_THRESHOLD)
            ),
        }
        if (
            row.get("future_challenger_criteria") != criteria
            or row.get("future_challenger_qualified")
            is not all(criteria.values())
        ):
            raise ValueError(
                f"{game} calendar weekday 決策不一致"
            )

    if result.get("conclusion") != build_conclusion(diagnostics):
        raise ValueError("calendar weekday 結論不一致")
    integrity = result["records_integrity"]
    if (
        set(integrity)
        != {"before_sha256", "after_sha256", "unchanged"}
        or not _is_sha256(integrity["before_sha256"])
        or not _is_sha256(integrity["after_sha256"])
        or integrity["unchanged"]
        is not (
            integrity["before_sha256"]
            == integrity["after_sha256"]
        )
        or not integrity["unchanged"]
    ):
        raise ValueError("calendar weekday records 完整性失敗")
    audit_payload = {
        key: value
        for key, value in result.items()
        if key != "audit_hash"
    }
    if (
        not _is_sha256(result.get("audit_hash"))
        or result["audit_hash"] != canonical_hash(audit_payload)
    ):
        raise ValueError("calendar weekday audit hash 不一致")
    return result


def write_result(result: dict, path: Path) -> Path:
    validate_result(result)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path
