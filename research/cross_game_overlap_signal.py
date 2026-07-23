"""檢驗另一款遊戲最近已揭曉期的重複數能否改善完整 subset 機率。"""
from __future__ import annotations

from bisect import bisect_left
from collections import Counter
from datetime import date
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
from research.persistent_bias_signal import _safe_exp, _stable_floats


EXPERIMENT_ID = "cross-game-overlap-subset-probability-audit-v1"
PROTOCOL_FILE = "CROSS_GAME_OVERLAP_PROTOCOL.md"
MODEL_ID = "cross_game_overlap_dirichlet_null_1"
GAMES = (SUPER, LOTTO649)
OTHER_GAME = {SUPER: LOTTO649, LOTTO649: SUPER}
OVERLAP_VALUES = tuple(range(PICK_N + 1))
SOURCE_SIZE_VALUES = tuple(range(PICK_N + 1))
PRIOR_TOTAL_STRENGTH = 1.0
BOOTSTRAP_BLOCK = 13
BOOTSTRAP_SAMPLES = 2_000
RECENT_WINDOWS = (52, 104, 208)
E_VALUE_THRESHOLD = 60.0
FIELD_CLASSIFICATION = (
    {
        "field": "target period and lotteryDate",
        "availability": "pre_draw_schedule",
        "use": "identity_chronology_and_strict_prior_join",
    },
    {
        "field": "strictly earlier other-game drawNumberSize[:6]",
        "availability": "post_source_draw_then_pre_target_draw",
        "use": "only_conditional_feature",
    },
    {
        "field": "same-date other-game drawNumberSize[:6]",
        "availability": "not_proven_before_target_draw",
        "use": "excluded_use_latest_strictly_earlier_source",
    },
    {
        "field": "current target drawNumberSize[:6]",
        "availability": "post_draw",
        "use": "proper_score_target_then_state_update",
    },
    {
        "field": "draw_order_second_zone_bonus_sales_prizes",
        "availability": "excluded_or_post_draw",
        "use": "excluded",
    },
)
PROTOCOL_CONFIG = {
    "games": list(GAMES),
    "other_game": dict(OTHER_GAME),
    "models": ["uniform", MODEL_ID],
    "pairing": {
        "source_rule": "latest_other_game_date_strictly_before_target_date",
        "same_date_source": "excluded",
        "missing_source": "exact_uniform_and_no_state_update",
        "source_reuse": "allowed_when_it_was_latest_at_each_target",
    },
    "overlap_model": {
        "state": (
            "separate_cumulative_overlap_counts_by_"
            "eligible_source_size_m_0_through_6"
        ),
        "statistic": "K_size_of_target_intersection_eligible_source_labels",
        "null_distribution": (
            "C(m,k)*C(N-m,6-k)/C(N,6)"
        ),
        "prior": "dirichlet_centered_on_exact_stratum_null",
        "prior_total_strength": PRIOR_TOTAL_STRENGTH,
        "subset_probability": (
            "predictive_overlap_probability_divided_by_"
            "C(m,k)*C(N-m,6-k)"
        ),
        "window": "expanding_all_prior_paired_targets_with_same_m",
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


def overlap_stratum_size(
    pool: int,
    eligible_source_size: int,
    overlap: int,
) -> int:
    if (
        not isinstance(pool, int)
        or pool < PICK_N
        or eligible_source_size not in SOURCE_SIZE_VALUES
        or overlap not in OVERLAP_VALUES
    ):
        raise ValueError("跨遊戲 overlap 分層參數不合法")
    if overlap > eligible_source_size:
        return 0
    remaining = PICK_N - overlap
    if remaining > pool - eligible_source_size:
        return 0
    return math.comb(eligible_source_size, overlap) * math.comb(
        pool - eligible_source_size,
        remaining,
    )


def null_overlap_distribution(
    pool: int,
    eligible_source_size: int,
) -> list[float]:
    if (
        not isinstance(pool, int)
        or pool < PICK_N
        or eligible_source_size not in SOURCE_SIZE_VALUES
        or eligible_source_size > pool
    ):
        raise ValueError("跨遊戲公平分布參數不合法")
    denominator = math.comb(pool, PICK_N)
    probabilities = [
        overlap_stratum_size(
            pool,
            eligible_source_size,
            overlap,
        )
        / denominator
        for overlap in OVERLAP_VALUES
    ]
    if (
        any(not math.isfinite(value) or value < 0 for value in probabilities)
        or not math.isclose(
            math.fsum(probabilities),
            1.0,
            rel_tol=0.0,
            abs_tol=2e-15,
        )
    ):
        raise RuntimeError("跨遊戲公平 overlap 分布未正規化")
    return probabilities


def initial_cross_game_state(pool: int) -> dict:
    if not isinstance(pool, int) or pool < PICK_N:
        raise ValueError("目標球池不合法")
    return {
        "pool": pool,
        "counts_by_m": [
            [0] * len(OVERLAP_VALUES)
            for _ in SOURCE_SIZE_VALUES
        ],
        "transitions_by_m": [0] * len(SOURCE_SIZE_VALUES),
        "log_e_value": 0.0,
        "maximum_log_e_value": 0.0,
    }


def validate_cross_game_state(state: dict) -> None:
    if (
        not isinstance(state, dict)
        or set(state)
        != {
            "pool",
            "counts_by_m",
            "transitions_by_m",
            "log_e_value",
            "maximum_log_e_value",
        }
    ):
        raise ValueError("跨遊戲 overlap state 欄位不合法")
    pool = state["pool"]
    if not isinstance(pool, int) or pool < PICK_N:
        raise ValueError("跨遊戲 overlap state 球池不合法")
    counts_by_m = state["counts_by_m"]
    transitions_by_m = state["transitions_by_m"]
    if (
        not isinstance(counts_by_m, list)
        or len(counts_by_m) != len(SOURCE_SIZE_VALUES)
        or not isinstance(transitions_by_m, list)
        or len(transitions_by_m) != len(SOURCE_SIZE_VALUES)
    ):
        raise ValueError("跨遊戲 overlap state strata 不合法")
    for m in SOURCE_SIZE_VALUES:
        counts = counts_by_m[m]
        transitions = transitions_by_m[m]
        if (
            not isinstance(counts, list)
            or len(counts) != len(OVERLAP_VALUES)
            or any(
                not isinstance(value, int) or value < 0
                for value in counts
            )
            or not isinstance(transitions, int)
            or transitions < 0
            or sum(counts) != transitions
            or any(
                counts[k] != 0
                for k in OVERLAP_VALUES
                if overlap_stratum_size(pool, m, k) == 0
            )
        ):
            raise ValueError("跨遊戲 overlap state 計數不合法")
    log_e_value = state["log_e_value"]
    maximum_log_e_value = state["maximum_log_e_value"]
    if (
        not isinstance(log_e_value, (int, float))
        or isinstance(log_e_value, bool)
        or not math.isfinite(log_e_value)
        or not isinstance(maximum_log_e_value, (int, float))
        or isinstance(maximum_log_e_value, bool)
        or not math.isfinite(maximum_log_e_value)
        or maximum_log_e_value < 0
        or maximum_log_e_value < log_e_value
    ):
        raise ValueError("跨遊戲 overlap e-value state 不合法")


def predictive_overlap_distribution(
    state: dict,
    eligible_source_size: int,
) -> list[float]:
    validate_cross_game_state(state)
    if eligible_source_size not in SOURCE_SIZE_VALUES:
        raise ValueError("來源共享標籤數 m 不合法")
    null = null_overlap_distribution(
        state["pool"],
        eligible_source_size,
    )
    counts = state["counts_by_m"][eligible_source_size]
    transitions = state["transitions_by_m"][eligible_source_size]
    denominator = transitions + PRIOR_TOTAL_STRENGTH
    predictive = [
        (counts[k] + null[k] * PRIOR_TOTAL_STRENGTH)
        / denominator
        for k in OVERLAP_VALUES
    ]
    if (
        any(not math.isfinite(value) or value < 0 for value in predictive)
        or not math.isclose(
            math.fsum(predictive),
            1.0,
            rel_tol=0.0,
            abs_tol=2e-15,
        )
    ):
        raise RuntimeError("跨遊戲 predictive overlap 未正規化")
    return predictive


def eligible_source_labels(
    source_numbers: tuple[int, ...] | list[int],
    *,
    source_pool: int,
    target_pool: int,
) -> tuple[int, ...]:
    source = _validate_numbers(source_numbers, pool=source_pool)
    return tuple(number for number in source if number <= target_pool)


def cross_game_subset_probability(
    target_numbers: tuple[int, ...] | list[int],
    source_numbers: tuple[int, ...] | list[int],
    state: dict,
    *,
    source_pool: int,
) -> float:
    """用 update 前 state 計算目標完整六號集合機率。"""
    validate_cross_game_state(state)
    pool = state["pool"]
    target = _validate_numbers(target_numbers, pool=pool)
    eligible = eligible_source_labels(
        source_numbers,
        source_pool=source_pool,
        target_pool=pool,
    )
    m = len(eligible)
    overlap = len(set(target) & set(eligible))
    predictive = predictive_overlap_distribution(state, m)
    stratum_size = overlap_stratum_size(pool, m, overlap)
    if stratum_size <= 0:
        raise RuntimeError("跨遊戲目標落在不可能 overlap strata")
    probability = predictive[overlap] / stratum_size
    if not math.isfinite(probability) or not 0 < probability <= 1:
        raise RuntimeError("跨遊戲完整 subset 機率不合法")
    return probability


def forecast_then_update(
    state: dict,
    target_numbers: tuple[int, ...] | list[int],
    source_numbers: tuple[int, ...] | list[int] | None,
    *,
    source_pool: int,
) -> dict:
    """先用 state 評分，揭曉後才更新相同 m strata。"""
    validate_cross_game_state(state)
    pool = state["pool"]
    target = _validate_numbers(target_numbers, pool=pool)
    prior_log_e_value = float(state["log_e_value"])
    if source_numbers is None:
        return {
            "m": None,
            "overlap": None,
            "predictive": None,
            "likelihood_ratio": 1.0,
            "regret": 0.0,
            "prior_log_e_value": prior_log_e_value,
        }

    eligible = eligible_source_labels(
        source_numbers,
        source_pool=source_pool,
        target_pool=pool,
    )
    m = len(eligible)
    overlap = len(set(target) & set(eligible))
    predictive = predictive_overlap_distribution(state, m)
    null = null_overlap_distribution(pool, m)
    if null[overlap] <= 0:
        raise RuntimeError("實際 overlap 的公平機率必須為正")
    likelihood_ratio = predictive[overlap] / null[overlap]
    if (
        not math.isfinite(likelihood_ratio)
        or likelihood_ratio <= 0
    ):
        raise RuntimeError("跨遊戲 likelihood ratio 不合法")
    regret = -math.log(likelihood_ratio)

    state["counts_by_m"][m][overlap] += 1
    state["transitions_by_m"][m] += 1
    state["log_e_value"] += math.log(likelihood_ratio)
    state["maximum_log_e_value"] = max(
        state["maximum_log_e_value"],
        state["log_e_value"],
    )
    validate_cross_game_state(state)
    return {
        "m": m,
        "overlap": overlap,
        "predictive": predictive,
        "likelihood_ratio": likelihood_ratio,
        "regret": regret,
        "prior_log_e_value": prior_log_e_value,
    }


def _validate_chronological_rows(
    game: str,
    rows: list[dict],
) -> None:
    if game not in GAMES or not isinstance(rows, list) or not rows:
        raise ValueError("跨遊戲配對 rows 不合法")
    previous_date = None
    periods = set()
    for row in rows:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("date"), str)
            or "period" not in row
            or "numbers" not in row
            or (
                previous_date is not None
                and row["date"] <= previous_date
            )
        ):
            raise ValueError("跨遊戲 rows 必須按日期嚴格遞增")
        try:
            date.fromisoformat(row["date"])
        except ValueError as exc:
            raise ValueError("跨遊戲 row 日期不合法") from exc
        period = int(row["period"])
        if period in periods:
            raise ValueError("跨遊戲 row 期別重複")
        periods.add(period)
        _validate_numbers(row["numbers"], pool=POOL[game])
        previous_date = row["date"]


def build_cross_game_pairs(
    target_game: str,
    target_rows: list[dict],
    source_rows: list[dict],
) -> tuple[list[dict], dict]:
    """依日期嚴格小於目標日的規則建立當時可用來源。"""
    if target_game not in GAMES:
        raise ValueError("目標遊戲不合法")
    source_game = OTHER_GAME[target_game]
    _validate_chronological_rows(target_game, target_rows)
    _validate_chronological_rows(source_game, source_rows)
    source_dates = [row["date"] for row in source_rows]
    source_date_set = set(source_dates)
    pairs = []
    mapping_trace = []
    lag_days = Counter()
    source_usage = Counter()
    same_date_ignored = 0
    missing = 0

    for target in target_rows:
        target_date = target["date"]
        same_date = target_date in source_date_set
        same_date_ignored += int(same_date)
        source_index = bisect_left(source_dates, target_date) - 1
        source = source_rows[source_index] if source_index >= 0 else None
        if source is None:
            missing += 1
            lag = None
            source_key = None
        else:
            lag = (
                date.fromisoformat(target_date)
                - date.fromisoformat(source["date"])
            ).days
            if lag <= 0:
                raise RuntimeError("跨遊戲來源日期未嚴格早於目標")
            lag_days[str(lag)] += 1
            source_key = f"{source['date']}|{int(source['period'])}"
            source_usage[source_key] += 1
        pair = {
            "target_date": target_date,
            "target_period": int(target["period"]),
            "target_numbers": list(
                _validate_numbers(
                    target["numbers"],
                    pool=POOL[target_game],
                )
            ),
            "source_date": source["date"] if source else None,
            "source_period": int(source["period"]) if source else None,
            "source_numbers": (
                list(
                    _validate_numbers(
                        source["numbers"],
                        pool=POOL[source_game],
                    )
                )
                if source
                else None
            ),
            "lag_days": lag,
            "same_date_source_ignored": same_date,
        }
        pairs.append(pair)
        mapping_trace.append(
            {
                key: pair[key]
                for key in (
                    "target_date",
                    "target_period",
                    "source_date",
                    "source_period",
                    "lag_days",
                    "same_date_source_ignored",
                )
            }
        )

    profile = {
        "target_game": target_game,
        "source_game": source_game,
        "targets": len(target_rows),
        "strict_prior_available": len(target_rows) - missing,
        "missing_source": missing,
        "same_date_source_ignored": same_date_ignored,
        "lag_days": dict(sorted(lag_days.items(), key=lambda item: int(item[0]))),
        "unique_sources_used": len(source_usage),
        "sources_reused": sum(value > 1 for value in source_usage.values()),
        "maximum_source_reuse": max(source_usage.values(), default=0),
        "mapping_hash": canonical_hash(mapping_trace),
    }
    return pairs, profile


def _mean(values: list[float]) -> float:
    if not values:
        raise ValueError("平均值輸入不得為空")
    return statistics.fmean(values)


def evaluate_cross_game_model(
    game: str,
    pairs: list[dict],
    *,
    pairing_profile: dict,
    bootstrap_samples: int = BOOTSTRAP_SAMPLES,
) -> dict:
    if (
        game not in GAMES
        or not isinstance(pairs, list)
        or len(pairs) < 2
        or not isinstance(bootstrap_samples, int)
        or bootstrap_samples < 100
    ):
        raise ValueError("跨遊戲模型輸入不合法")
    if pairing_profile.get("target_game") != game:
        raise ValueError("跨遊戲 pairing profile 不符")
    source_game = OTHER_GAME[game]
    state = initial_cross_game_state(POOL[game])
    regrets = []
    available_regrets = []
    missing_regrets = []
    score_trace = []
    maximum_normalization_error = 0.0
    previous_target_date = None

    for index, pair in enumerate(pairs):
        if (
            not isinstance(pair, dict)
            or pair.get("target_date") is None
            or (
                previous_target_date is not None
                and pair["target_date"] <= previous_target_date
            )
        ):
            raise ValueError("跨遊戲 pairs 未按目標日期嚴格遞增")
        source_numbers = pair.get("source_numbers")
        if source_numbers is None:
            if any(
                pair.get(field) is not None
                for field in ("source_date", "source_period", "lag_days")
            ):
                raise ValueError("無來源 pair 欄位不一致")
        else:
            if (
                not isinstance(pair.get("source_date"), str)
                or pair["source_date"] >= pair["target_date"]
                or not isinstance(pair.get("lag_days"), int)
                or pair["lag_days"] <= 0
            ):
                raise ValueError("來源 pair 時間邊界不合法")
        outcome = forecast_then_update(
            state,
            pair["target_numbers"],
            source_numbers,
            source_pool=POOL[source_game],
        )
        regret = outcome["regret"]
        regrets.append(regret)
        if source_numbers is None:
            if regret != 0.0:
                raise RuntimeError("無來源期 regret 必須為零")
            missing_regrets.append(regret)
        else:
            available_regrets.append(regret)
            normalization_error = abs(
                math.fsum(outcome["predictive"]) - 1.0
            )
            maximum_normalization_error = max(
                maximum_normalization_error,
                normalization_error,
            )
        score_trace.append(
            {
                "index": index,
                "target_period": int(pair["target_period"]),
                "source_period": pair["source_period"],
                "m": outcome["m"],
                "overlap": outcome["overlap"],
                "prior_log_e_value": outcome["prior_log_e_value"],
                "regret": regret,
            }
        )
        previous_target_date = pair["target_date"]

    if len(available_regrets) != pairing_profile["strict_prior_available"]:
        raise RuntimeError("跨遊戲可用配對數與 profile 不一致")
    ci_low, ci_high = block_bootstrap_ci(
        regrets,
        samples=bootstrap_samples,
        block=BOOTSTRAP_BLOCK,
        seed=f"{EXPERIMENT_ID}|{game}|proper-score-regret",
    )
    half = len(regrets) // 2
    recent = {
        str(window): _mean(regrets[-window:])
        for window in RECENT_WINDOWS
    }
    mean_regret = _mean(regrets)
    criteria = {
        "mean_regret_negative": mean_regret < 0,
        "bootstrap_upper_negative": ci_high < 0,
        "both_halves_nonpositive": (
            _mean(regrets[:half]) <= 0
            and _mean(regrets[half:]) <= 0
        ),
        "all_recent_windows_nonpositive": all(
            value <= 0 for value in recent.values()
        ),
        "final_e_value_at_least_60": (
            state["log_e_value"] >= math.log(E_VALUE_THRESHOLD)
        ),
    }
    state_snapshot = {
        "pool": state["pool"],
        "counts_by_m": state["counts_by_m"],
        "transitions_by_m": state["transitions_by_m"],
        "log_e_value": state["log_e_value"],
        "maximum_log_e_value": state["maximum_log_e_value"],
    }
    return {
        "game": game,
        "game_name": GAME_NAMES[game],
        "source_game": source_game,
        "source_game_name": GAME_NAMES[source_game],
        "model": MODEL_ID,
        "draws": len(pairs),
        "strict_prior_available": len(available_regrets),
        "missing_source_draws": len(missing_regrets),
        "first_date": pairs[0]["target_date"],
        "last_date": pairs[-1]["target_date"],
        "pairing_profile": pairing_profile,
        "m_strata_draws": {
            str(m): state["transitions_by_m"][m]
            for m in SOURCE_SIZE_VALUES
        },
        "final_overlap_counts_by_m": {
            str(m): list(state["counts_by_m"][m])
            for m in SOURCE_SIZE_VALUES
        },
        "mean_regret_nats": mean_regret,
        "available_mean_regret_nats": _mean(available_regrets),
        "mean_information_gain_nats": -mean_regret,
        "geometric_probability_ratio_vs_uniform": math.exp(
            -mean_regret
        ),
        "bootstrap_95_low": ci_low,
        "bootstrap_95_high": ci_high,
        "first_half_mean_regret": _mean(regrets[:half]),
        "second_half_mean_regret": _mean(regrets[half:]),
        "recent_mean_regret": recent,
        "better_than_uniform_rate": (
            sum(value < 0 for value in regrets) / len(regrets)
        ),
        "missing_source_max_abs_regret": max(
            (abs(value) for value in missing_regrets),
            default=0.0,
        ),
        "final_log_e_value": state["log_e_value"],
        "final_e_value": _safe_exp(state["log_e_value"]),
        "maximum_log_e_value": state["maximum_log_e_value"],
        "maximum_e_value": _safe_exp(
            state["maximum_log_e_value"]
        ),
        "maximum_normalization_error": maximum_normalization_error,
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
        raise ValueError("跨遊戲 overlap 診斷遊戲不完整")
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
        "frontier_v4_inclusion_required": True,
        "reason": (
            "兩款遊戲同時通過固定跨遊戲 overlap 完整 subset "
            "proper-score、穩定性與 e-value 門檻；仍只能另立"
            " future-only shadow。"
            if qualified
            else "至少一款遊戲未通過固定跨遊戲 overlap 完整 subset "
            "proper-score 門檻，不得新增 Agent 或 watcher 訊號。"
        ),
        "next_evidence": (
            "不論結果方向都加入 immutable frontier v4；若不合格，"
            "正式機率維持 uniform null-safe。"
        ),
    }


def run_cross_game_overlap_signal(
    *,
    base: Path,
    bootstrap_samples: int = BOOTSTRAP_SAMPLES,
) -> dict:
    base = Path(base).resolve()
    records_before = tree_sha256(base / "records")
    protocol_path = base / PROTOCOL_FILE
    if not protocol_path.exists():
        raise RuntimeError(f"缺少預註冊檔：{PROTOCOL_FILE}")

    rows_by_game = {}
    quality_by_game = {}
    for game in GAMES:
        rows, profile = load_and_profile_raw_game(game, base=base)
        rows_by_game[game] = rows
        quality_by_game[game] = profile
    pairs_by_game = {}
    pairing_profiles = {}
    for game in GAMES:
        pairs, profile = build_cross_game_pairs(
            game,
            rows_by_game[game],
            rows_by_game[OTHER_GAME[game]],
        )
        pairs_by_game[game] = pairs
        pairing_profiles[game] = profile
    diagnostics = {
        game: evaluate_cross_game_model(
            game,
            pairs_by_game[game],
            pairing_profile=pairing_profiles[game],
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
            "另一款遊戲最近已揭曉期的共享標籤重複數，能否提高"
            "下一期完整無序六號子集合機率？"
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
            "grain": "target_draw_with_latest_strictly_earlier_other_game_draw",
            "games": quality_by_game,
            "pairing_profiles": pairing_profiles,
            "raw_files_total": sum(
                quality_by_game[game]["files"] for game in GAMES
            ),
            "draws_total": sum(
                quality_by_game[game]["draws"] for game in GAMES
            ),
            "raw_snapshot_hashes": raw_hashes,
            "combined_raw_snapshot_hash": canonical_hash(raw_hashes),
            "lookahead_control": (
                "只用日期嚴格小於 target 的最新另一遊戲 reveal；"
                "同日來源忽略；target reveal 評分後才更新相同 m state。"
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
            "模型只檢查跨遊戲 overlap 個數，不識別特定球號或設備。",
            "同日來源因精確公開先後未證明而固定排除。",
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
            raise ValueError(f"跨遊戲 overlap 欄位非有限：{field}")


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
        raise ValueError("跨遊戲 overlap 結果 schema 不合法")
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
            raise ValueError(
                f"跨遊戲 overlap protocol 欄位不符：{key}"
            )
    if (
        protocol.get("protocol_hash") != PROTOCOL_HASH
        or protocol.get("protocol_file") != PROTOCOL_FILE
        or not _is_sha256(protocol.get("protocol_file_sha256"))
        or result.get("field_classification")
        != list(FIELD_CLASSIFICATION)
    ):
        raise ValueError("跨遊戲 overlap protocol 或欄位分類不符")

    quality = result["data_quality"]
    games_quality = quality.get("games", {})
    pairing_profiles = quality.get("pairing_profiles", {})
    if (
        quality.get("status") != "pass"
        or quality.get("grain")
        != "target_draw_with_latest_strictly_earlier_other_game_draw"
        or set(games_quality) != set(GAMES)
        or set(pairing_profiles) != set(GAMES)
        or set(quality.get("raw_snapshot_hashes", {})) != set(GAMES)
        or quality.get("raw_files_total")
        != sum(games_quality[game].get("files", -1) for game in GAMES)
        or quality.get("draws_total")
        != sum(games_quality[game].get("draws", -1) for game in GAMES)
        or not _is_sha256(
            quality.get("combined_raw_snapshot_hash")
        )
    ):
        raise ValueError("跨遊戲 overlap 資料品質摘要不合法")
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
                f"{game} 跨遊戲 overlap 資料品質不合法"
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
        raise ValueError("跨遊戲 overlap raw hash 關聯不一致")

    diagnostics = result["diagnostics"]
    if set(diagnostics) != set(GAMES):
        raise ValueError("跨遊戲 overlap diagnostics 不完整")
    finite_fields = (
        "mean_regret_nats",
        "available_mean_regret_nats",
        "mean_information_gain_nats",
        "geometric_probability_ratio_vs_uniform",
        "bootstrap_95_low",
        "bootstrap_95_high",
        "first_half_mean_regret",
        "second_half_mean_regret",
        "better_than_uniform_rate",
        "missing_source_max_abs_regret",
        "final_log_e_value",
        "final_e_value",
        "maximum_log_e_value",
        "maximum_e_value",
        "maximum_normalization_error",
    )
    for game in GAMES:
        row = diagnostics[game]
        pair = pairing_profiles[game]
        strata = row.get("m_strata_draws", {})
        counts_by_m = row.get("final_overlap_counts_by_m", {})
        if (
            row.get("game") != game
            or row.get("source_game") != OTHER_GAME[game]
            or row.get("model") != MODEL_ID
            or row.get("draws") != games_quality[game]["draws"]
            or row.get("first_date")
            != games_quality[game]["date_range"][0]
            or row.get("last_date")
            != games_quality[game]["date_range"][1]
            or row.get("pairing_profile") != pair
            or pair.get("target_game") != game
            or pair.get("source_game") != OTHER_GAME[game]
            or pair.get("targets") != row["draws"]
            or pair.get("strict_prior_available")
            != row.get("strict_prior_available")
            or pair.get("missing_source")
            != row.get("missing_source_draws")
            or pair["strict_prior_available"] + pair["missing_source"]
            != pair["targets"]
            or not _is_sha256(pair.get("mapping_hash"))
            or set(pair.get("lag_days", {})) == set()
            or sum(pair["lag_days"].values())
            != pair["strict_prior_available"]
            or not isinstance(pair.get("same_date_source_ignored"), int)
            or pair["same_date_source_ignored"] < 0
            or not isinstance(pair.get("unique_sources_used"), int)
            or not isinstance(pair.get("sources_reused"), int)
            or not isinstance(pair.get("maximum_source_reuse"), int)
            or set(strata) != {str(m) for m in SOURCE_SIZE_VALUES}
            or set(counts_by_m) != {str(m) for m in SOURCE_SIZE_VALUES}
            or sum(strata.values()) != row["strict_prior_available"]
            or row.get("missing_source_max_abs_regret") != 0.0
            or any(
                not isinstance(row.get(field), (int, float))
                or isinstance(row.get(field), bool)
                or not math.isfinite(float(row[field]))
                for field in finite_fields
            )
            or set(row.get("recent_mean_regret", {}))
            != {str(window) for window in RECENT_WINDOWS}
            or not _is_sha256(row.get("score_trace_hash"))
            or not _is_sha256(row.get("final_state_hash"))
        ):
            raise ValueError(
                f"{game} 跨遊戲 overlap 診斷欄位不合法"
            )
        state_counts = []
        transitions = []
        for m in SOURCE_SIZE_VALUES:
            count_row = counts_by_m[str(m)]
            transition = strata[str(m)]
            if (
                not isinstance(transition, int)
                or transition < 0
                or not isinstance(count_row, list)
                or len(count_row) != len(OVERLAP_VALUES)
                or any(
                    not isinstance(value, int) or value < 0
                    for value in count_row
                )
                or sum(count_row) != transition
                or any(
                    count_row[k] != 0
                    for k in OVERLAP_VALUES
                    if overlap_stratum_size(POOL[game], m, k) == 0
                )
            ):
                raise ValueError(
                    f"{game} 跨遊戲 overlap strata state 不合法"
                )
            state_counts.append(count_row)
            transitions.append(transition)
        state_snapshot = {
            "pool": POOL[game],
            "counts_by_m": state_counts,
            "transitions_by_m": transitions,
            "log_e_value": row["final_log_e_value"],
            "maximum_log_e_value": row["maximum_log_e_value"],
        }
        if row["final_state_hash"] != canonical_hash(
            _stable_floats(state_snapshot)
        ):
            raise ValueError(
                f"{game} 跨遊戲 overlap state hash 不一致"
            )
        if (
            not 0 <= row["better_than_uniform_rate"] <= 1
            or row["geometric_probability_ratio_vs_uniform"] <= 0
            or row["maximum_normalization_error"] > 2e-15
            or not math.isclose(
                row["mean_information_gain_nats"],
                -row["mean_regret_nats"],
                rel_tol=1e-12,
                abs_tol=1e-15,
            )
            or not math.isclose(
                row["geometric_probability_ratio_vs_uniform"],
                math.exp(-row["mean_regret_nats"]),
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
            or row["maximum_log_e_value"] < row["final_log_e_value"]
            or not math.isclose(
                row["maximum_e_value"],
                _safe_exp(row["maximum_log_e_value"]),
                rel_tol=1e-11,
                abs_tol=1e-15,
            )
        ):
            raise ValueError(
                f"{game} 跨遊戲 overlap 數值關聯不一致"
            )
        recent = row["recent_mean_regret"]
        criteria = {
            "mean_regret_negative": row["mean_regret_nats"] < 0,
            "bootstrap_upper_negative": row["bootstrap_95_high"] < 0,
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
                f"{game} 跨遊戲 overlap challenger 決策不一致"
            )

    if result.get("conclusion") != build_conclusion(diagnostics):
        raise ValueError("跨遊戲 overlap 結論不一致")
    integrity = result["records_integrity"]
    if (
        set(integrity)
        != {"before_sha256", "after_sha256", "unchanged"}
        or not _is_sha256(integrity.get("before_sha256"))
        or not _is_sha256(integrity.get("after_sha256"))
        or integrity.get("before_sha256")
        != integrity.get("after_sha256")
        or integrity.get("unchanged") is not True
    ):
        raise ValueError("跨遊戲 overlap records 完整性失敗")
    payload = dict(result)
    observed_hash = payload.pop("audit_hash", None)
    if (
        not _is_sha256(observed_hash)
        or observed_hash != canonical_hash(payload)
    ):
        raise ValueError("跨遊戲 overlap audit hash 不一致")
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
