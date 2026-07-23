"""檢驗官方抽出順序能否改善完整無序六號子集合機率。

唯一候選是六個位置各自使用 Laplace prior 的累積 Dirichlet 模型。第 t 期
forecast 嚴格只使用第 t-1 期以前的 ``drawNumberAppear``；當期結果只更新
下一期。完整歷史僅供描述性診斷，永遠不能直接升級。
"""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import random
import statistics

from engine.agent_loop import canonical_hash, verify_replay
from engine.games import GAME_NAMES, LOTTO649, PICK_N, POOL, SPECIAL_POOL, SUPER
from engine.seeds import seed_int
from research.agent_ablation import block_bootstrap_ci
from research.gates import tree_sha256


EXPERIMENT_ID = "draw-order-subset-signal-audit-v1"
PROTOCOL_FILE = "DRAW_ORDER_SIGNAL_PROTOCOL.md"
MODEL_ID = "position_dirichlet_1"
ALPHA = 1.0
BOOTSTRAP_BLOCK = 13
BOOTSTRAP_SAMPLES = 2_000
PERMUTATION_SAMPLES = 2_000
RECENT_WINDOWS = (52, 104, 208)
E_VALUE_THRESHOLD = 40.0
GAMES = (SUPER, LOTTO649)
RESULT_KEYS = {
    SUPER: "superLotto638Res",
    LOTTO649: "lotto649Res",
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
        "use": "identity_and_chronology_only",
    },
    {
        "field": "drawNumberAppear[:6]",
        "availability": "post_draw",
        "use": "eligible_only_for_later_targets",
    },
    {
        "field": "drawNumberAppear[6]",
        "availability": "post_draw",
        "use": "excluded_not_new_for_main_subset",
    },
    {
        "field": "drawNumberSize",
        "availability": "post_draw",
        "use": "validation_target_only",
    },
    {
        "field": "sellAmount",
        "availability": "timestamp_not_proven_pre_draw",
        "use": "excluded_fail_closed",
    },
    {
        "field": "totalAmount",
        "availability": "post_draw_publication",
        "use": "excluded",
    },
    {
        "field": "*Assign",
        "availability": "post_draw",
        "use": "excluded",
    },
    {
        "field": "redeemableDate",
        "availability": "post_draw_publication",
        "use": "excluded",
    },
)
PROTOCOL_CONFIG = {
    "games": list(GAMES),
    "models": ["uniform", MODEL_ID],
    "position_model": {
        "positions": PICK_N,
        "prior": "laplace",
        "alpha": ALPHA,
        "sampling": "position_specific_weighted_without_replacement",
        "subset_probability": "exact_64_state_sum_over_all_6_factorial_orders",
    },
    "score": "negative_log_probability_of_complete_unordered_six_number_subset",
    "control": "exact_discrete_uniform",
    "bootstrap": {
        "kind": "circular_moving_block",
        "block_draws": BOOTSTRAP_BLOCK,
        "samples": BOOTSTRAP_SAMPLES,
        "interval": 0.95,
    },
    "conditional_order_permutation": {
        "samples": PERMUTATION_SAMPLES,
        "conditioning": "fixed_six_number_set_within_each_draw",
        "decision_use": "descriptive_only",
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


def initial_position_counts(pool: int) -> list[list[int]]:
    if not isinstance(pool, int) or pool < PICK_N:
        raise ValueError("球池大小不合法")
    return [[0] * (pool + 1) for _ in range(PICK_N)]


def _validate_position_counts(
    counts: list[list[int]],
    *,
    pool: int,
) -> None:
    if (
        not isinstance(counts, list)
        or len(counts) != PICK_N
        or any(
            not isinstance(row, list)
            or len(row) != pool + 1
            or row[0] != 0
            or any(
                not isinstance(value, int) or value < 0
                for value in row
            )
            for row in counts
        )
    ):
        raise ValueError("位置計數 state 不合法")
    totals = {sum(row) for row in counts}
    if len(totals) != 1:
        raise ValueError("六個位置必須有相同期數")


def position_subset_probability(
    target_numbers: tuple[int, ...] | list[int],
    counts: list[list[int]],
    *,
    pool: int,
    alpha: float = ALPHA,
) -> float:
    """精確加總目標六號集合的全部抽出順序機率。

    DP state 是已從目標集合抽出的 bitmask，共 64 個狀態。每一條路徑的
    分母仍包含所有尚未抽出的球，因此得到的是完整合法無放回生成模型，
    不是把六個位置當成獨立分類。
    """
    target = tuple(int(value) for value in target_numbers)
    if (
        len(target) != PICK_N
        or len(set(target)) != PICK_N
        or any(not 1 <= value <= pool for value in target)
    ):
        raise ValueError("目標主號必須是合法六號集合")
    if not math.isfinite(alpha) or alpha <= 0:
        raise ValueError("Dirichlet alpha 必須為有限正值")
    _validate_position_counts(counts, pool=pool)

    full_mask = (1 << PICK_N) - 1
    probabilities = {0: 1.0}
    for position in range(PICK_N):
        row = counts[position]
        total_weight = pool * alpha + sum(row)
        next_probabilities: dict[int, float] = {}
        for mask, state_probability in probabilities.items():
            removed_weight = sum(
                alpha + row[target[index]]
                for index in range(PICK_N)
                if mask & (1 << index)
            )
            denominator = total_weight - removed_weight
            if denominator <= 0:
                raise ValueError("位置模型條件分母不合法")
            for index, number in enumerate(target):
                bit = 1 << index
                if mask & bit:
                    continue
                next_mask = mask | bit
                transition = (alpha + row[number]) / denominator
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
        raise ValueError("位置模型子集合機率不合法")
    return probability


def _update_position_counts(
    counts: list[list[int]],
    order: tuple[int, ...] | list[int],
    *,
    pool: int,
) -> None:
    values = tuple(int(value) for value in order)
    if (
        len(values) != PICK_N
        or len(set(values)) != PICK_N
        or any(not 1 <= value <= pool for value in values)
    ):
        raise ValueError("抽出順序不合法")
    _validate_position_counts(counts, pool=pool)
    for position, number in enumerate(values):
        counts[position][number] += 1


def _row_schema_signature(row: dict) -> str:
    return "|".join(sorted(str(key) for key in row))


def load_and_profile_raw_game(
    game: str,
    *,
    base: Path,
) -> tuple[list[dict], dict]:
    """讀取全部官方月檔並 fail-closed 驗證抽出順序。"""
    if game not in GAMES:
        raise ValueError("不支援的遊戲")
    raw_dir = Path(base) / "data" / "raw" / game
    files = sorted(raw_dir.glob("*.json"))
    if not files:
        raise RuntimeError(f"{game} 沒有官方原始月檔")

    result_key = RESULT_KEYS[game]
    pool = POOL[game]
    rows: list[dict] = []
    empty_files: list[str] = []
    root_signatures: Counter[str] = Counter()
    row_signatures: Counter[str] = Counter()
    failures: list[str] = []

    for path in files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as error:
            raise RuntimeError(
                f"{game} {path.name} JSON 無法解析"
            ) from error
        root_signatures["|".join(sorted(payload))] += 1
        if (
            set(payload) != {"rtCode", "rtMsg", "content"}
            or payload.get("rtCode") != 0
            or not isinstance(payload.get("content"), dict)
            or set(payload["content"]) != {"totalSize", result_key}
            or not isinstance(payload["content"][result_key], list)
        ):
            failures.append(f"{path.name}:root_schema")
            continue
        month_rows = payload["content"][result_key]
        if payload["content"]["totalSize"] != len(month_rows):
            failures.append(f"{path.name}:total_size")
        if not month_rows:
            empty_files.append(path.name)

        for row in month_rows:
            if not isinstance(row, dict):
                failures.append(f"{path.name}:row_type")
                continue
            row_signatures[_row_schema_signature(row)] += 1
            required = {
                "period",
                "lotteryDate",
                "redeemableDate",
                "drawNumberSize",
                "drawNumberAppear",
                "totalAmount",
                "sellAmount",
            }
            if not required.issubset(row):
                failures.append(f"{path.name}:required_fields")
                continue
            date_value = str(row["lotteryDate"])[:10]
            if date_value[:7] != path.stem:
                failures.append(
                    f"{path.name}:{row.get('period')}:file_month"
                )
            size = row["drawNumberSize"]
            order = row["drawNumberAppear"]
            if (
                not isinstance(size, list)
                or not isinstance(order, list)
                or len(size) != PICK_N + 1
                or len(order) != PICK_N + 1
            ):
                failures.append(
                    f"{path.name}:{row.get('period')}:array_length"
                )
                continue
            try:
                size_values = tuple(int(value) for value in size)
                order_values = tuple(int(value) for value in order)
                period = int(row["period"])
            except (TypeError, ValueError):
                failures.append(
                    f"{path.name}:{row.get('period')}:value_type"
                )
                continue
            size_main = size_values[:PICK_N]
            order_main = order_values[:PICK_N]
            special = size_values[PICK_N]
            if (
                tuple(sorted(size_main)) != size_main
                or len(set(size_main)) != PICK_N
                or len(set(order_main)) != PICK_N
                or set(size_main) != set(order_main)
                or any(not 1 <= number <= pool for number in size_main)
                or any(not 1 <= number <= pool for number in order_main)
                or special != order_values[PICK_N]
            ):
                failures.append(f"{path.name}:{period}:number_contract")
                continue
            if game == SUPER:
                if not 1 <= special <= SPECIAL_POOL[SUPER]:
                    failures.append(f"{path.name}:{period}:special_range")
                    continue
            elif (
                not 1 <= special <= pool
                or special in set(size_main)
            ):
                failures.append(f"{path.name}:{period}:bonus_contract")
                continue
            if any(row.get(field) is None for field in required):
                failures.append(f"{path.name}:{period}:required_null")
                continue
            rows.append(
                {
                    "source_file": path.name,
                    "period": period,
                    "date": date_value,
                    "numbers": list(size_main),
                    "order": list(order_main),
                    "special": special,
                }
            )

    if failures:
        raise RuntimeError(
            f"{game} 原始抽出順序契約失敗：{failures[:5]}"
        )
    rows.sort(key=lambda row: (row["date"], row["period"]))
    periods = [row["period"] for row in rows]
    dates = [row["date"] for row in rows]
    if (
        not rows
        or len(periods) != len(set(periods))
        or len(dates) != len(set(dates))
        or any(
            current <= previous
            for previous, current in zip(dates, dates[1:])
        )
    ):
        raise RuntimeError(f"{game} 期號或日期不唯一遞增")

    ledger_path = (
        Path(base) / "simulation" / "results" / f"{game}.jsonl"
    )
    replay = verify_replay(ledger_path)
    ledger_rows: dict[int, dict] = {}
    with ledger_path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            reveal = json.loads(line)["reveal"]
            ledger_rows[int(reveal["period"])] = reveal
    if set(ledger_rows) != set(periods):
        raise RuntimeError(f"{game} raw 與正式 ledger 期號集合不同")
    mismatches = []
    for row in rows:
        reveal = ledger_rows[row["period"]]
        if (
            row["date"] != str(reveal["date"])
            or row["numbers"]
            != [int(value) for value in reveal["numbers"]]
            or row["special"] != int(reveal["special"])
        ):
            mismatches.append(row["period"])
    if mismatches:
        raise RuntimeError(
            f"{game} raw 與正式 ledger 不一致：{mismatches[:5]}"
        )

    schema_variants = []
    for signature, count in sorted(
        row_signatures.items(),
        key=lambda item: (-item[1], item[0]),
    ):
        signature_keys = set(signature.split("|"))
        variant_rows = [
            row
            for path in files
            for row in json.loads(
                path.read_text(encoding="utf-8")
            )["content"][result_key]
            if _row_schema_signature(row) == signature
        ]
        schema_variants.append(
            {
                "count": count,
                "key_count": len(signature_keys),
                "base_fields_present": {
                    "period",
                    "lotteryDate",
                    "drawNumberSize",
                    "drawNumberAppear",
                }.issubset(signature_keys),
                "first_date": min(
                    str(row["lotteryDate"])[:10]
                    for row in variant_rows
                ),
                "last_date": max(
                    str(row["lotteryDate"])[:10]
                    for row in variant_rows
                ),
            }
        )

    profile = {
        "status": "pass",
        "game": game,
        "game_name": GAME_NAMES[game],
        "files": len(files),
        "empty_files": len(empty_files),
        "empty_file_range": (
            [empty_files[0], empty_files[-1]]
            if empty_files
            else None
        ),
        "draws": len(rows),
        "unique_periods": len(periods),
        "date_range": [dates[0], dates[-1]],
        "root_schema_variants": len(root_signatures),
        "row_schema_variants": len(row_signatures),
        "row_schema_profile": schema_variants,
        "draw_order_coverage_rate": 1.0,
        "required_nulls": 0,
        "duplicate_periods": 0,
        "duplicate_dates": 0,
        "invalid_number_rows": 0,
        "raw_ledger_mismatches": 0,
        "raw_tree_sha256": tree_sha256(raw_dir),
        "ledger_verification": replay,
    }
    return rows, profile


def ordering_association_statistic(
    orders: list[list[int]] | list[tuple[int, ...]],
    *,
    pool: int,
) -> float:
    """條件於每期六號集合的 position-number Pearson 型統計量。"""
    if not orders:
        raise ValueError("ordering statistic 沒有資料")
    counts = [[0] * (pool + 1) for _ in range(PICK_N)]
    totals = [0] * (pool + 1)
    for order in orders:
        values = tuple(int(value) for value in order)
        if (
            len(values) != PICK_N
            or len(set(values)) != PICK_N
            or any(not 1 <= value <= pool for value in values)
        ):
            raise ValueError("ordering statistic 抽出順序不合法")
        for position, number in enumerate(values):
            counts[position][number] += 1
            totals[number] += 1
    statistic = 0.0
    for number in range(1, pool + 1):
        expected = totals[number] / PICK_N
        if expected <= 0:
            continue
        statistic += sum(
            (counts[position][number] - expected) ** 2 / expected
            for position in range(PICK_N)
        )
    if not math.isfinite(statistic) or statistic < 0:
        raise ValueError("ordering statistic 不合法")
    return statistic


def conditional_order_permutation_test(
    orders: list[list[int]] | list[tuple[int, ...]],
    *,
    pool: int,
    samples: int = PERMUTATION_SAMPLES,
    seed: str,
) -> dict:
    """固定每期六號集合，只隨機排列位置的 Monte Carlo 條件檢定。"""
    if not isinstance(samples, int) or samples < 1:
        raise ValueError("permutation samples 必須為正整數")
    normalized = [list(map(int, order)) for order in orders]
    observed = ordering_association_statistic(
        normalized,
        pool=pool,
    )
    totals = [0] * (pool + 1)
    for order in normalized:
        for number in order:
            totals[number] += 1
    rng = random.Random(seed_int(seed))
    greater_equal = 0
    for _ in range(samples):
        counts = [[0] * (pool + 1) for _ in range(PICK_N)]
        for order in normalized:
            permuted = order.copy()
            rng.shuffle(permuted)
            for position, number in enumerate(permuted):
                counts[position][number] += 1
        simulated = 0.0
        for number in range(1, pool + 1):
            expected = totals[number] / PICK_N
            if expected <= 0:
                continue
            simulated += sum(
                (counts[position][number] - expected) ** 2 / expected
                for position in range(PICK_N)
            )
        if simulated >= observed - 1e-12:
            greater_equal += 1
    return {
        "statistic": observed,
        "samples": samples,
        "greater_equal": greater_equal,
        "p_value": (greater_equal + 1) / (samples + 1),
        "conditioning": "fixed_six_number_set_within_each_draw",
        "decision_use": "descriptive_only",
    }


def evaluate_position_model(
    game: str,
    rows: list[dict],
    *,
    bootstrap_samples: int = BOOTSTRAP_SAMPLES,
    permutation_samples: int = PERMUTATION_SAMPLES,
) -> dict:
    if game not in GAMES or not rows:
        raise ValueError("位置模型輸入不合法")
    pool = POOL[game]
    counts = initial_position_counts(pool)
    regrets: list[float] = []
    log_e_value = 0.0
    maximum_log_e_value = 0.0
    uniform_probability = 1.0 / math.comb(pool, PICK_N)

    for index, row in enumerate(rows):
        if index and (
            row["date"] <= rows[index - 1]["date"]
        ):
            raise ValueError("位置模型資料必須按日期嚴格遞增")
        target = tuple(int(value) for value in row["numbers"])
        probability = position_subset_probability(
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
            raise RuntimeError("零歷史位置模型必須精確退回均勻")
        regret = -math.log(probability) + math.log(
            uniform_probability
        )
        if not math.isfinite(regret):
            raise RuntimeError("位置模型 regret 非有限")
        regrets.append(regret)
        log_e_value -= regret
        maximum_log_e_value = max(
            maximum_log_e_value,
            log_e_value,
        )
        _update_position_counts(
            counts,
            row["order"],
            pool=pool,
        )

    ci_low, ci_high = block_bootstrap_ci(
        regrets,
        samples=bootstrap_samples,
        block=BOOTSTRAP_BLOCK,
        seed=f"{EXPERIMENT_ID}|{game}|proper-score-regret",
    )
    half = len(regrets) // 2
    permutation = conditional_order_permutation_test(
        [row["order"] for row in rows],
        pool=pool,
        samples=permutation_samples,
        seed=f"{EXPERIMENT_ID}|{game}|conditional-order",
    )
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
        "final_e_value_at_least_40": (
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
        "conditional_order_permutation": permutation,
        "final_position_counts": [
            row[1:] for row in counts
        ],
        "final_state_hash": canonical_hash(counts),
        "future_challenger_criteria": criteria,
        "future_challenger_qualified": all(criteria.values()),
    }


def build_conclusion(diagnostics: dict[str, dict]) -> dict:
    if set(diagnostics) != set(GAMES):
        raise ValueError("位置模型診斷遊戲不完整")
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
            "兩款遊戲同時通過固定 proper-score、穩定性與 e-value 門檻；"
            "仍只能另立 future-only shadow。"
            if qualified
            else "至少一款遊戲未通過固定完整子集合 proper-score 門檻，"
            "抽出順序不得成為新 Agent 或 watcher 訊號。"
        ),
        "next_evidence": (
            "沒有合格候選時維持現行 null-safe；歷史 ordering p-value "
            "不能替代新的開獎前 proper score。"
        ),
    }


def run_draw_order_signal(
    *,
    base: Path,
    bootstrap_samples: int = BOOTSTRAP_SAMPLES,
    permutation_samples: int = PERMUTATION_SAMPLES,
) -> dict:
    """執行完整資料品質、prequential proper score 與條件排列診斷。"""
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
        game: evaluate_position_model(
            game,
            rows_by_game[game],
            bootstrap_samples=bootstrap_samples,
            permutation_samples=permutation_samples,
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
    result = {
        "schema_version": "1",
        "experiment_id": EXPERIMENT_ID,
        "generated_at": f"{latest_date}T23:59:59+08:00",
        "question": (
            "過去抽出位置能否提高下一期完整無序六號子集合機率？"
        ),
        "protocol": {
            **PROTOCOL_CONFIG,
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
                "forecast_t 使用 update 前 position state；"
                "drawNumberAppear_t 只更新 forecast_t_plus_1。"
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
            "抽出順序是開獎後欄位，只能供更晚目標期使用。",
            "條件排列 p-value 只檢查順序關聯，不能證明無序號碼較準。",
            "公平開獎下所有合法號碼組合理論等機率。",
            "純模擬，不構成購買或下注建議。",
        ],
    }
    result = _stable_floats(result)
    result["audit_hash"] = canonical_hash(result)
    validate_result(
        result,
        expected_bootstrap_samples=bootstrap_samples,
        expected_permutation_samples=permutation_samples,
    )
    return result


def validate_result(
    result: dict,
    *,
    expected_bootstrap_samples: int = BOOTSTRAP_SAMPLES,
    expected_permutation_samples: int = PERMUTATION_SAMPLES,
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
        raise ValueError("抽出順序結果 schema 不合法")
    protocol = result["protocol"]
    expected_protocol = {
        **PROTOCOL_CONFIG,
        "bootstrap": {
            **PROTOCOL_CONFIG["bootstrap"],
            "samples": expected_bootstrap_samples,
        },
        "conditional_order_permutation": {
            **PROTOCOL_CONFIG["conditional_order_permutation"],
            "samples": expected_permutation_samples,
        },
    }
    for key, value in expected_protocol.items():
        if protocol.get(key) != value:
            raise ValueError(f"抽出順序 protocol 欄位不符：{key}")
    if (
        protocol.get("protocol_hash") != PROTOCOL_HASH
        or protocol.get("protocol_file") != PROTOCOL_FILE
        or not _is_sha256(protocol.get("protocol_file_sha256"))
        or result.get("field_classification")
        != list(FIELD_CLASSIFICATION)
    ):
        raise ValueError("抽出順序 protocol 或欄位分類不符")

    quality = result["data_quality"]
    if (
        quality.get("status") != "pass"
        or quality.get("raw_files_total") != 494
        or quality.get("draws_total") != 4082
        or set(quality.get("games", {})) != set(GAMES)
        or set(quality.get("raw_snapshot_hashes", {}))
        != set(GAMES)
        or not _is_sha256(
            quality.get("combined_raw_snapshot_hash")
        )
    ):
        raise ValueError("抽出順序資料品質摘要不合法")
    for game in GAMES:
        profile = quality["games"][game]
        if (
            profile.get("status") != "pass"
            or profile.get("game") != game
            or profile.get("draws")
            != profile.get("unique_periods")
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
            raise ValueError(f"{game} 抽出順序資料品質不合法")
    profile_raw_hashes = {
        game: quality["games"][game]["raw_tree_sha256"]
        for game in GAMES
    }
    if (
        quality["raw_snapshot_hashes"] != profile_raw_hashes
        or quality["combined_raw_snapshot_hash"]
        != canonical_hash(profile_raw_hashes)
    ):
        raise ValueError("抽出順序 raw snapshot hash 關聯不一致")

    diagnostics = result["diagnostics"]
    if set(diagnostics) != set(GAMES):
        raise ValueError("抽出順序 diagnostics 遊戲不完整")
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
        if (
            row.get("game") != game
            or row.get("model") != MODEL_ID
            or row.get("draws")
            != quality["games"][game]["draws"]
            or row.get("first_date")
            != quality["games"][game]["date_range"][0]
            or row.get("last_date")
            != quality["games"][game]["date_range"][1]
            or any(
                not isinstance(row.get(field), (int, float))
                or isinstance(row.get(field), bool)
                or not math.isfinite(float(row[field]))
                for field in finite_fields
            )
            or set(row.get("recent_mean_regret", {}))
            != {str(window) for window in RECENT_WINDOWS}
            or len(row.get("final_position_counts", [])) != PICK_N
            or any(
                len(position) != POOL[game]
                or any(
                    not isinstance(value, int) or value < 0
                    for value in position
                )
                for position in row["final_position_counts"]
            )
            or not _is_sha256(row.get("final_state_hash"))
        ):
            raise ValueError(f"{game} 抽出順序診斷欄位不合法")
        permutation = row.get("conditional_order_permutation", {})
        if (
            permutation.get("samples") != expected_permutation_samples
            or not 0 < permutation.get("p_value", 0) <= 1
            or not 0 <= permutation.get("greater_equal", -1)
            <= expected_permutation_samples
            or permutation.get("decision_use")
            != "descriptive_only"
        ):
            raise ValueError(f"{game} 條件排列檢定不合法")
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
            "final_e_value_at_least_40": (
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

    expected_conclusion = build_conclusion(diagnostics)
    if result.get("conclusion") != expected_conclusion:
        raise ValueError("抽出順序結論不一致")
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
        raise ValueError("抽出順序 records 完整性失敗")
    audit_payload = {
        key: value
        for key, value in result.items()
        if key != "audit_hash"
    }
    if (
        not _is_sha256(result.get("audit_hash"))
        or result["audit_hash"] != canonical_hash(audit_payload)
    ):
        raise ValueError("抽出順序 audit hash 不一致")
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
