"""檢驗持續球號偏差能否改善完整無序六號子集合機率。

唯一候選對每個球號維護截至上一期的累積出現次數，使用固定 Laplace
prior，並以精確無放回生成模型評分完整六號集合。完整歷史只作描述性
診斷，永遠不能直接升級正式號碼。
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


EXPERIMENT_ID = "persistent-label-bias-subset-audit-v1"
PROTOCOL_FILE = "PERSISTENT_BIAS_PROTOCOL.md"
MODEL_ID = "persistent_dirichlet_1"
ALPHA = 1.0
BOOTSTRAP_BLOCK = 13
BOOTSTRAP_SAMPLES = 2_000
RECENT_WINDOWS = (52, 104, 208)
E_VALUE_THRESHOLD = 60.0
GAMES = (SUPER, LOTTO649)
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
        "field": "past drawNumberSize[:6]",
        "availability": "post_draw_then_historical",
        "use": "only_model_feature_for_later_targets",
    },
    {
        "field": "current drawNumberSize[:6]",
        "availability": "post_draw",
        "use": "proper_score_target_only",
    },
    {
        "field": "drawNumberAppear",
        "availability": "post_draw",
        "use": "excluded_order_not_required",
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
    "models": ["uniform", MODEL_ID],
    "label_model": {
        "prior": "laplace",
        "alpha": ALPHA,
        "state": "cumulative_main_number_occurrence_counts",
        "sampling": "shared_label_weighted_without_replacement",
        "subset_probability": (
            "exact_64_state_sum_over_all_6_factorial_orders"
        ),
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


def _safe_exp(log_value: float) -> float:
    if not math.isfinite(log_value):
        raise ValueError("log e-value 必須為有限值")
    return math.exp(min(log_value, 700.0))


def _stable_floats(value):
    """把跨 Python 版本的單一 ULP 差異固定為相同 JSON 數值。"""
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


def initial_label_counts(pool: int) -> list[int]:
    if not isinstance(pool, int) or pool < PICK_N:
        raise ValueError("球池大小不合法")
    return [0] * (pool + 1)


def _validate_label_counts(
    counts: list[int],
    *,
    pool: int,
) -> None:
    if (
        not isinstance(counts, list)
        or len(counts) != pool + 1
        or counts[0] != 0
        or any(
            not isinstance(value, int) or value < 0
            for value in counts
        )
    ):
        raise ValueError("球號累積計數 state 不合法")
    total = sum(counts)
    draws = total // PICK_N
    if (
        total % PICK_N != 0
        or any(value > draws for value in counts)
    ):
        raise ValueError("球號累積計數 state 不合法")


def persistent_subset_probability(
    target_numbers: tuple[int, ...] | list[int],
    counts: list[int],
    *,
    pool: int,
    alpha: float = ALPHA,
) -> float:
    """精確加總目標六號集合的全部無放回抽出順序機率。"""
    target = tuple(int(value) for value in target_numbers)
    if (
        len(target) != PICK_N
        or len(set(target)) != PICK_N
        or any(not 1 <= value <= pool for value in target)
    ):
        raise ValueError("目標主號必須是合法六號集合")
    if not math.isfinite(alpha) or alpha <= 0:
        raise ValueError("Dirichlet alpha 必須為有限正值")
    _validate_label_counts(counts, pool=pool)

    weights = [alpha + counts[number] for number in target]
    total_weight = pool * alpha + sum(counts)
    full_mask = (1 << PICK_N) - 1
    probabilities = {0: 1.0}
    selected_weights = [0.0] * (1 << PICK_N)
    for mask in range(1, 1 << PICK_N):
        least_bit = mask & -mask
        index = least_bit.bit_length() - 1
        selected_weights[mask] = (
            selected_weights[mask ^ least_bit] + weights[index]
        )

    for _position in range(PICK_N):
        next_probabilities: dict[int, float] = {}
        for mask, state_probability in probabilities.items():
            denominator = total_weight - selected_weights[mask]
            if denominator <= 0:
                raise ValueError("球號模型條件分母不合法")
            for index, weight in enumerate(weights):
                bit = 1 << index
                if mask & bit:
                    continue
                next_mask = mask | bit
                transition = weight / denominator
                next_probabilities[next_mask] = (
                    next_probabilities.get(next_mask, 0.0)
                    + state_probability * transition
                )
        probabilities = next_probabilities

    probability = probabilities.get(full_mask, 0.0)
    if (
        not math.isfinite(probability)
        or not 0 < probability <= 1
    ):
        raise ValueError("球號模型子集合機率不合法")
    return probability


def _update_label_counts(
    counts: list[int],
    numbers: tuple[int, ...] | list[int],
    *,
    pool: int,
) -> None:
    values = tuple(int(value) for value in numbers)
    if (
        len(values) != PICK_N
        or len(set(values)) != PICK_N
        or any(not 1 <= value <= pool for value in values)
    ):
        raise ValueError("揭曉主號不合法")
    _validate_label_counts(counts, pool=pool)
    for number in values:
        counts[number] += 1


def evaluate_persistent_model(
    game: str,
    rows: list[dict],
    *,
    bootstrap_samples: int = BOOTSTRAP_SAMPLES,
) -> dict:
    if game not in GAMES or not rows:
        raise ValueError("持續球號模型輸入不合法")
    pool = POOL[game]
    counts = initial_label_counts(pool)
    regrets: list[float] = []
    log_e_value = 0.0
    maximum_log_e_value = 0.0
    uniform_probability = 1.0 / math.comb(pool, PICK_N)

    for index, row in enumerate(rows):
        if (
            not isinstance(row, dict)
            or "date" not in row
            or "numbers" not in row
            or (
                index
                and row["date"] <= rows[index - 1]["date"]
            )
        ):
            raise ValueError("持續球號資料必須按日期嚴格遞增")
        target = tuple(int(value) for value in row["numbers"])
        probability = persistent_subset_probability(
            target,
            counts,
            pool=pool,
            alpha=ALPHA,
        )
        if index == 0 and not math.isclose(
            probability,
            uniform_probability,
            rel_tol=1e-12,
            abs_tol=1e-18,
        ):
            raise RuntimeError("零歷史球號模型必須精確退回均勻")
        regret = -math.log(probability) + math.log(
            uniform_probability
        )
        if not math.isfinite(regret):
            raise RuntimeError("持續球號模型 regret 非有限")
        regrets.append(regret)
        log_e_value -= regret
        maximum_log_e_value = max(
            maximum_log_e_value,
            log_e_value,
        )
        _update_label_counts(
            counts,
            target,
            pool=pool,
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
    return {
        "game": game,
        "game_name": GAME_NAMES[game],
        "model": MODEL_ID,
        "draws": len(rows),
        "first_date": rows[0]["date"],
        "last_date": rows[-1]["date"],
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
        "final_label_counts": counts[1:],
        "final_state_hash": canonical_hash(counts),
        "future_challenger_criteria": criteria,
        "future_challenger_qualified": all(criteria.values()),
    }


def build_conclusion(diagnostics: dict[str, dict]) -> dict:
    if set(diagnostics) != set(GAMES):
        raise ValueError("持續球號模型診斷遊戲不完整")
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
        "reason": (
            "兩款遊戲同時通過固定完整子集合 proper-score、穩定性與 "
            "e-value 門檻；仍只能另立 future-only shadow。"
            if qualified
            else "至少一款遊戲未通過固定完整子集合 proper-score 門檻，"
            "持續球號偏差不得成為新 Agent 或 watcher 訊號。"
        ),
        "next_evidence": (
            "沒有合格候選時維持現行 null-safe；歷史頻率排名或命中數"
            "不能替代新的開獎前完整 subset proper score。"
        ),
    }


def run_persistent_bias_signal(
    *,
    base: Path,
    bootstrap_samples: int = BOOTSTRAP_SAMPLES,
) -> dict:
    """執行完整品質稽核與 prequential subset proper score。"""
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
        game: evaluate_persistent_model(
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
            "過去累積球號頻率能否提高下一期完整無序六號"
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
            "lookahead_control": (
                "forecast_t 使用 update 前 label-count state；"
                "drawNumberSize_t 只更新 forecast_t_plus_1。"
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
            "模型只檢查跨期持續的主號標籤偏差，不檢查設備 metadata。",
            "固定 Laplace prior 不代表已知最佳，只是封存的單一候選。",
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
        raise ValueError("持續球號偏差結果 schema 不合法")

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
            raise ValueError(f"持續球號 protocol 欄位不符：{key}")
    if (
        protocol.get("protocol_hash") != PROTOCOL_HASH
        or protocol.get("protocol_file") != PROTOCOL_FILE
        or not _is_sha256(protocol.get("protocol_file_sha256"))
        or result.get("field_classification")
        != list(FIELD_CLASSIFICATION)
    ):
        raise ValueError("持續球號 protocol 或欄位分類不符")

    quality = result["data_quality"]
    games_quality = quality.get("games", {})
    if (
        quality.get("status") != "pass"
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
        raise ValueError("持續球號資料品質摘要不合法")
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
            or set(profile.get("ledger_verification", {}))
            != {"lines", "last_event_hash", "ledger_sha256"}
            or profile["ledger_verification"].get("lines")
            != profile.get("draws")
            or not _is_sha256(
                profile["ledger_verification"].get(
                    "last_event_hash"
                )
            )
            or not _is_sha256(
                profile["ledger_verification"].get(
                    "ledger_sha256"
                )
            )
        ):
            raise ValueError(f"{game} 持續球號資料品質不合法")
    profile_raw_hashes = {
        game: games_quality[game]["raw_tree_sha256"]
        for game in GAMES
    }
    if (
        quality["raw_snapshot_hashes"] != profile_raw_hashes
        or quality["combined_raw_snapshot_hash"]
        != canonical_hash(profile_raw_hashes)
    ):
        raise ValueError("持續球號 raw snapshot hash 關聯不一致")

    diagnostics = result["diagnostics"]
    if set(diagnostics) != set(GAMES):
        raise ValueError("持續球號 diagnostics 遊戲不完整")
    finite_fields = (
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
        counts = row.get("final_label_counts", [])
        if (
            row.get("game") != game
            or row.get("model") != MODEL_ID
            or row.get("draws") != games_quality[game]["draws"]
            or row.get("first_date")
            != games_quality[game]["date_range"][0]
            or row.get("last_date")
            != games_quality[game]["date_range"][1]
            or any(
                not isinstance(row.get(field), (int, float))
                or isinstance(row.get(field), bool)
                or not math.isfinite(float(row[field]))
                for field in finite_fields
            )
            or set(row.get("recent_mean_regret", {}))
            != {str(window) for window in RECENT_WINDOWS}
            or any(
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(float(value))
                for value in row.get(
                    "recent_mean_regret",
                    {},
                ).values()
            )
            or len(counts) != POOL[game]
            or any(
                not isinstance(value, int) or value < 0
                for value in counts
            )
            or sum(counts) != row["draws"] * PICK_N
            or any(value > row["draws"] for value in counts)
            or row.get("final_state_hash")
            != canonical_hash([0, *counts])
            or not _is_sha256(row.get("score_trace_hash"))
        ):
            raise ValueError(f"{game} 持續球號診斷欄位不合法")
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
            raise ValueError(f"{game} 持續球號數值關聯不一致")
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
            raise ValueError(f"{game} challenger 決策不一致")

    if result.get("conclusion") != build_conclusion(diagnostics):
        raise ValueError("持續球號結論不一致")
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
        raise ValueError("持續球號 records 完整性失敗")
    audit_payload = {
        key: value
        for key, value in result.items()
        if key != "audit_hash"
    }
    if (
        not _is_sha256(result.get("audit_hash"))
        or result["audit_hash"] != canonical_hash(audit_payload)
    ):
        raise ValueError("持續球號 audit hash 不一致")
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
