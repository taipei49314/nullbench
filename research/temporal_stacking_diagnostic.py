"""診斷時間衰減能否降低七專家 stacking 的完整子集 proper-score regret。

所有方法都嚴格 prequential：第 t 期 forecast 只能使用第 t-1 期以前的
權重狀態；第 t 期 reveal 只更新第 t+1 期。完整歷史只作描述性診斷，
不能被本模組重新解釋為策略升級證據。
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import statistics

from engine.agent_loop import (
    LOOP_EXPERIMENT_ID,
    canonical_hash,
    verify_replay,
)
from engine.games import (
    GAME_NAMES,
    LOTTO649,
    POOL,
    SPECIAL_POOL,
    SUPER,
)
from research.agent_ablation import (
    _validate_event,
    block_bootstrap_ci,
)
from research.gates import tree_sha256
from research.null_safe_probability import (
    ACTIVATION_E_THRESHOLD,
    initial_e_process_state,
    restart_e_process_step,
    subset_log_likelihood_ratio_vs_uniform,
)
from research.probability_stacking import (
    EXPERT_IDS,
    UNIFORM_EXPERT,
    _softmax,
    expert_distributions,
    mixture_distribution,
    update_log_weights,
)


EXPERIMENT_ID = "temporal-probability-stacking-diagnostic-v1"
PROTOCOL_FILE = "TEMPORAL_STACKING_PROTOCOL.md"
METHODS = (
    "uniform",
    "current_cumulative_marginal",
    "subset_cumulative",
    "subset_rolling_52",
    "subset_rolling_104",
    "subset_rolling_208",
    "subset_ewma_52",
    "subset_ewma_104",
    "subset_ewma_208",
)
STREAMS = (
    "super_main",
    "super_special",
    "lotto649_main",
)
RECENT_WINDOWS = (52, 104, 208)
BOOTSTRAP_BLOCK = 13
BOOTSTRAP_SAMPLES = 2_000
PROTOCOL_CONFIG = {
    "methods": list(METHODS),
    "streams": list(STREAMS),
    "main_score": (
        "negative_log_probability_of_complete_unordered_six_number_subset"
    ),
    "special_score": "categorical_negative_log_probability_mass",
    "control": "exact_discrete_uniform",
    "rolling_windows": list(RECENT_WINDOWS),
    "ewma_half_lives": list(RECENT_WINDOWS),
    "bootstrap": {
        "kind": "circular_moving_block",
        "block_draws": BOOTSTRAP_BLOCK,
        "samples": BOOTSTRAP_SAMPLES,
        "interval": 0.95,
    },
    "activation_e_threshold": ACTIVATION_E_THRESHOLD,
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


def _stream_id(game: str, dimension: str) -> str:
    if game == SUPER and dimension == "main":
        return "super_main"
    if game == SUPER and dimension == "special":
        return "super_special"
    if game == LOTTO649 and dimension == "main":
        return "lotto649_main"
    raise ValueError("時間 stacking stream 不合法")


def _uniform_distribution(domain_size: int) -> dict[int, float]:
    return {
        number: 1.0 / domain_size
        for number in range(1, domain_size + 1)
    }


def _shift_logs(logs: dict[str, float]) -> dict[str, float]:
    if set(logs) != set(EXPERT_IDS):
        raise ValueError("時間 stacking log weights 欄位不完整")
    values = {expert: float(logs[expert]) for expert in EXPERT_IDS}
    if any(not math.isfinite(value) for value in values.values()):
        raise ValueError("時間 stacking log weights 必須為有限值")
    maximum = max(values.values())
    shifted = {
        expert: values[expert] - maximum
        for expert in EXPERT_IDS
    }
    _softmax(shifted)
    return shifted


def initial_method_state(method: str) -> dict:
    if method not in METHODS:
        raise ValueError("未知時間 stacking 方法")
    return {
        "method": method,
        "logs": {expert: 0.0 for expert in EXPERT_IDS},
        "history": [],
        "discounted_regret": {
            expert: 0.0 for expert in EXPERT_IDS
        },
        "effective_draws": 0.0,
        "sequence": 0,
    }


def _expert_regrets(
    distributions: dict[str, dict[int, float]],
    actual: list[int],
    *,
    dimension: str,
    domain_size: int,
) -> dict[str, float]:
    if set(distributions) != set(EXPERT_IDS):
        raise ValueError("時間 stacking 專家分布欄位不完整")
    if dimension == "main":
        log_likelihood_ratios = {
            expert: subset_log_likelihood_ratio_vs_uniform(
                distributions[expert],
                actual,
            )
            for expert in EXPERT_IDS
        }
    elif dimension == "special":
        value = int(actual[0])
        if len(actual) != 1 or not 1 <= value <= domain_size:
            raise ValueError("時間 stacking 第二區揭曉不合法")
        log_likelihood_ratios = {
            expert: math.log(
                float(distributions[expert][value]) * domain_size
            )
            for expert in EXPERT_IDS
        }
    else:
        raise ValueError("時間 stacking dimension 不合法")
    output = {
        expert: (
            0.0
            if expert == UNIFORM_EXPERT
            else -float(log_likelihood_ratios[expert])
        )
        for expert in EXPERT_IDS
    }
    if any(not math.isfinite(value) for value in output.values()):
        raise ValueError("時間 stacking 專家 regret 非有限")
    return output


def _forecast_regret(
    method: str,
    state: dict,
    distributions: dict[str, dict[int, float]],
    actual: list[int],
    *,
    dimension: str,
    domain_size: int,
) -> float:
    if method == "uniform":
        return 0.0
    mixture = mixture_distribution(distributions, state["logs"])
    if dimension == "main":
        return -subset_log_likelihood_ratio_vs_uniform(
            mixture,
            actual,
        )
    value = int(actual[0])
    return -math.log(float(mixture[value]) * domain_size)


def update_method_state(
    state: dict,
    *,
    distributions: dict[str, dict[int, float]],
    actual: list[int],
    expert_regrets: dict[str, float],
    sequence: int,
) -> dict:
    method = str(state.get("method"))
    if method not in METHODS or sequence != int(state.get("sequence", -1)) + 1:
        raise ValueError("時間 stacking state sequence 不連續")
    updated = deepcopy(state)
    updated["sequence"] = sequence
    if method == "uniform":
        return updated
    if method == "current_cumulative_marginal":
        updated["logs"], _ = update_log_weights(
            updated["logs"],
            distributions,
            actual,
            sequence=sequence,
        )
        return updated
    if method == "subset_cumulative":
        eta = 1.0 / math.sqrt(sequence)
        updated["logs"] = _shift_logs(
            {
                expert: float(updated["logs"][expert])
                - eta * float(expert_regrets[expert])
                for expert in EXPERT_IDS
            }
        )
        return updated
    if method.startswith("subset_rolling_"):
        window = int(method.rsplit("_", 1)[1])
        updated["history"].append(deepcopy(expert_regrets))
        updated["history"] = updated["history"][-window:]
        effective = len(updated["history"])
        updated["logs"] = _shift_logs(
            {
                expert: -math.fsum(
                    row[expert] for row in updated["history"]
                )
                / math.sqrt(effective)
                for expert in EXPERT_IDS
            }
        )
        return updated
    if method.startswith("subset_ewma_"):
        half_life = int(method.rsplit("_", 1)[1])
        decay = 2.0 ** (-1.0 / half_life)
        effective = (
            decay * float(updated["effective_draws"]) + 1.0
        )
        updated["effective_draws"] = effective
        updated["discounted_regret"] = {
            expert: (
                decay
                * float(updated["discounted_regret"][expert])
                + float(expert_regrets[expert])
            )
            for expert in EXPERT_IDS
        }
        updated["logs"] = _shift_logs(
            {
                expert: -float(
                    updated["discounted_regret"][expert]
                )
                / math.sqrt(effective)
                for expert in EXPERT_IDS
            }
        )
        return updated
    raise AssertionError("時間 stacking 方法分支遺漏")


def _mean(values: list[float]) -> float:
    return statistics.fmean(values)


def _summarize_method(
    *,
    game: str,
    dimension: str,
    method: str,
    regrets: list[float],
    state: dict,
    e_state: dict,
    maximum_log_e_value: float,
    bootstrap_samples: int,
) -> dict:
    midpoint = len(regrets) // 2
    ci_low, ci_high = block_bootstrap_ci(
        regrets,
        samples=bootstrap_samples,
        block=BOOTSTRAP_BLOCK,
        seed=f"{EXPERIMENT_ID}:{game}:{dimension}:{method}",
    )
    recent = {
        str(window): _mean(regrets[-min(window, len(regrets)):])
        for window in RECENT_WINDOWS
    }
    if method == "uniform":
        final_uniform_weight = 1.0
    else:
        final_uniform_weight = _softmax(state["logs"])[
            UNIFORM_EXPERT
        ]
    row = {
        "stream": _stream_id(game, dimension),
        "game": game,
        "game_name": GAME_NAMES[game],
        "dimension": dimension,
        "method": method,
        "draws": len(regrets),
        "mean_regret_nats": _mean(regrets),
        "mean_information_gain_nats": -_mean(regrets),
        "bootstrap_95_low": ci_low,
        "bootstrap_95_high": ci_high,
        "first_half_mean_regret": _mean(regrets[:midpoint]),
        "second_half_mean_regret": _mean(regrets[midpoint:]),
        "recent_mean_regret": recent,
        "better_than_uniform_rate": (
            sum(value < -1e-15 for value in regrets)
            / len(regrets)
        ),
        "tie_uniform_rate": (
            sum(abs(value) <= 1e-15 for value in regrets)
            / len(regrets)
        ),
        "final_uniform_expert_weight": final_uniform_weight,
        "final_e_value": math.exp(float(e_state["log_e_value"])),
        "maximum_e_value": math.exp(maximum_log_e_value),
    }
    if any(
        not math.isfinite(float(value))
        for key, value in row.items()
        if key
        not in {
            "stream",
            "game",
            "game_name",
            "dimension",
            "method",
            "recent_mean_regret",
        }
    ) or any(
        not math.isfinite(float(value)) for value in recent.values()
    ):
        raise ValueError("時間 stacking 摘要含非有限值")
    return row


def evaluate_stream(
    events: list[dict],
    *,
    game: str,
    dimension: str,
    bootstrap_samples: int = BOOTSTRAP_SAMPLES,
) -> dict:
    """回傳 summary 與測試用逐期 trace；formal artifact 不保存 trace。"""
    stream = _stream_id(game, dimension)
    if not events or bootstrap_samples < 1:
        raise ValueError("時間 stacking stream 缺少資料")
    states = {
        method: initial_method_state(method) for method in METHODS
    }
    regrets = {method: [] for method in METHODS}
    e_states = {
        method: initial_e_process_state() for method in METHODS
    }
    maximum_log_e = {method: 0.0 for method in METHODS}
    previous_key = None
    seen_periods = set()
    for sequence, event in enumerate(events, 1):
        _validate_event(event, game, sequence)
        reveal = event["reveal"]
        key = (str(reveal["date"]), int(reveal["period"]))
        if previous_key is not None and key <= previous_key:
            raise ValueError("時間 stacking 期別未嚴格遞增")
        if key[1] in seen_periods:
            raise ValueError("時間 stacking 期別重複")
        previous_key = key
        seen_periods.add(key[1])
        distributions = expert_distributions(
            game,
            event["decision"],
            dimension=dimension,
        )
        if dimension == "main":
            actual = [int(number) for number in reveal["numbers"]]
            domain_size = POOL[game]
        else:
            actual = [int(reveal["special"])]
            domain_size = SPECIAL_POOL[SUPER]
        expert_regrets = _expert_regrets(
            distributions,
            actual,
            dimension=dimension,
            domain_size=domain_size,
        )
        for method in METHODS:
            regret = _forecast_regret(
                method,
                states[method],
                distributions,
                actual,
                dimension=dimension,
                domain_size=domain_size,
            )
            if not math.isfinite(regret):
                raise ValueError("時間 stacking forecast regret 非有限")
            regrets[method].append(regret)
            e_states[method] = restart_e_process_step(
                e_states[method],
                -regret,
            )
            maximum_log_e[method] = max(
                maximum_log_e[method],
                float(e_states[method]["log_e_value"]),
            )
            states[method] = update_method_state(
                states[method],
                distributions=distributions,
                actual=actual,
                expert_regrets=expert_regrets,
                sequence=sequence,
            )
    rows = [
        _summarize_method(
            game=game,
            dimension=dimension,
            method=method,
            regrets=regrets[method],
            state=states[method],
            e_state=e_states[method],
            maximum_log_e_value=maximum_log_e[method],
            bootstrap_samples=bootstrap_samples,
        )
        for method in METHODS
    ]
    return {
        "stream": stream,
        "rows": rows,
        "traces": regrets,
        "final_states": states,
    }


def _qualifies(row: dict) -> bool:
    return (
        float(row["mean_regret_nats"]) < 0
        and float(row["bootstrap_95_high"]) < 0
        and float(row["first_half_mean_regret"]) <= 0
        and float(row["second_half_mean_regret"]) <= 0
        and all(
            float(row["recent_mean_regret"][str(window)]) <= 0
            for window in RECENT_WINDOWS
        )
        and float(row["final_e_value"])
        >= ACTIVATION_E_THRESHOLD
    )


def build_conclusion(rows: list[dict]) -> dict:
    by_method = {
        method: [
            row for row in rows if row["method"] == method
        ]
        for method in METHODS
    }
    if any(
        {row["stream"] for row in method_rows} != set(STREAMS)
        for method_rows in by_method.values()
    ):
        raise ValueError("時間 stacking 結論缺少固定 stream")
    ranking = sorted(
        (method for method in METHODS if method != "uniform"),
        key=lambda method: (
            max(
                float(row["mean_regret_nats"])
                for row in by_method[method]
            ),
            statistics.fmean(
                float(row["mean_regret_nats"])
                for row in by_method[method]
            ),
            method,
        ),
    )
    qualified = [
        method
        for method in ranking
        if all(_qualifies(row) for row in by_method[method])
    ]
    selected = qualified[0] if qualified else None
    return {
        "status": (
            "future_challenger_supported_for_preregistration"
            if selected is not None
            else "retain_existing_null_safe_protocol"
        ),
        "historical_promotion_eligible": False,
        "watcher_integration_allowed": False,
        "descriptive_minimax_method": ranking[0],
        "qualified_future_challengers": qualified,
        "selected_future_challenger": selected,
        "ranking": ranking,
        "decision_rule": (
            "三個 stream 的全期、bootstrap 上界、前後半、最近 "
            "52/104/208 與 final e-value 必須同時通過；歷史結果仍不得升級。"
        ),
        "next_evidence": (
            "只有另立新 experiment ID 且開獎前預註冊的未來 proper score "
            "可以支持 challenger；沒有合格者時維持現行 null-safe 均勻 gate。"
        ),
    }


def run_temporal_stacking_diagnostic(
    ledger_paths: dict[str, Path],
    *,
    base: Path,
    verify_ledgers: bool = True,
    bootstrap_samples: int = BOOTSTRAP_SAMPLES,
) -> dict:
    if set(ledger_paths) != {SUPER, LOTTO649}:
        raise ValueError("時間 stacking 診斷需要兩款遊戲 ledger")
    base = Path(base)
    records_before = tree_sha256(base / "records")
    verification = {}
    source_first_dates = {}
    source_last_dates = {}
    all_rows = []
    for game in (SUPER, LOTTO649):
        path = Path(ledger_paths[game])
        verification[game] = (
            verify_replay(path)
            if verify_ledgers
            else {
                "lines": sum(
                    1
                    for line in path.read_text(
                        encoding="utf-8"
                    ).splitlines()
                    if line.strip()
                ),
                "ledger_sha256": _file_sha256(path),
                "last_event_hash": None,
            }
        )
        with path.open(encoding="utf-8") as handle:
            events = [
                json.loads(line)
                for line in handle
                if line.strip()
            ]
        if not events:
            raise ValueError("時間 stacking ledger 不得為空")
        if verification[game]["lines"] != len(events):
            raise ValueError("時間 stacking ledger 行數不符")
        source_first_dates[game] = str(events[0]["reveal"]["date"])
        source_last_dates[game] = str(events[-1]["reveal"]["date"])
        all_rows.extend(
            evaluate_stream(
                events,
                game=game,
                dimension="main",
                bootstrap_samples=bootstrap_samples,
            )["rows"]
        )
        if game == SUPER:
            all_rows.extend(
                evaluate_stream(
                    events,
                    game=game,
                    dimension="special",
                    bootstrap_samples=bootstrap_samples,
                )["rows"]
            )
    all_rows.sort(key=lambda row: (row["stream"], row["method"]))
    records_after = tree_sha256(base / "records")
    payload = {
        "schema_version": "1",
        "experiment_id": EXPERIMENT_ID,
        "source_experiment_id": LOOP_EXPERIMENT_ID,
        "generated_at": max(source_last_dates.values())
        + "T23:59:59+08:00",
        "question": (
            "rolling 或 EWMA 時間衰減能否在嚴格 prequential 的完整子集 "
            "proper score 下，降低現行 stacking 相對均勻模型的 regret？"
        ),
        "protocol": {
            **PROTOCOL_CONFIG,
            "protocol_hash": PROTOCOL_HASH,
            "protocol_file": PROTOCOL_FILE,
            "protocol_file_sha256": _file_sha256(
                base / PROTOCOL_FILE
            ),
        },
        "data_quality": {
            "status": "pass",
            "ledger_verification": verification,
            "source_first_dates": source_first_dates,
            "source_last_dates": source_last_dates,
            "chronology": "strictly_increasing",
            "duplicate_periods": 0,
            "unit": "每款遊戲每期一個開獎前七專家集合",
            "lookahead_control": (
                "第 t 期 forecast 使用 update 前 state；第 t 期 reveal "
                "只更新第 t+1 期。"
            ),
        },
        "diagnostic_rows": all_rows,
        "conclusion": build_conclusion(all_rows),
        "records_integrity": {
            "before_sha256": records_before,
            "after_sha256": records_after,
            "unchanged": records_before == records_after,
        },
        "limitations": [
            "公平模型下所有合法號碼組合理論等機率。",
            "完整歷史已被其他研究使用，本結果只有描述性診斷地位。",
            "比較九種方法仍有選模風險，不能以歷史最佳者直接升級。",
            "只有新的開獎前預註冊 proper score 能支持未來 challenger。",
            "純模擬，不構成購買或下注建議。",
        ],
    }
    result = {
        **payload,
        "audit_hash": canonical_hash(payload),
    }
    validate_result(result)
    if not result["records_integrity"]["unchanged"]:
        raise RuntimeError("時間 stacking 診斷不應修改正式 records")
    return result


def validate_result(result: dict) -> dict:
    expected_fields = {
        "schema_version",
        "experiment_id",
        "source_experiment_id",
        "generated_at",
        "question",
        "protocol",
        "data_quality",
        "diagnostic_rows",
        "conclusion",
        "records_integrity",
        "limitations",
        "audit_hash",
    }
    if (
        not isinstance(result, dict)
        or set(result) != expected_fields
        or result.get("schema_version") != "1"
        or result.get("experiment_id") != EXPERIMENT_ID
        or result.get("source_experiment_id") != LOOP_EXPERIMENT_ID
        or not _is_sha256(result.get("audit_hash"))
        or result.get("protocol", {}).get("protocol_hash")
        != PROTOCOL_HASH
        or result.get("protocol", {}).get("methods")
        != list(METHODS)
        or result.get("protocol", {}).get("streams")
        != list(STREAMS)
        or not _is_sha256(
            result.get("protocol", {}).get(
                "protocol_file_sha256"
            )
        )
        or result.get("data_quality", {}).get("status") != "pass"
        or result.get("records_integrity", {}).get("unchanged")
        is not True
    ):
        raise ValueError("時間 stacking 診斷結果契約不符")
    payload = {
        key: value
        for key, value in result.items()
        if key != "audit_hash"
    }
    if result["audit_hash"] != canonical_hash(payload):
        raise ValueError("時間 stacking 診斷 audit hash 不符")
    rows = result["diagnostic_rows"]
    if (
        not isinstance(rows, list)
        or len(rows) != len(METHODS) * len(STREAMS)
        or {
            (row.get("stream"), row.get("method"))
            for row in rows
        }
        != {
            (stream, method)
            for stream in STREAMS
            for method in METHODS
        }
    ):
        raise ValueError("時間 stacking 診斷列集合不符")
    expected_row_fields = {
        "stream",
        "game",
        "game_name",
        "dimension",
        "method",
        "draws",
        "mean_regret_nats",
        "mean_information_gain_nats",
        "bootstrap_95_low",
        "bootstrap_95_high",
        "first_half_mean_regret",
        "second_half_mean_regret",
        "recent_mean_regret",
        "better_than_uniform_rate",
        "tie_uniform_rate",
        "final_uniform_expert_weight",
        "final_e_value",
        "maximum_e_value",
    }
    for row in rows:
        if (
            set(row) != expected_row_fields
            or row["method"] not in METHODS
            or row["stream"] not in STREAMS
            or type(row["draws"]) is not int
            or row["draws"] < 1
            or set(row["recent_mean_regret"])
            != {str(window) for window in RECENT_WINDOWS}
        ):
            raise ValueError("時間 stacking 診斷列契約不符")
        numeric = [
            row[key]
            for key in expected_row_fields
            if key
            not in {
                "stream",
                "game",
                "game_name",
                "dimension",
                "method",
                "draws",
                "recent_mean_regret",
            }
        ] + list(row["recent_mean_regret"].values())
        if any(not math.isfinite(float(value)) for value in numeric):
            raise ValueError("時間 stacking 診斷列含非有限值")
        if not (
            0 <= float(row["better_than_uniform_rate"]) <= 1
            and 0 <= float(row["tie_uniform_rate"]) <= 1
            and 0
            <= float(row["final_uniform_expert_weight"])
            <= 1
            and float(row["final_e_value"]) > 0
            and float(row["maximum_e_value"]) >= 1
            and math.isclose(
                float(row["mean_information_gain_nats"]),
                -float(row["mean_regret_nats"]),
                rel_tol=0.0,
                abs_tol=1e-12,
            )
        ):
            raise ValueError("時間 stacking 診斷列語意不符")
        if row["method"] == "uniform" and any(
            not math.isclose(
                float(value),
                expected,
                rel_tol=0.0,
                abs_tol=1e-12,
            )
            for value, expected in (
                (row["mean_regret_nats"], 0.0),
                (row["bootstrap_95_low"], 0.0),
                (row["bootstrap_95_high"], 0.0),
                (row["final_uniform_expert_weight"], 1.0),
                (row["final_e_value"], 1.0),
                (row["maximum_e_value"], 1.0),
            )
        ):
            raise ValueError("均勻控制組診斷不符")
    if result["conclusion"] != build_conclusion(rows):
        raise ValueError("時間 stacking 診斷結論無法重建")
    return deepcopy(result)


def write_results(result: dict, output_dir: Path) -> Path:
    verified = validate_result(result)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "temporal_stacking_diagnostic.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(verified, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return path
