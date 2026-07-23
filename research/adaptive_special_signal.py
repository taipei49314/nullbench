"""威力彩共同第二區時間自適應方法的巢狀前向稽核。

候選、切分與門檻先凍結在 ``ADAPTIVE_SPECIAL_PROTOCOL.md``。每一期方法
只能讀取嚴格更早的第二區；inner validation 沒有合格候選時，外層 holdout
保持未開封。
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from datetime import date
import hashlib
import json
import math
import os
from pathlib import Path
import statistics

from engine.agent_loop import canonical_hash, verify_replay
from engine.games import SPECIAL_POOL, SUPER
from research.agent_ablation import (
    _validate_event,
    block_bootstrap_ci,
)
from research.gates import tree_sha256
from research.label_signal import _binomial_upper_tail, _holm_adjust
from research.max_coverage import select_consensus_disjoint_portfolio
from research.mechanism_signal import (
    MechanismSignalConfig,
    _floor_profit_result,
    _profile_events,
    _split_profile,
)
from research.profit_portfolio_forward import (
    EMPIRICAL_FLOOR_SNAPSHOT,
    FIVE_TICKET_COST_NTD,
    GUARDED_PROOF,
    PORTFOLIO_IDS,
    UNCONSTRAINED_PROOF,
    build_profit_portfolio_shadows,
)


EXPERIMENT_ID = "adaptive-profit-common-special-audit-v1"
FORWARD_EXPERIMENT_ID = (
    "adaptive-profit-common-special-forward-shadow-v2"
)
PROTOCOL_FILE = "ADAPTIVE_SPECIAL_PROTOCOL.md"
METHODS = (
    "expanding_global",
    "expanding_weekday",
    "rolling_52",
    "rolling_104",
    "rolling_208",
    "ewma_half_life_52",
    "ewma_half_life_104",
)
WEEKDAY_MINIMUM_HISTORY = 52
EXACT_NULL_SPECIAL_RATE = 1 / SPECIAL_POOL[SUPER]


@dataclass(frozen=True)
class AdaptiveSpecialConfig:
    warmup_draws: int = 60
    development_fraction: float = 0.70
    inner_training_fraction: float = 0.70
    bootstrap_samples: int = 2_000
    bootstrap_block: int = 13

    def validate(self) -> None:
        MechanismSignalConfig(
            warmup_draws=self.warmup_draws,
            development_fraction=self.development_fraction,
            inner_training_fraction=self.inner_training_fraction,
            bootstrap_samples=self.bootstrap_samples,
            bootstrap_block=self.bootstrap_block,
        ).validate()

    def mechanism_config(self) -> MechanismSignalConfig:
        return MechanismSignalConfig(
            warmup_draws=self.warmup_draws,
            development_fraction=self.development_fraction,
            inner_training_fraction=self.inner_training_fraction,
            bootstrap_samples=self.bootstrap_samples,
            bootstrap_block=self.bootstrap_block,
        )


def _special(event: dict) -> int:
    return int(event["reveal"]["special"])


def _rank_count(values: list[int]) -> int:
    counts = Counter(values)
    return min(
        range(1, SPECIAL_POOL[SUPER] + 1),
        key=lambda value: (-counts[value], value),
    )


def predict_special(
    method: str,
    history: list[dict],
    target_date: str,
) -> int:
    """使用嚴格過去 history 產生單一第二區。"""
    if method not in METHODS:
        raise ValueError("未知共同第二區自適應方法")
    if not history:
        raise ValueError("共同第二區自適應方法缺少過去資料")
    specials = [_special(event) for event in history]
    if method == "expanding_global":
        return _rank_count(specials)
    if method == "expanding_weekday":
        weekday = date.fromisoformat(target_date).weekday()
        same_weekday = [
            _special(event)
            for event in history
            if date.fromisoformat(event["reveal"]["date"]).weekday()
            == weekday
        ]
        return (
            _rank_count(same_weekday)
            if len(same_weekday) >= WEEKDAY_MINIMUM_HISTORY
            else _rank_count(specials)
        )
    if method.startswith("rolling_"):
        window = int(method.rsplit("_", 1)[1])
        return _rank_count(specials[-window:])
    half_life = int(method.rsplit("_", 1)[1])
    scores = {
        value: 0.0 for value in range(1, SPECIAL_POOL[SUPER] + 1)
    }
    for age, value in enumerate(reversed(specials)):
        scores[value] += 2.0 ** (-age / half_life)
    return min(
        scores,
        key=lambda value: (-scores[value], value),
    )


def build_prequential_predictions(
    events: list[dict],
    *,
    warmup_draws: int,
) -> dict[str, list[int | None]]:
    if not 1 <= warmup_draws < len(events):
        raise ValueError("自適應第二區暖機期不合法")
    predictions = {
        method: [None] * len(events) for method in METHODS
    }
    for index in range(warmup_draws, len(events)):
        history = events[:index]
        target_date = str(events[index]["reveal"]["date"])
        for method in METHODS:
            predictions[method][index] = predict_special(
                method,
                history,
                target_date,
            )
    return predictions


def _baseline_profit(event: dict) -> tuple[int, dict[str, dict]]:
    coverage_tickets, selection = (
        select_consensus_disjoint_portfolio(
            SUPER, event["decision"]
        )
    )
    top_ticket_index = min(
        range(len(coverage_tickets)),
        key=lambda index: (
            -float(selection["ticket_debate_support"][index]),
            index,
        ),
    )
    baseline_special = int(
        coverage_tickets[top_ticket_index]["special"]
    )
    shadow = build_profit_portfolio_shadows(
        source_decision_hash=event["decision"]["decision_hash"],
        support_evidence_hash=selection["support_evidence_hash"],
        ranked_main_numbers=selection["selected_main_numbers"],
        selected_special=baseline_special,
    )
    return baseline_special, {
        portfolio_id: {
            "tickets": shadow["portfolios"][portfolio_id]["tickets"],
            "result": _floor_profit_result(
                shadow["portfolios"][portfolio_id]["tickets"],
                event["reveal"],
            ),
        }
        for portfolio_id in PORTFOLIO_IDS
    }


def _sign_test(candidate_wins: int, baseline_wins: int) -> float:
    discordant = candidate_wins + baseline_wins
    if discordant == 0:
        return 1.0
    return _binomial_upper_tail(
        discordant,
        candidate_wins,
        0.5,
    )


def _evaluate_methods(
    events: list[dict],
    indices: list[int],
    predictions: dict[str, list[int | None]],
    methods: tuple[str, ...],
    *,
    config: AdaptiveSpecialConfig,
    split: str,
) -> dict[str, dict]:
    values = {
        method: {
            "special_hits": [],
            "baseline_special_hits": [],
            "predicted_specials": [],
            "portfolios": {
                portfolio_id: {
                    "candidate_profit": [],
                    "baseline_profit": [],
                    "strict_deltas": [],
                    "net_deltas": [],
                }
                for portfolio_id in PORTFOLIO_IDS
            },
        }
        for method in methods
    }
    for index in indices:
        event = events[index]
        actual_special = _special(event)
        baseline_special, baseline = _baseline_profit(event)
        for method in methods:
            selected = predictions[method][index]
            if not isinstance(selected, int):
                raise RuntimeError("自適應第二區預測缺失")
            row = values[method]
            row["predicted_specials"].append(selected)
            row["special_hits"].append(
                int(selected == actual_special)
            )
            row["baseline_special_hits"].append(
                int(baseline_special == actual_special)
            )
            for portfolio_id in PORTFOLIO_IDS:
                baseline_row = baseline[portfolio_id]
                candidate_tickets = [
                    {**ticket, "special": selected}
                    for ticket in baseline_row["tickets"]
                ]
                candidate = _floor_profit_result(
                    candidate_tickets,
                    event["reveal"],
                )
                baseline_result = baseline_row["result"]
                candidate_profit = int(
                    candidate[
                        "empirical_floor_stress_strict_profit"
                    ]
                )
                baseline_profit = int(
                    baseline_result[
                        "empirical_floor_stress_strict_profit"
                    ]
                )
                portfolio = row["portfolios"][portfolio_id]
                portfolio["candidate_profit"].append(
                    candidate_profit
                )
                portfolio["baseline_profit"].append(
                    baseline_profit
                )
                portfolio["strict_deltas"].append(
                    candidate_profit - baseline_profit
                )
                portfolio["net_deltas"].append(
                    candidate[
                        "empirical_floor_stress_net_ntd"
                    ]
                    - baseline_result[
                        "empirical_floor_stress_net_ntd"
                    ]
                )

    results = {}
    midpoint = len(indices) // 2
    for method, row in values.items():
        special_hits = row["special_hits"]
        baseline_special_hits = row["baseline_special_hits"]
        portfolios = {}
        for portfolio_id, source in row["portfolios"].items():
            deltas = source["strict_deltas"]
            ci_low, ci_high = block_bootstrap_ci(
                deltas,
                samples=config.bootstrap_samples,
                block=config.bootstrap_block,
                seed=(
                    f"{EXPERIMENT_ID}|{split}|{method}|"
                    f"{portfolio_id}"
                ),
            )
            candidate_wins = sum(value > 0 for value in deltas)
            baseline_wins = sum(value < 0 for value in deltas)
            portfolios[portfolio_id] = {
                "draws": len(indices),
                "candidate_strict_profit_rate": statistics.fmean(
                    source["candidate_profit"]
                ),
                "baseline_strict_profit_rate": statistics.fmean(
                    source["baseline_profit"]
                ),
                "strict_profit_delta": statistics.fmean(deltas),
                "strict_profit_delta_ci_low": ci_low,
                "strict_profit_delta_ci_high": ci_high,
                "first_half_strict_profit_delta": (
                    statistics.fmean(deltas[:midpoint])
                ),
                "second_half_strict_profit_delta": (
                    statistics.fmean(deltas[midpoint:])
                ),
                "candidate_wins": candidate_wins,
                "ties": sum(value == 0 for value in deltas),
                "baseline_wins": baseline_wins,
                "raw_one_sided_sign_p_value": _sign_test(
                    candidate_wins, baseline_wins
                ),
                "mean_net_delta_ntd": statistics.fmean(
                    source["net_deltas"]
                ),
            }
        results[method] = {
            "method": method,
            "draws": len(indices),
            "predicted_special_counts": {
                str(value): count
                for value, count in sorted(
                    Counter(row["predicted_specials"]).items()
                )
            },
            "special_hits": sum(special_hits),
            "special_hit_rate": statistics.fmean(special_hits),
            "delta_vs_exact_null": (
                statistics.fmean(special_hits)
                - EXACT_NULL_SPECIAL_RATE
            ),
            "raw_one_sided_special_p_value": (
                _binomial_upper_tail(
                    len(indices),
                    sum(special_hits),
                    EXACT_NULL_SPECIAL_RATE,
                )
            ),
            "baseline_special_hits": sum(baseline_special_hits),
            "baseline_special_hit_rate": statistics.fmean(
                baseline_special_hits
            ),
            "portfolios": portfolios,
        }
    return results


def _select_inner_candidate(
    results: dict[str, dict],
) -> tuple[str | None, list[str]]:
    eligible = []
    for method in METHODS:
        row = results[method]
        if (
            row["delta_vs_exact_null"] > 0
            and all(
                portfolio["strict_profit_delta"] > 0
                for portfolio in row["portfolios"].values()
            )
        ):
            eligible.append(method)
    if not eligible:
        return None, []

    def score(method: str) -> tuple:
        rows = list(results[method]["portfolios"].values())
        strict = [row["strict_profit_delta"] for row in rows]
        net = [row["mean_net_delta_ntd"] for row in rows]
        return (
            -min(strict),
            -statistics.fmean(strict),
            -statistics.fmean(net),
            method,
        )

    return min(eligible, key=score), eligible


def run_adaptive_special_study(
    ledger_path: Path,
    *,
    base: Path,
    config: AdaptiveSpecialConfig | None = None,
    verify_ledger: bool = True,
) -> dict:
    config = config or AdaptiveSpecialConfig()
    config.validate()
    base = Path(base)
    protocol_path = base / PROTOCOL_FILE
    if not protocol_path.exists():
        raise RuntimeError("缺少共同第二區自適應預註冊文件")
    protocol_hash = hashlib.sha256(
        protocol_path.read_bytes()
    ).hexdigest()
    records_before = tree_sha256(base / "records")
    path = Path(ledger_path)
    verification = (
        verify_replay(path)
        if verify_ledger
        else {
            "lines": sum(1 for _ in path.open(encoding="utf-8"))
        }
    )
    events = []
    with path.open(encoding="utf-8") as handle:
        for sequence, line in enumerate(handle, 1):
            event = json.loads(line)
            _validate_event(event, SUPER, sequence)
            events.append(event)
    profile = _profile_events(SUPER, events)
    if profile["quality_status"] != "pass":
        raise RuntimeError("共同第二區自適應資料品質失敗")
    split = _split_profile(
        len(events), config.mechanism_config()
    )
    predictions = build_prequential_predictions(
        events,
        warmup_draws=config.warmup_draws,
    )
    inner_start = (
        config.warmup_draws + split["inner_training_draws"]
    )
    development_end = (
        config.warmup_draws + split["development_draws"]
    )
    inner_indices = list(range(inner_start, development_end))
    inner_results = _evaluate_methods(
        events,
        inner_indices,
        predictions,
        METHODS,
        config=config,
        split="inner-validation",
    )
    selected_method, inner_eligible = _select_inner_candidate(
        inner_results
    )

    holdout_opened = selected_method is not None
    holdout = None
    historical_gate_passed = False
    forward_candidate = None
    if holdout_opened:
        holdout_indices = list(
            range(development_end, len(events))
        )
        selected_result = _evaluate_methods(
            events,
            holdout_indices,
            predictions,
            (selected_method,),
            config=config,
            split="holdout",
        )[selected_method]
        raw_p = {
            "special_hit": selected_result[
                "raw_one_sided_special_p_value"
            ],
            **{
                f"{portfolio_id}:strict_profit": row[
                    "raw_one_sided_sign_p_value"
                ]
                for portfolio_id, row in selected_result[
                    "portfolios"
                ].items()
            },
        }
        adjusted = _holm_adjust(raw_p)
        selected_result[
            "holm_adjusted_one_sided_p_values"
        ] = adjusted
        historical_gate_passed = (
            all(value < 0.05 for value in adjusted.values())
            and all(
                row["strict_profit_delta_ci_low"] > 0
                and row["first_half_strict_profit_delta"] >= 0
                and row["second_half_strict_profit_delta"] >= 0
                and row["mean_net_delta_ntd"] >= 0
                for row in selected_result[
                    "portfolios"
                ].values()
            )
        )
        holdout = {
            "status": "opened_for_inner_selected_candidate",
            "selected_method": selected_method,
            "result": selected_result,
            "historical_gate_passed": historical_gate_passed,
        }
        if historical_gate_passed:
            candidate_payload = {
                "experiment_id": FORWARD_EXPERIMENT_ID,
                "source_experiment_id": EXPERIMENT_ID,
                "game": SUPER,
                "method": selected_method,
                "protocol_hash": protocol_hash,
                "fitted_through": events[development_end - 1][
                    "reveal"
                ]["date"],
                "historical_evaluated_through": profile["last_date"],
                "promotion_eligible": False,
                "use": "future_forward_shadow_only",
                "guarded_profit_proof": deepcopy(GUARDED_PROOF),
                "unconstrained_profit_proof": deepcopy(
                    UNCONSTRAINED_PROOF
                ),
            }
            forward_candidate = {
                **candidate_payload,
                "candidate_hash": canonical_hash(
                    candidate_payload
                ),
            }
    else:
        holdout = {
            "status": "not_opened_no_inner_validation_candidate",
            "selected_method": None,
            "result": None,
            "historical_gate_passed": False,
        }

    records_after = tree_sha256(base / "records")
    if records_before != records_after:
        raise RuntimeError("自適應第二區研究不得改動正式 records")
    return {
        "schema_version": "1",
        "experiment_id": EXPERIMENT_ID,
        "generated_at": profile["last_date"] + "T23:59:59+08:00",
        "question": (
            "只讀嚴格過去資料的共同第二區自適應方法，能否同時提高"
            " guarded 與 unconstrained 五注嚴格獲利事件率？"
        ),
        "protocol": {
            "file": PROTOCOL_FILE,
            "sha256": protocol_hash,
            "candidate_methods": list(METHODS),
            "weekday_minimum_history": (
                WEEKDAY_MINIMUM_HISTORY
            ),
            "selection_rule": (
                "inner validation 需高於 1/8，且兩個結構嚴格獲利差"
                "皆正；依 min delta、mean delta、mean net、method 排序"
            ),
            "holdout_gate": (
                "三項 Holm p<0.05、兩結構 block-bootstrap 下界>0、"
                "前後半非負且平均壓力淨額非負"
            ),
            "historical_reuse": (
                "完整歷史已被先前研究使用；即使通過也只能建立未來"
                " forward shadow。"
            ),
        },
        "methodology": {
            "warmup_draws": config.warmup_draws,
            "development_fraction": config.development_fraction,
            "inner_training_fraction": (
                config.inner_training_fraction
            ),
            "bootstrap_samples": config.bootstrap_samples,
            "bootstrap_block_draws": config.bootstrap_block,
            "five_ticket_cost_ntd": FIVE_TICKET_COST_NTD,
            "empirical_floor_snapshot": deepcopy(
                EMPIRICAL_FLOOR_SNAPSHOT
            ),
            "guarded_profit_proof": deepcopy(GUARDED_PROOF),
            "unconstrained_profit_proof": deepcopy(
                UNCONSTRAINED_PROOF
            ),
        },
        "data_quality": {
            "status": profile["quality_status"],
            "profile": profile,
            "ledger_verification": verification,
            "split_profile": split,
        },
        "inner_validation": {
            "status": (
                "candidate_selected"
                if selected_method is not None
                else "no_inner_validation_candidate"
            ),
            "selected_method": selected_method,
            "eligible_methods": inner_eligible,
            "results": inner_results,
        },
        "holdout": holdout,
        "future_forward_shadow_candidate": forward_candidate,
        "conclusion": {
            "status": (
                "future_shadow_candidate_ready"
                if forward_candidate is not None
                else "retain_existing_common_special_methods"
            ),
            "historical_gate_passed": historical_gate_passed,
            "decision": (
                "建立獨立 v2 未來 shadow，不替換 v1 或辯論 baseline"
                if forward_candidate is not None
                else "不建立 v2；保留辯論 baseline 與既有固定 v1"
            ),
        },
        "records_integrity": {
            "before_sha256": records_before,
            "after_sha256": records_after,
            "unchanged": records_before == records_after,
        },
        "limitations": [
            "所有合法第二區在公平模型下理論機率相同。",
            "完整歷史已被其他研究查看，不能冒充全新確認樣本。",
            "歷史最低實領只是壓力測試，不是未來獎金保證。",
            "純模擬，不構成購買或下注建議。",
        ],
    }


def write_results(result: dict, output_dir: Path) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "adaptive_special_signal.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return path
