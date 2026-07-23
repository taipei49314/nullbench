"""完全分散五注中的 30 個號碼標籤是否具有前向可重現訊號。"""
from __future__ import annotations

import csv
from collections import Counter, deque
from copy import deepcopy
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import statistics

from engine.agent_loop import LOOP_EXPERIMENT_ID, verify_replay
from engine.games import (
    GAME_NAMES,
    LOTTO649,
    PICK_N,
    POOL,
    SUPER,
)
from research.agent_ablation import (
    _validate_event,
    block_bootstrap_ci,
)
from research.gates import tree_sha256
from research.max_coverage import _special_ranking, _support_rows
from research.structural_optimum import structural_proof_reference


EXPERIMENT_ID = "label-signal-shadow-v1"
SELECTED_MAIN_NUMBERS = 30
WINDOWS = (13, 26, 52, 104)
DEFAULT_WARMUP_DRAWS = 60
DEFAULT_DEVELOPMENT_FRACTION = 0.70
DEFAULT_BOOTSTRAP_SAMPLES = 2_000
DEFAULT_BOOTSTRAP_BLOCK = 13
RANKER_NAMES = (
    "consensus",
    "hot_all",
    "gap",
    "hot_13",
    "cold_13",
    "mix_13",
    "hot_26",
    "cold_26",
    "mix_26",
    "hot_52",
    "cold_52",
    "mix_52",
    "hot_104",
    "cold_104",
    "mix_104",
)
METRICS = (
    "union_main_hits",
    "best_main_hits",
    "any_three_plus",
    "any_prize",
)
GUARDRAILS = (
    "best_main_hits",
    "any_three_plus",
    "any_prize",
)


@dataclass(frozen=True)
class LabelSignalConfig:
    warmup_draws: int = DEFAULT_WARMUP_DRAWS
    development_fraction: float = DEFAULT_DEVELOPMENT_FRACTION
    bootstrap_samples: int = DEFAULT_BOOTSTRAP_SAMPLES
    bootstrap_block: int = DEFAULT_BOOTSTRAP_BLOCK

    def validate(self) -> None:
        if self.warmup_draws < 1:
            raise ValueError("label signal warmup 至少為 1")
        if not 0.5 <= self.development_fraction < 1:
            raise ValueError("development_fraction 必須介於 0.5 與 1")
        if self.bootstrap_samples < 100:
            raise ValueError("bootstrap_samples 至少為 100")
        if self.bootstrap_block < 1:
            raise ValueError("bootstrap_block 至少為 1")


def _initial_history_state(game: str) -> dict:
    return {
        "game": game,
        "draw_index": 0,
        "counts": Counter(),
        "last_seen": {
            number: -1
            for number in range(1, POOL[game] + 1)
        },
        "recent": deque(maxlen=max(WINDOWS)),
    }


def _update_history_state(
    state: dict,
    numbers: list[int] | tuple[int, ...],
) -> None:
    for number in numbers:
        value = int(number)
        state["counts"][value] += 1
        state["last_seen"][value] = state["draw_index"]
    state["recent"].append(tuple(int(number) for number in numbers))
    state["draw_index"] += 1


def candidate_rankings(
    game: str,
    decision: dict,
    history_state: dict,
) -> dict[str, list[int]]:
    """只使用目標期以前的狀態與已封存辯論建立 15 種排序。"""
    if game not in (SUPER, LOTTO649):
        raise ValueError(f"不支援的遊戲：{game}")
    if decision.get("game") != game:
        raise ValueError("label ranker decision 遊戲不符")
    if history_state.get("game") != game:
        raise ValueError("label ranker 歷史狀態遊戲不符")
    all_numbers = list(range(1, POOL[game] + 1))
    consensus = [
        row["number"] for row in _support_rows(game, decision)
    ]
    consensus_position = {
        number: position
        for position, number in enumerate(consensus)
    }
    counts = history_state["counts"]
    rankings = {
        "consensus": consensus,
        "hot_all": sorted(
            all_numbers,
            key=lambda number: (-counts[number], number),
        ),
        "gap": sorted(
            all_numbers,
            key=lambda number: (
                -(
                    history_state["draw_index"]
                    - history_state["last_seen"][number]
                ),
                number,
            ),
        ),
    }
    recent = list(history_state["recent"])
    for window in WINDOWS:
        window_counts = Counter(
            number
            for draw in recent[-window:]
            for number in draw
        )
        hot = sorted(
            all_numbers,
            key=lambda number: (-window_counts[number], number),
        )
        cold = sorted(
            all_numbers,
            key=lambda number: (window_counts[number], number),
        )
        hot_position = {
            number: position
            for position, number in enumerate(hot)
        }
        mix = sorted(
            all_numbers,
            key=lambda number: (
                consensus_position[number] + hot_position[number],
                consensus_position[number],
                number,
            ),
        )
        rankings[f"hot_{window}"] = hot
        rankings[f"cold_{window}"] = cold
        rankings[f"mix_{window}"] = mix
    if tuple(rankings) != RANKER_NAMES:
        raise RuntimeError("label ranker 集合或順序不符預註冊")
    if any(
        sorted(ranking) != all_numbers
        for ranking in rankings.values()
    ):
        raise RuntimeError("label ranker 未形成完整號碼排列")
    return rankings


def _tickets_from_ranking(
    game: str,
    decision: dict,
    ranking: list[int],
) -> list[dict]:
    selected = ranking[:SELECTED_MAIN_NUMBERS]
    if len(set(selected)) != SELECTED_MAIN_NUMBERS:
        raise RuntimeError("label ranker 前 30 個號碼不唯一")
    bins = [[] for _ in range(5)]
    for index, number in enumerate(selected):
        bins[index % 5].append(number)

    if game == SUPER:
        support = {
            row["number"]: row["debate_support"]
            for row in _support_rows(game, decision)
        }
        bin_support = [
            math.fsum(support[number] for number in numbers)
            for numbers in bins
        ]
        specials = [
            row["special"]
            for row in _special_ranking(decision)[:5]
        ]
        bin_order = sorted(
            range(5),
            key=lambda index: (-bin_support[index], index),
        )
        special_by_bin = {
            bin_index: specials[rank]
            for rank, bin_index in enumerate(bin_order)
        }
    else:
        special_by_bin = {index: None for index in range(5)}
    return [
        {
            "numbers": sorted(numbers),
            "special": special_by_bin[index],
        }
        for index, numbers in enumerate(bins)
    ]


def _realized_metrics(
    game: str,
    tickets: list[dict],
    reveal: dict,
) -> dict[str, float]:
    drawn = set(int(number) for number in reveal["numbers"])
    hits = [
        len(set(ticket["numbers"]) & drawn)
        for ticket in tickets
    ]
    if game == SUPER:
        any_prize = any(
            hit >= 3
            or (
                hit in (1, 2)
                and ticket["special"] == int(reveal["special"])
            )
            for hit, ticket in zip(hits, tickets)
        )
    else:
        bonus = int(reveal["special"])
        any_prize = any(
            hit >= 3
            or (hit == 2 and bonus in set(ticket["numbers"]))
            for hit, ticket in zip(hits, tickets)
        )
    return {
        "union_main_hits": float(
            len(
                set().union(
                    *(set(ticket["numbers"]) for ticket in tickets)
                )
                & drawn
            )
        ),
        "best_main_hits": float(max(hits)),
        "any_three_plus": float(max(hits) >= 3),
        "any_prize": float(any_prize),
    }


def _split_profile(total: int, config: LabelSignalConfig) -> dict:
    eligible = total - config.warmup_draws
    if eligible < 20:
        raise ValueError("label signal 暖機後資料不足")
    development = math.floor(
        eligible * config.development_fraction
    )
    return {
        "total_draws": total,
        "warmup_draws": config.warmup_draws,
        "eligible_draws": eligible,
        "development_draws": development,
        "holdout_draws": eligible - development,
    }


def _mean(rows: list[dict], ranker: str, metric: str) -> float:
    return statistics.fmean(
        row[ranker][metric] for row in rows
    )


def _metric_rows(
    game: str,
    split: str,
    rows: list[dict],
) -> list[dict]:
    return [
        {
            "game": game,
            "game_name": GAME_NAMES[game],
            "split": split,
            "ranker": ranker,
            "draws": len(rows),
            **{
                metric: _mean(rows, ranker, metric)
                for metric in METRICS
            },
            **{
                f"{metric}_minus_consensus": (
                    _mean(rows, ranker, metric)
                    - _mean(rows, "consensus", metric)
                )
                for metric in METRICS
            },
        }
        for ranker in RANKER_NAMES
    ]


def _choose_development_ranker(
    rows: list[dict],
) -> tuple[str, list[str]]:
    baseline = {
        metric: _mean(rows, "consensus", metric)
        for metric in METRICS
    }
    eligible = []
    rejected = []
    for ranker in RANKER_NAMES:
        if ranker == "consensus":
            continue
        values = {
            metric: _mean(rows, ranker, metric)
            for metric in METRICS
        }
        primary_delta = (
            values["union_main_hits"]
            - baseline["union_main_hits"]
        )
        guardrails_pass = all(
            values[metric] >= baseline[metric] - 1e-15
            for metric in GUARDRAILS
        )
        if primary_delta > 0 and guardrails_pass:
            eligible.append(
                (
                    -primary_delta,
                    -sum(
                        values[metric] - baseline[metric]
                        for metric in GUARDRAILS
                    ),
                    ranker,
                )
            )
        else:
            rejected.append(ranker)
    if not eligible:
        return "consensus", rejected
    eligible.sort()
    return eligible[0][2], rejected


def _holdout_candidate_decision(
    game: str,
    ranker: str,
    development_rows: list[dict],
    holdout_rows: list[dict],
    config: LabelSignalConfig,
) -> dict:
    deltas = {
        metric: [
            row[ranker][metric] - row["consensus"][metric]
            for row in holdout_rows
        ]
        for metric in METRICS
    }
    primary_ci = block_bootstrap_ci(
        deltas["union_main_hits"],
        samples=config.bootstrap_samples,
        block=config.bootstrap_block,
        seed=(
            f"{EXPERIMENT_ID}|{game}|{ranker}|holdout|"
            "union-main-hits"
        ),
    )
    development_deltas = {
        metric: (
            _mean(development_rows, ranker, metric)
            - _mean(development_rows, "consensus", metric)
        )
        for metric in METRICS
    }
    holdout_deltas = {
        metric: statistics.fmean(values)
        for metric, values in deltas.items()
    }
    eligible = (
        ranker != "consensus"
        and primary_ci[0] > 0
        and all(
            holdout_deltas[metric] >= 0
            for metric in GUARDRAILS
        )
    )
    return {
        "development_selected_ranker": ranker,
        "development_deltas_vs_consensus": development_deltas,
        "holdout_deltas_vs_consensus": holdout_deltas,
        "holdout_union_main_hits_ci_low": primary_ci[0],
        "holdout_union_main_hits_ci_high": primary_ci[1],
        "promotion_eligible": eligible,
        "decision": (
            f"promote_{ranker}"
            if eligible
            else "retain_consensus"
        ),
    }


def _hypergeometric_total_upper_tail(
    *,
    pool: int,
    selected: int,
    drawn: int,
    periods: int,
    observed: int,
) -> float:
    denominator = math.comb(pool, drawn)
    single = [
        (
            math.comb(selected, hits)
            * math.comb(pool - selected, drawn - hits)
            / denominator
        )
        if 0 <= drawn - hits <= pool - selected
        else 0.0
        for hits in range(drawn + 1)
    ]
    distribution = [1.0]
    for _ in range(periods):
        next_distribution = [0.0] * (
            len(distribution) + drawn
        )
        for total, probability in enumerate(distribution):
            for hits, hit_probability in enumerate(single):
                next_distribution[total + hits] += (
                    probability * hit_probability
                )
        distribution = next_distribution
    return min(1.0, math.fsum(distribution[observed:]))


def _binomial_upper_tail(
    periods: int,
    observed: int,
    probability: float,
) -> float:
    return min(
        1.0,
        math.fsum(
            math.comb(periods, successes)
            * probability**successes
            * (1 - probability) ** (periods - successes)
            for successes in range(observed, periods + 1)
        ),
    )


def _holm_adjust(raw: dict[str, float]) -> dict[str, float]:
    ordered = sorted(raw.items(), key=lambda item: (item[1], item[0]))
    total = len(ordered)
    adjusted = {}
    running = 0.0
    for index, (name, value) in enumerate(ordered):
        running = max(running, min(1.0, (total - index) * value))
        adjusted[name] = running
    return adjusted


def _consensus_null_evidence(
    game: str,
    rows: list[dict],
    exact_probabilities: dict,
) -> tuple[dict, dict[str, float]]:
    periods = len(rows)
    union_total = round(
        sum(row["consensus"]["union_main_hits"] for row in rows)
    )
    any_three_total = round(
        sum(row["consensus"]["any_three_plus"] for row in rows)
    )
    any_prize_total = round(
        sum(row["consensus"]["any_prize"] for row in rows)
    )
    expected_union = periods * PICK_N * SELECTED_MAIN_NUMBERS / POOL[
        game
    ]
    raw = {
        "union_main_hits": _hypergeometric_total_upper_tail(
            pool=POOL[game],
            selected=SELECTED_MAIN_NUMBERS,
            drawn=PICK_N,
            periods=periods,
            observed=union_total,
        ),
        "any_three_plus": _binomial_upper_tail(
            periods,
            any_three_total,
            exact_probabilities["three_main"],
        ),
        "any_prize": _binomial_upper_tail(
            periods,
            any_prize_total,
            exact_probabilities["any_prize"],
        ),
    }
    return {
        "draws": periods,
        "union_main_hits_observed_total": union_total,
        "union_main_hits_observed_mean": union_total / periods,
        "union_main_hits_exact_null_mean": (
            expected_union / periods
        ),
        "union_main_hits_excess_total": (
            union_total - expected_union
        ),
        "any_three_plus_observed": any_three_total,
        "any_three_plus_exact_null_probability": (
            exact_probabilities["three_main"]
        ),
        "any_prize_observed": any_prize_total,
        "any_prize_exact_null_probability": (
            exact_probabilities["any_prize"]
        ),
        "raw_one_sided_p_values": raw,
    }, {
        f"{game}:{metric}": value
        for metric, value in raw.items()
    }


def run_label_signal_study(
    ledger_paths: dict[str, Path],
    *,
    base: Path,
    config: LabelSignalConfig | None = None,
    verify_ledgers: bool = True,
) -> dict:
    """逐期 walk-forward 稽核標籤排序，不讓 holdout 參與選模。"""
    config = config or LabelSignalConfig()
    config.validate()
    base = Path(base)
    records_before = tree_sha256(base / "records")
    split_profiles = {}
    ledger_verification = {}
    source_last_dates = {}
    all_metric_rows = []
    decisions = {}
    holdout_rows_by_game = {}

    proof_path = (
        base / "research" / "results" / "structural_optimum.json"
    )
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    if (
        proof.get("certificate_hash")
        != structural_proof_reference()["certificate_hash"]
    ):
        raise RuntimeError("label signal 結構證明來源不符")

    for game in (SUPER, LOTTO649):
        path = Path(ledger_paths[game])
        verification = (
            verify_replay(path)
            if verify_ledgers
            else {"lines": sum(1 for _ in path.open(encoding="utf-8"))}
        )
        ledger_verification[game] = verification
        profile = _split_profile(verification["lines"], config)
        split_profiles[game] = profile
        state = _initial_history_state(game)
        eligible_rows = []
        last_date = None
        with path.open(encoding="utf-8") as handle:
            for sequence, line in enumerate(handle, 1):
                event = json.loads(line)
                _validate_event(event, game, sequence)
                decision = event["decision"]
                rankings = candidate_rankings(game, decision, state)
                if sequence > config.warmup_draws:
                    reveal = event["reveal"]
                    eligible_rows.append(
                        {
                            ranker: _realized_metrics(
                                game,
                                _tickets_from_ranking(
                                    game, decision, ranking
                                ),
                                reveal,
                            )
                            for ranker, ranking in rankings.items()
                        }
                    )
                reveal = event["reveal"]
                _update_history_state(state, reveal["numbers"])
                last_date = reveal["date"]
        if len(eligible_rows) != profile["eligible_draws"]:
            raise RuntimeError("label signal eligible 期數不符")
        source_last_dates[game] = last_date
        development_count = profile["development_draws"]
        development_rows = eligible_rows[:development_count]
        holdout_rows = eligible_rows[development_count:]
        holdout_rows_by_game[game] = holdout_rows
        all_metric_rows.extend(
            _metric_rows(game, "development", development_rows)
        )
        all_metric_rows.extend(
            _metric_rows(game, "holdout", holdout_rows)
        )
        selected, rejected = _choose_development_ranker(
            development_rows
        )
        decisions[game] = {
            **_holdout_candidate_decision(
                game,
                selected,
                development_rows,
                holdout_rows,
                config,
            ),
            "development_rejected_rankers": rejected,
        }

    null_evidence = {}
    raw_p_values = {}
    for game in (SUPER, LOTTO649):
        exact = {
            "any_prize": proof["games"][game]["any_prize"][
                "global_maximum_probability"
            ],
            "three_main": proof["games"][game]["three_main"][
                "global_maximum_probability"
            ],
        }
        evidence, raw = _consensus_null_evidence(
            game,
            holdout_rows_by_game[game],
            exact,
        )
        null_evidence[game] = evidence
        raw_p_values.update(raw)
    adjusted = _holm_adjust(raw_p_values)
    for game, evidence in null_evidence.items():
        evidence["holm_adjusted_one_sided_p_values"] = {
            metric: adjusted[f"{game}:{metric}"]
            for metric in (
                "union_main_hits",
                "any_three_plus",
                "any_prize",
            )
        }
        evidence["predictive_label_signal_supported"] = (
            evidence["holm_adjusted_one_sided_p_values"][
                "union_main_hits"
            ]
            < 0.05
        )

    records_after = tree_sha256(base / "records")
    if records_before != records_after:
        raise RuntimeError("label signal 研究不應改動正式 records")
    promotion = all(
        decision["promotion_eligible"]
        for decision in decisions.values()
    )
    return {
        "schema_version": "1",
        "experiment_id": EXPERIMENT_ID,
        "source_experiment_id": LOOP_EXPERIMENT_ID,
        "generated_at": max(source_last_dates.values())
        + "T23:59:59+08:00",
        "question": (
            "在全域最優的完全分散結構內，歷史頻率、間隔或與 Agent"
            "共識混合的 30 號標籤排序，能否在封存 holdout 穩定勝過"
            "現行 Agent 共識？"
        ),
        "methodology": {
            "warmup_draws": config.warmup_draws,
            "development_fraction": config.development_fraction,
            "bootstrap_samples": config.bootstrap_samples,
            "bootstrap_block_draws": config.bootstrap_block,
            "rankers": list(RANKER_NAMES),
            "primary_metric": "union_main_hits",
            "guardrails": list(GUARDRAILS),
            "selection_rule": (
                "development 中 union_main_hits 嚴格提高且三個護欄"
                "均不下降者才可成為單一候選；holdout 配對區塊"
                "bootstrap 下界須大於 0 且護欄均不下降。"
            ),
            "multiple_testing": (
                "Agent 共識對精確均勻零模型的兩遊戲三指標使用"
                "Holm family-wise correction。"
            ),
            "lookahead_control": (
                "candidate_rankings 不接受 reveal；每期評分後才更新"
                "頻率、近期視窗與 last-seen 狀態。"
            ),
            "structural_optimum_proof": structural_proof_reference(),
        },
        "data_quality": {
            "status": "pass",
            "ledger_verification": ledger_verification,
            "split_profiles": split_profiles,
            "source_last_dates": source_last_dates,
        },
        "summary": all_metric_rows,
        "development_selection_and_holdout": decisions,
        "consensus_holdout_vs_exact_uniform_null": null_evidence,
        "conclusion": {
            "status": (
                "eligible_for_label_ranker_upgrade"
                if promotion
                else "retain_consensus_label_ranking"
            ),
            "both_games_promotion_eligible": promotion,
            "decision_rule": (
                "禁止依 holdout 改選另一個 ranker；未同時通過兩款"
                "遊戲就保留 Agent 共識標籤排序。"
            ),
        },
        "records_integrity": {
            "before_sha256": records_before,
            "after_sha256": records_after,
            "unchanged": records_before == records_after,
        },
        "limitations": [
            "公平獨立開獎下每個號碼標籤理論等機率；歷史 ranker 只是假說。",
            "同一歷史已被多次研究，只有未來 forward 樣本能提供新確認。",
            "標籤排序不改變完全分散五注的精確結構機率。",
            "純模擬，不構成購買或下注建議。",
        ],
    }


def write_results(result: dict, output_dir: Path) -> dict[str, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "json": output_dir / "label_signal.json",
        "summary": output_dir / "label_signal_summary.csv",
    }
    temporary = paths["json"].with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, paths["json"])
    rows = result["summary"]
    with paths["summary"].open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return paths
