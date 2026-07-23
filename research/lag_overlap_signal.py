"""檢驗相鄰期重複數能否改善完整無序六號子集合機率。

唯一候選只維護上一期與下一期主號交集大小的七格累積計數。每一期先以
截至上一期的 state 建立完整 subset 分布，讀取 reveal 後才更新 state。
歷史結果只有描述性地位，永遠不能直接升級正式號碼。
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import statistics

from engine.agent_loop import canonical_hash
from engine.games import GAME_NAMES, LOTTO649, PICK_N, POOL, SUPER
from research.agent_ablation import block_bootstrap_ci
from research.draw_order_signal import load_and_profile_raw_game
from research.gates import tree_sha256


EXPERIMENT_ID = "lag-overlap-subset-probability-audit-v1"
PROTOCOL_FILE = "LAG_OVERLAP_PROTOCOL.md"
MODEL_ID = "lag_overlap_dirichlet_null_1"
GAMES = (SUPER, LOTTO649)
OVERLAP_VALUES = tuple(range(PICK_N + 1))
PRIOR_TOTAL_STRENGTH = 1.0
BOOTSTRAP_BLOCK = 13
BOOTSTRAP_SAMPLES = 2_000
RECENT_WINDOWS = (52, 104, 208)
E_VALUE_THRESHOLD = 40.0
FIELD_CLASSIFICATION = (
    {
        "field": "period",
        "availability": "pre_draw_schedule",
        "use": "identity_and_chronology_only",
    },
    {
        "field": "lotteryDate",
        "availability": "pre_draw_schedule",
        "use": "identity_and_chronology_only",
    },
    {
        "field": "previous drawNumberSize[:6]",
        "availability": "post_draw_then_historical",
        "use": "only_feature_for_next_target",
    },
    {
        "field": "current drawNumberSize[:6]",
        "availability": "post_draw",
        "use": "proper_score_target_then_state_update",
    },
    {
        "field": "drawNumberAppear",
        "availability": "post_draw",
        "use": "excluded",
    },
    {
        "field": "second_zone_or_bonus",
        "availability": "post_draw",
        "use": "excluded",
    },
    {
        "field": "sellAmount",
        "availability": "timestamp_not_proven_pre_draw",
        "use": "excluded_fail_closed",
    },
    {
        "field": "totalAmount_and_prizes",
        "availability": "post_draw_publication",
        "use": "excluded",
    },
)
PROTOCOL_CONFIG = {
    "games": list(GAMES),
    "models": ["uniform", MODEL_ID, "null_safe_lag_overlap"],
    "overlap_model": {
        "state": "cumulative_adjacent_draw_overlap_counts_0_through_6",
        "null_distribution": (
            "C(6,k)*C(N-6,6-k)/C(N,6)"
        ),
        "prior": "dirichlet_centered_on_exact_null",
        "prior_total_strength": PRIOR_TOTAL_STRENGTH,
        "subset_probability": (
            "predictive_overlap_probability_divided_by_"
            "C(6,k)*C(N-6,6-k)"
        ),
        "window": "expanding_all_prior_transitions",
    },
    "score": (
        "candidate_negative_log_probability_minus_"
        "exact_uniform_negative_log_probability"
    ),
    "control": "exact_discrete_uniform",
    "bootstrap": {
        "kind": "circular_moving_block",
        "block_draws": BOOTSTRAP_BLOCK,
        "samples": BOOTSTRAP_SAMPLES,
        "interval": 0.95,
    },
    "recent_windows": list(RECENT_WINDOWS),
    "e_process": {
        "kind": "prequential_bayes_factor",
        "family_alpha": 0.05,
        "stream_alpha": 0.025,
        "activation_e_threshold": E_VALUE_THRESHOLD,
        "activation_timing": (
            "target_t_uses_only_e_value_through_reveal_t_minus_1"
        ),
    },
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


def _safe_exp(log_value: float) -> float:
    if not math.isfinite(log_value):
        raise ValueError("log e-value 必須為有限值")
    return math.exp(min(log_value, 700.0))


def _stable_floats(value):
    """固定跨 Python 版本可能出現的單一 ULP 差異。"""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("正式結果不得包含非有限浮點數")
        return float(format(value, ".15g"))
    if isinstance(value, list):
        return [_stable_floats(item) for item in value]
    if isinstance(value, tuple):
        return [_stable_floats(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _stable_floats(item)
            for key, item in value.items()
        }
    return value


def overlap_stratum_size(pool: int, overlap: int) -> int:
    if (
        not isinstance(pool, int)
        or pool < 2 * PICK_N
        or overlap not in OVERLAP_VALUES
    ):
        raise ValueError("重複數分層參數不合法")
    return math.comb(PICK_N, overlap) * math.comb(
        pool - PICK_N,
        PICK_N - overlap,
    )


def null_overlap_distribution(pool: int) -> list[float]:
    if not isinstance(pool, int) or pool < 2 * PICK_N:
        raise ValueError("球池大小不合法")
    denominator = math.comb(pool, PICK_N)
    probabilities = [
        overlap_stratum_size(pool, overlap) / denominator
        for overlap in OVERLAP_VALUES
    ]
    if (
        any(not math.isfinite(value) or value <= 0 for value in probabilities)
        or not math.isclose(
            math.fsum(probabilities),
            1.0,
            rel_tol=0.0,
            abs_tol=1e-15,
        )
    ):
        raise RuntimeError("公平重複數分布未正規化")
    return probabilities


def initial_overlap_state(pool: int) -> dict:
    null_probabilities = null_overlap_distribution(pool)
    return {
        "pool": pool,
        "counts": [0] * len(OVERLAP_VALUES),
        "transitions": 0,
        "previous_numbers": None,
        "log_e_value": 0.0,
        "maximum_log_e_value": 0.0,
        "null_probabilities": null_probabilities,
    }


def _validate_numbers(
    numbers: tuple[int, ...] | list[int],
    *,
    pool: int,
) -> tuple[int, ...]:
    values = tuple(sorted(int(value) for value in numbers))
    if (
        len(values) != PICK_N
        or len(set(values)) != PICK_N
        or any(not 1 <= value <= pool for value in values)
    ):
        raise ValueError("主號必須是合法六號集合")
    return values


def validate_overlap_state(state: dict) -> None:
    if not isinstance(state, dict):
        raise ValueError("重複數 state 不合法")
    expected_keys = {
        "pool",
        "counts",
        "transitions",
        "previous_numbers",
        "log_e_value",
        "maximum_log_e_value",
        "null_probabilities",
    }
    if set(state) != expected_keys:
        raise ValueError("重複數 state 欄位不合法")
    pool = state["pool"]
    expected_null = null_overlap_distribution(pool)
    counts = state["counts"]
    transitions = state["transitions"]
    if (
        not isinstance(counts, list)
        or len(counts) != len(OVERLAP_VALUES)
        or any(not isinstance(value, int) or value < 0 for value in counts)
        or not isinstance(transitions, int)
        or transitions < 0
        or sum(counts) != transitions
        or state["null_probabilities"] != expected_null
    ):
        raise ValueError("重複數 state 計數不合法")
    previous = state["previous_numbers"]
    if previous is None:
        if transitions != 0:
            raise ValueError("缺少上一期時不得有 transition")
    else:
        _validate_numbers(previous, pool=pool)
    log_e_value = state["log_e_value"]
    maximum_log_e_value = state["maximum_log_e_value"]
    if (
        not isinstance(log_e_value, (int, float))
        or isinstance(log_e_value, bool)
        or not math.isfinite(log_e_value)
        or not isinstance(maximum_log_e_value, (int, float))
        or isinstance(maximum_log_e_value, bool)
        or not math.isfinite(maximum_log_e_value)
        or maximum_log_e_value < max(0.0, log_e_value)
    ):
        raise ValueError("重複數 state e-value 不合法")


def predictive_overlap_distribution(state: dict) -> list[float]:
    validate_overlap_state(state)
    denominator = state["transitions"] + PRIOR_TOTAL_STRENGTH
    predictive = [
        (
            state["counts"][overlap]
            + state["null_probabilities"][overlap]
        )
        / denominator
        for overlap in OVERLAP_VALUES
    ]
    if (
        any(not math.isfinite(value) or value <= 0 for value in predictive)
        or not math.isclose(
            math.fsum(predictive),
            1.0,
            rel_tol=0.0,
            abs_tol=2e-15,
        )
    ):
        raise RuntimeError("候選重複數分布未正規化")
    return predictive


def overlap_subset_probability(
    numbers: tuple[int, ...] | list[int],
    *,
    previous_numbers: tuple[int, ...] | list[int] | None,
    predictive: list[float],
    pool: int,
) -> float:
    target = _validate_numbers(numbers, pool=pool)
    if (
        not isinstance(predictive, list)
        or len(predictive) != len(OVERLAP_VALUES)
        or any(not math.isfinite(value) or value <= 0 for value in predictive)
        or not math.isclose(
            math.fsum(predictive),
            1.0,
            rel_tol=0.0,
            abs_tol=2e-15,
        )
    ):
        raise ValueError("候選重複數分布不合法")
    if previous_numbers is None:
        return 1.0 / math.comb(pool, PICK_N)
    previous = _validate_numbers(previous_numbers, pool=pool)
    overlap = len(set(target) & set(previous))
    probability = predictive[overlap] / overlap_stratum_size(
        pool,
        overlap,
    )
    if not math.isfinite(probability) or not 0 < probability <= 1:
        raise RuntimeError("候選完整子集合機率不合法")
    return probability


def forecast_then_update(
    state: dict,
    numbers: tuple[int, ...] | list[int],
) -> dict:
    """以 update 前 state 評分一筆 reveal，再更新供下一期使用。"""
    validate_overlap_state(state)
    pool = state["pool"]
    target = _validate_numbers(numbers, pool=pool)
    predictive = predictive_overlap_distribution(state)
    previous = state["previous_numbers"]
    prior_log_e_value = float(state["log_e_value"])
    gate_active = prior_log_e_value >= math.log(E_VALUE_THRESHOLD)

    if previous is None:
        overlap = None
        likelihood_ratio = 1.0
        raw_regret = 0.0
    else:
        previous_values = _validate_numbers(previous, pool=pool)
        overlap = len(set(target) & set(previous_values))
        likelihood_ratio = (
            predictive[overlap]
            / state["null_probabilities"][overlap]
        )
        if (
            not math.isfinite(likelihood_ratio)
            or likelihood_ratio <= 0
        ):
            raise RuntimeError("候選 likelihood ratio 不合法")
        raw_regret = -math.log(likelihood_ratio)
        state["counts"][overlap] += 1
        state["transitions"] += 1
        state["log_e_value"] += math.log(likelihood_ratio)
        state["maximum_log_e_value"] = max(
            state["maximum_log_e_value"],
            state["log_e_value"],
        )

    safe_regret = raw_regret if gate_active else 0.0
    state["previous_numbers"] = target
    validate_overlap_state(state)
    return {
        "overlap": overlap,
        "predictive": predictive,
        "prior_log_e_value": prior_log_e_value,
        "gate_active": gate_active,
        "likelihood_ratio": likelihood_ratio,
        "raw_regret": raw_regret,
        "safe_regret": safe_regret,
    }


def _mean(values: list[float]) -> float:
    if not values:
        raise ValueError("平均值輸入不得為空")
    return statistics.fmean(values)


def evaluate_lag_overlap_model(
    game: str,
    rows: list[dict],
    *,
    bootstrap_samples: int = BOOTSTRAP_SAMPLES,
) -> dict:
    if (
        game not in GAMES
        or not isinstance(rows, list)
        or not rows
        or not isinstance(bootstrap_samples, int)
        or bootstrap_samples < 100
    ):
        raise ValueError("相鄰期重複模型輸入不合法")
    pool = POOL[game]
    state = initial_overlap_state(pool)
    raw_regrets: list[float] = []
    safe_regrets: list[float] = []
    score_trace = []
    maximum_normalization_error = 0.0
    gate_activation_count = 0

    previous_date = None
    previous_period = None
    for index, row in enumerate(rows):
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("date"), str)
            or "period" not in row
            or "numbers" not in row
            or (
                previous_date is not None
                and row["date"] <= previous_date
            )
            or (
                previous_period is not None
                and int(row["period"]) == previous_period
            )
        ):
            raise ValueError("相鄰期資料必須有唯一期間且按日期嚴格遞增")
        outcome = forecast_then_update(state, row["numbers"])
        normalization_error = abs(
            math.fsum(outcome["predictive"]) - 1.0
        )
        maximum_normalization_error = max(
            maximum_normalization_error,
            normalization_error,
        )
        raw_regrets.append(outcome["raw_regret"])
        safe_regrets.append(outcome["safe_regret"])
        gate_activation_count += int(outcome["gate_active"])
        score_trace.append(
            {
                "index": index,
                "overlap": outcome["overlap"],
                "prior_log_e_value": outcome["prior_log_e_value"],
                "gate_active": outcome["gate_active"],
                "raw_regret": outcome["raw_regret"],
                "safe_regret": outcome["safe_regret"],
            }
        )
        previous_date = row["date"]
        previous_period = int(row["period"])

    raw_ci_low, raw_ci_high = block_bootstrap_ci(
        raw_regrets,
        samples=bootstrap_samples,
        block=BOOTSTRAP_BLOCK,
        seed=f"{EXPERIMENT_ID}|{game}|raw-regret",
    )
    safe_ci_low, safe_ci_high = block_bootstrap_ci(
        safe_regrets,
        samples=bootstrap_samples,
        block=BOOTSTRAP_BLOCK,
        seed=f"{EXPERIMENT_ID}|{game}|safe-regret",
    )
    half = len(raw_regrets) // 2
    recent = {
        str(window): _mean(raw_regrets[-window:])
        for window in RECENT_WINDOWS
    }
    raw_mean = _mean(raw_regrets)
    safe_mean = _mean(safe_regrets)
    criteria = {
        "raw_mean_regret_negative": raw_mean < 0,
        "raw_bootstrap_upper_negative": raw_ci_high < 0,
        "both_halves_nonpositive": (
            _mean(raw_regrets[:half]) <= 0
            and _mean(raw_regrets[half:]) <= 0
        ),
        "all_recent_windows_nonpositive": all(
            value <= 0 for value in recent.values()
        ),
        "final_e_value_at_least_40": (
            state["log_e_value"] >= math.log(E_VALUE_THRESHOLD)
        ),
    }
    empirical = [
        count / state["transitions"]
        for count in state["counts"]
    ]
    final_predictive = predictive_overlap_distribution(state)
    state_snapshot = {
        "pool": pool,
        "counts": list(state["counts"]),
        "transitions": state["transitions"],
        "previous_numbers": list(state["previous_numbers"]),
        "log_e_value": state["log_e_value"],
        "maximum_log_e_value": state["maximum_log_e_value"],
    }
    return {
        "game": game,
        "game_name": GAME_NAMES[game],
        "model": MODEL_ID,
        "draws": len(rows),
        "transitions": state["transitions"],
        "first_date": rows[0]["date"],
        "last_date": rows[-1]["date"],
        "null_overlap_probabilities": list(
            state["null_probabilities"]
        ),
        "final_overlap_counts": list(state["counts"]),
        "empirical_overlap_probabilities": empirical,
        "final_predictive_overlap_probabilities": final_predictive,
        "raw_mean_regret_nats": raw_mean,
        "raw_mean_information_gain_nats": -raw_mean,
        "raw_geometric_probability_ratio_vs_uniform": math.exp(
            -raw_mean
        ),
        "raw_bootstrap_95_low": raw_ci_low,
        "raw_bootstrap_95_high": raw_ci_high,
        "safe_mean_regret_nats": safe_mean,
        "safe_mean_information_gain_nats": -safe_mean,
        "safe_geometric_probability_ratio_vs_uniform": math.exp(
            -safe_mean
        ),
        "safe_bootstrap_95_low": safe_ci_low,
        "safe_bootstrap_95_high": safe_ci_high,
        "first_half_raw_mean_regret": _mean(
            raw_regrets[:half]
        ),
        "second_half_raw_mean_regret": _mean(
            raw_regrets[half:]
        ),
        "recent_raw_mean_regret": recent,
        "raw_better_than_uniform_rate": (
            sum(value < 0 for value in raw_regrets)
            / len(raw_regrets)
        ),
        "gate_activation_count": gate_activation_count,
        "final_gate_active": (
            state["log_e_value"] >= math.log(E_VALUE_THRESHOLD)
        ),
        "final_log_e_value": state["log_e_value"],
        "final_e_value": _safe_exp(state["log_e_value"]),
        "maximum_log_e_value": state["maximum_log_e_value"],
        "maximum_e_value": _safe_exp(
            state["maximum_log_e_value"]
        ),
        "maximum_normalization_error": (
            maximum_normalization_error
        ),
        "score_trace_hash": canonical_hash(
            _stable_floats(score_trace)
        ),
        "final_state_hash": canonical_hash(
            _stable_floats(state_snapshot)
        ),
        "future_challenger_criteria": criteria,
        "future_challenger_qualified": all(criteria.values()),
    }


def build_conclusion(diagnostics: dict[str, dict]) -> dict:
    if set(diagnostics) != set(GAMES):
        raise ValueError("相鄰期重複模型診斷遊戲不完整")
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
        "frontier_v2_inclusion_required": True,
        "reason": (
            "兩款遊戲同時通過固定重複數完整 subset proper-score、"
            "穩定性與 e-value 門檻；仍只能另立 future-only shadow。"
            if qualified
            else "至少一款遊戲未通過固定重複數完整 subset "
            "proper-score 門檻，不得新增 Agent 或 watcher 訊號。"
        ),
        "next_evidence": (
            "不論結果方向都加入 immutable frontier v2；若不合格，"
            "正式機率維持既有 null-safe。"
        ),
    }


def run_lag_overlap_signal(
    *,
    base: Path,
    bootstrap_samples: int = BOOTSTRAP_SAMPLES,
) -> dict:
    """執行資料品質、無前視與完整 subset proper-score 稽核。"""
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
        game: evaluate_lag_overlap_model(
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
            "相鄰兩期主號重複個數能否提高下一期完整無序六號"
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
            "grain": "one_game_draw_complete_six_main_subset",
            "games": quality_by_game,
            "raw_files_total": sum(
                quality_by_game[game]["files"] for game in GAMES
            ),
            "draws_total": sum(
                quality_by_game[game]["draws"] for game in GAMES
            ),
            "raw_snapshot_hashes": raw_hashes,
            "combined_raw_snapshot_hash": canonical_hash(raw_hashes),
            "lookahead_control": (
                "forecast_t 只讀 reveal_t_minus_1 以前 overlap state；"
                "reveal_t 評分後才更新 forecast_t_plus_1。"
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
            "模型只檢查相鄰期重複個數，不識別特定球號或設備。",
            "公平且獨立開獎下所有合法六號集合仍理論等機率。",
            "只有新的開獎前完整 subset score 可作 promotion 證據。",
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


def _require_finite(record: dict, fields: tuple[str, ...]) -> None:
    for field in fields:
        value = record.get(field)
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
        ):
            raise ValueError(f"相鄰期重複欄位非有限：{field}")


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
        raise ValueError("相鄰期重複結果 schema 不合法")

    expected_protocol = {
        **PROTOCOL_CONFIG,
        "bootstrap": {
            **PROTOCOL_CONFIG["bootstrap"],
            "samples": expected_bootstrap_samples,
        },
    }
    protocol = result["protocol"]
    for key, value in expected_protocol.items():
        if protocol.get(key) != value:
            raise ValueError(f"相鄰期重複 protocol 欄位不符：{key}")
    if (
        protocol.get("protocol_hash") != PROTOCOL_HASH
        or protocol.get("protocol_file") != PROTOCOL_FILE
        or not _is_sha256(protocol.get("protocol_file_sha256"))
        or result.get("field_classification")
        != list(FIELD_CLASSIFICATION)
    ):
        raise ValueError("相鄰期重複 protocol 或欄位分類不符")

    quality = result["data_quality"]
    games_quality = quality.get("games", {})
    if (
        quality.get("status") != "pass"
        or quality.get("grain")
        != "one_game_draw_complete_six_main_subset"
        or set(games_quality) != set(GAMES)
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
        raise ValueError("相鄰期重複資料品質摘要不合法")
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
            raise ValueError(f"{game} 相鄰期重複資料品質不合法")
    profile_hashes = {
        game: games_quality[game]["raw_tree_sha256"]
        for game in GAMES
    }
    if (
        quality["raw_snapshot_hashes"] != profile_hashes
        or quality["combined_raw_snapshot_hash"]
        != canonical_hash(profile_hashes)
    ):
        raise ValueError("相鄰期重複 raw snapshot hash 不一致")

    diagnostics = result["diagnostics"]
    if set(diagnostics) != set(GAMES):
        raise ValueError("相鄰期重複 diagnostics 遊戲不完整")
    finite_fields = (
        "raw_mean_regret_nats",
        "raw_mean_information_gain_nats",
        "raw_geometric_probability_ratio_vs_uniform",
        "raw_bootstrap_95_low",
        "raw_bootstrap_95_high",
        "safe_mean_regret_nats",
        "safe_mean_information_gain_nats",
        "safe_geometric_probability_ratio_vs_uniform",
        "safe_bootstrap_95_low",
        "safe_bootstrap_95_high",
        "first_half_raw_mean_regret",
        "second_half_raw_mean_regret",
        "raw_better_than_uniform_rate",
        "final_log_e_value",
        "final_e_value",
        "maximum_log_e_value",
        "maximum_e_value",
        "maximum_normalization_error",
    )
    for game in GAMES:
        row = diagnostics[game]
        _require_finite(row, finite_fields)
        expected_row_keys = {
            "game",
            "game_name",
            "model",
            "draws",
            "transitions",
            "first_date",
            "last_date",
            "null_overlap_probabilities",
            "final_overlap_counts",
            "empirical_overlap_probabilities",
            "final_predictive_overlap_probabilities",
            *finite_fields,
            "recent_raw_mean_regret",
            "gate_activation_count",
            "final_gate_active",
            "score_trace_hash",
            "final_state_hash",
            "future_challenger_criteria",
            "future_challenger_qualified",
        }
        if (
            set(row) != expected_row_keys
            or row.get("game") != game
            or row.get("game_name") != GAME_NAMES[game]
            or row.get("model") != MODEL_ID
            or row.get("draws")
            != games_quality[game].get("draws")
            or row.get("transitions") != row.get("draws") - 1
            or row.get("first_date")
            != games_quality[game].get("date_range", [None, None])[0]
            or row.get("last_date")
            != games_quality[game].get("date_range", [None, None])[1]
            or not _is_sha256(row.get("score_trace_hash"))
            or not _is_sha256(row.get("final_state_hash"))
        ):
            raise ValueError(f"{game} 相鄰期重複摘要不合法")
        raw_expected_null = null_overlap_distribution(POOL[game])
        expected_null = _stable_floats(raw_expected_null)
        counts = row["final_overlap_counts"]
        empirical = row["empirical_overlap_probabilities"]
        predictive = row["final_predictive_overlap_probabilities"]
        if (
            row["null_overlap_probabilities"] != expected_null
            or not isinstance(counts, list)
            or len(counts) != len(OVERLAP_VALUES)
            or any(
                not isinstance(value, int) or value < 0
                for value in counts
            )
            or sum(counts) != row["transitions"]
            or not isinstance(empirical, list)
            or len(empirical) != len(OVERLAP_VALUES)
            or not isinstance(predictive, list)
            or len(predictive) != len(OVERLAP_VALUES)
        ):
            raise ValueError(f"{game} 重複數分布不合法")
        expected_empirical = _stable_floats(
            [
                count / row["transitions"]
                for count in counts
            ]
        )
        expected_predictive = _stable_floats(
            [
                (counts[index] + raw_expected_null[index])
                / (row["transitions"] + PRIOR_TOTAL_STRENGTH)
                for index in OVERLAP_VALUES
            ]
        )
        if (
            empirical != expected_empirical
            or predictive != expected_predictive
            or not math.isclose(
                math.fsum(predictive),
                1.0,
                rel_tol=0.0,
                abs_tol=2e-14,
            )
            or not 0 <= row["raw_better_than_uniform_rate"] <= 1
            or row["gate_activation_count"] < 0
            or row["gate_activation_count"] > row["draws"]
            or row["maximum_normalization_error"] > 2e-14
        ):
            raise ValueError(f"{game} 重複數衍生欄位不一致")
        if (
            row["raw_mean_information_gain_nats"]
            != _stable_floats(-row["raw_mean_regret_nats"])
            or row["safe_mean_information_gain_nats"]
            != _stable_floats(-row["safe_mean_regret_nats"])
            or row["raw_geometric_probability_ratio_vs_uniform"]
            != _stable_floats(
                math.exp(-row["raw_mean_regret_nats"])
            )
            or row["safe_geometric_probability_ratio_vs_uniform"]
            != _stable_floats(
                math.exp(-row["safe_mean_regret_nats"])
            )
            or not math.isclose(
                row["final_e_value"],
                _safe_exp(row["final_log_e_value"]),
                rel_tol=5e-13,
                abs_tol=1e-300,
            )
            or not math.isclose(
                row["maximum_e_value"],
                _safe_exp(row["maximum_log_e_value"]),
                rel_tol=5e-13,
                abs_tol=1e-300,
            )
            or row["maximum_log_e_value"]
            < max(0.0, row["final_log_e_value"])
        ):
            raise ValueError(f"{game} score／e-value 關聯不一致")
        recent = row["recent_raw_mean_regret"]
        if (
            set(recent) != {str(value) for value in RECENT_WINDOWS}
            or any(
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(value)
                for value in recent.values()
            )
        ):
            raise ValueError(f"{game} 最近窗口摘要不合法")
        expected_criteria = {
            "raw_mean_regret_negative": (
                row["raw_mean_regret_nats"] < 0
            ),
            "raw_bootstrap_upper_negative": (
                row["raw_bootstrap_95_high"] < 0
            ),
            "both_halves_nonpositive": (
                row["first_half_raw_mean_regret"] <= 0
                and row["second_half_raw_mean_regret"] <= 0
            ),
            "all_recent_windows_nonpositive": all(
                value <= 0 for value in recent.values()
            ),
            "final_e_value_at_least_40": (
                row["final_log_e_value"]
                >= math.log(E_VALUE_THRESHOLD)
            ),
        }
        if (
            row["future_challenger_criteria"] != expected_criteria
            or row["future_challenger_qualified"]
            is not all(expected_criteria.values())
            or row["final_gate_active"]
            is not expected_criteria["final_e_value_at_least_40"]
        ):
            raise ValueError(f"{game} 升級門檻不一致")

    expected_conclusion = build_conclusion(diagnostics)
    if result["conclusion"] != expected_conclusion:
        raise ValueError("相鄰期重複結論不一致")
    integrity = result["records_integrity"]
    if (
        set(integrity)
        != {"before_sha256", "after_sha256", "unchanged"}
        or not _is_sha256(integrity.get("before_sha256"))
        or not _is_sha256(integrity.get("after_sha256"))
        or integrity.get("unchanged")
        is not (
            integrity.get("before_sha256")
            == integrity.get("after_sha256")
        )
        or integrity.get("unchanged") is not True
    ):
        raise ValueError("相鄰期重複 records 完整性失敗")
    if (
        not isinstance(result.get("limitations"), list)
        or len(result["limitations"]) < 4
        or not _is_sha256(result.get("audit_hash"))
    ):
        raise ValueError("相鄰期重複限制或 audit hash 不合法")
    payload = dict(result)
    observed_audit_hash = payload.pop("audit_hash")
    if observed_audit_hash != canonical_hash(payload):
        raise ValueError("相鄰期重複 audit hash 不一致")
    return result


def write_result(result: dict, path: Path) -> Path:
    validate_result(result)
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output
