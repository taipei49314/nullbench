"""同一批 30 個共識主號如何分成五注的 walk-forward 封存研究。"""
from __future__ import annotations

import csv
from collections import Counter, deque
from dataclasses import dataclass
import json
import math
import os
from itertools import combinations
from pathlib import Path
import statistics

from engine.agent_loop import LOOP_EXPERIMENT_ID, verify_replay
from engine.games import GAME_NAMES, LOTTO649, SUPER
from engine.seeds import seed_int
from research.agent_ablation import (
    _validate_event,
    block_bootstrap_ci,
)
from research.gates import tree_sha256
from research.label_signal import _realized_metrics
from research.max_coverage import _special_ranking, _support_rows
from research.structural_optimum import structural_proof_reference


EXPERIMENT_ID = "partition-signal-shadow-v1"
PARTITIONER_NAMES = (
    "round_robin",
    "chunks",
    "snake",
    "proposal_affinity",
    "proposal_anti",
    "history_all_affinity",
    "history_all_anti",
    "history_52_affinity",
    "history_52_anti",
    "seeded_shuffle",
)
METRICS = ("best_main_hits", "any_three_plus", "any_prize")
PRIMARY_METRIC = "any_three_plus"
GUARDRAILS = ("best_main_hits", "any_prize")
DEFAULT_WARMUP_DRAWS = 60
DEFAULT_DEVELOPMENT_FRACTION = 0.70
DEFAULT_BOOTSTRAP_SAMPLES = 2_000
DEFAULT_BOOTSTRAP_BLOCK = 13


@dataclass(frozen=True)
class PartitionSignalConfig:
    warmup_draws: int = DEFAULT_WARMUP_DRAWS
    development_fraction: float = DEFAULT_DEVELOPMENT_FRACTION
    bootstrap_samples: int = DEFAULT_BOOTSTRAP_SAMPLES
    bootstrap_block: int = DEFAULT_BOOTSTRAP_BLOCK

    def validate(self) -> None:
        if self.warmup_draws < 1:
            raise ValueError("partition signal warmup 至少為 1")
        if not 0.5 <= self.development_fraction < 1:
            raise ValueError("development_fraction 必須介於 0.5 與 1")
        if self.bootstrap_samples < 100:
            raise ValueError("bootstrap_samples 至少為 100")
        if self.bootstrap_block < 1:
            raise ValueError("bootstrap_block 至少為 1")


def _initial_pair_state(game: str) -> dict:
    return {
        "game": game,
        "pair_counts": Counter(),
        "recent": deque(maxlen=52),
    }


def _update_pair_state(
    state: dict,
    numbers: list[int] | tuple[int, ...],
) -> None:
    values = tuple(sorted(int(number) for number in numbers))
    for pair in combinations(values, 2):
        state["pair_counts"][pair] += 1
    state["recent"].append(values)


def _greedy_groups(
    selected: list[int],
    pair_weights: Counter,
    *,
    maximize: bool,
) -> list[list[int]]:
    position = {
        number: index for index, number in enumerate(selected)
    }
    unassigned = set(selected)
    groups = []
    for _ in range(5):
        seed = min(unassigned, key=lambda number: position[number])
        unassigned.remove(seed)
        group = [seed]
        while len(group) < 6:
            def key(number: int) -> tuple:
                score = math.fsum(
                    pair_weights[
                        tuple(sorted((number, member)))
                    ]
                    for member in group
                )
                return (
                    -score if maximize else score,
                    position[number],
                    number,
                )

            chosen = min(unassigned, key=key)
            unassigned.remove(chosen)
            group.append(chosen)
        groups.append(group)
    return groups


def candidate_partitions(
    game: str,
    decision: dict,
    pair_state: dict,
) -> dict[str, list[list[int]]]:
    """只讀開獎前辯論與歷史 pair state，分割同一批 30 個主號。"""
    if game not in (SUPER, LOTTO649):
        raise ValueError(f"不支援的遊戲：{game}")
    if decision.get("game") != game:
        raise ValueError("partition decision 遊戲不符")
    if pair_state.get("game") != game:
        raise ValueError("partition pair state 遊戲不符")
    support_rows = _support_rows(game, decision)
    selected = [row["number"] for row in support_rows[:30]]
    selected_set = set(selected)
    round_robin = [selected[index::5] for index in range(5)]
    chunks = [
        selected[index * 6 : (index + 1) * 6]
        for index in range(5)
    ]
    snake = [[] for _ in range(5)]
    for block in range(6):
        bin_order = (
            range(5) if block % 2 == 0 else range(4, -1, -1)
        )
        for offset, bin_index in enumerate(bin_order):
            snake[bin_index].append(selected[block * 5 + offset])

    proposal_weights = Counter()
    scores = {
        row["proposal_id"]: float(row["debate_score"])
        for row in decision["adjudication"]["candidate_scores"]
    }
    for proposal in decision["proposals"]:
        values = [
            int(number)
            for number in proposal["numbers"]
            if int(number) in selected_set
        ]
        contribution = max(
            0.0, scores[proposal["proposal_id"]]
        ) + 1.0
        for pair in combinations(sorted(values), 2):
            proposal_weights[pair] += contribution

    recent_weights = Counter(
        pair
        for draw in pair_state["recent"]
        for pair in combinations(draw, 2)
    )
    shuffled = list(selected)
    import random

    random.Random(
        seed_int(
            f"{EXPERIMENT_ID}|{game}|"
            f"{decision['target']['period']}|seeded-shuffle"
        )
    ).shuffle(shuffled)
    partitions = {
        "round_robin": round_robin,
        "chunks": chunks,
        "snake": snake,
        "proposal_affinity": _greedy_groups(
            selected, proposal_weights, maximize=True
        ),
        "proposal_anti": _greedy_groups(
            selected, proposal_weights, maximize=False
        ),
        "history_all_affinity": _greedy_groups(
            selected,
            pair_state["pair_counts"],
            maximize=True,
        ),
        "history_all_anti": _greedy_groups(
            selected,
            pair_state["pair_counts"],
            maximize=False,
        ),
        "history_52_affinity": _greedy_groups(
            selected, recent_weights, maximize=True
        ),
        "history_52_anti": _greedy_groups(
            selected, recent_weights, maximize=False
        ),
        "seeded_shuffle": [
            shuffled[index * 6 : (index + 1) * 6]
            for index in range(5)
        ],
    }
    if tuple(partitions) != PARTITIONER_NAMES:
        raise RuntimeError("partitioner 集合或順序不符預註冊")
    for groups in partitions.values():
        if (
            len(groups) != 5
            or any(len(group) != 6 for group in groups)
            or set().union(*(set(group) for group in groups))
            != selected_set
            or sum(len(group) for group in groups) != 30
        ):
            raise RuntimeError("partitioner 未保持同一批 30 個互斥主號")
    return partitions


def _tickets_from_partition(
    game: str,
    decision: dict,
    groups: list[list[int]],
) -> list[dict]:
    if game == SUPER:
        support = {
            row["number"]: row["debate_support"]
            for row in _support_rows(game, decision)
        }
        group_support = [
            math.fsum(support[number] for number in group)
            for group in groups
        ]
        specials = [
            row["special"]
            for row in _special_ranking(decision)[:5]
        ]
        order = sorted(
            range(5),
            key=lambda index: (-group_support[index], index),
        )
        special_by_group = {
            group_index: specials[rank]
            for rank, group_index in enumerate(order)
        }
    else:
        special_by_group = {index: None for index in range(5)}
    return [
        {
            "numbers": sorted(group),
            "special": special_by_group[index],
        }
        for index, group in enumerate(groups)
    ]


def _split_profile(total: int, config: PartitionSignalConfig) -> dict:
    eligible = total - config.warmup_draws
    if eligible < 20:
        raise ValueError("partition signal 暖機後資料不足")
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


def _mean(
    rows: list[dict],
    partitioner: str,
    metric: str,
) -> float:
    return statistics.fmean(
        row[partitioner][metric] for row in rows
    )


def _choose_development_partitioner(
    rows: list[dict],
) -> str:
    baseline = {
        metric: _mean(rows, "round_robin", metric)
        for metric in METRICS
    }
    eligible = []
    for partitioner in PARTITIONER_NAMES:
        if partitioner == "round_robin":
            continue
        values = {
            metric: _mean(rows, partitioner, metric)
            for metric in METRICS
        }
        primary_delta = (
            values[PRIMARY_METRIC] - baseline[PRIMARY_METRIC]
        )
        if primary_delta > 0 and all(
            values[metric] >= baseline[metric] - 1e-15
            for metric in GUARDRAILS
        ):
            eligible.append(
                (
                    -primary_delta,
                    -(
                        values["best_main_hits"]
                        - baseline["best_main_hits"]
                    ),
                    partitioner,
                )
            )
    if not eligible:
        return "round_robin"
    eligible.sort()
    return eligible[0][2]


def _decision(
    game: str,
    selected: str,
    development: list[dict],
    holdout: list[dict],
    config: PartitionSignalConfig,
) -> dict:
    development_deltas = {
        metric: (
            _mean(development, selected, metric)
            - _mean(development, "round_robin", metric)
        )
        for metric in METRICS
    }
    holdout_vectors = {
        metric: [
            row[selected][metric] - row["round_robin"][metric]
            for row in holdout
        ]
        for metric in METRICS
    }
    holdout_deltas = {
        metric: statistics.fmean(values)
        for metric, values in holdout_vectors.items()
    }
    primary_ci = block_bootstrap_ci(
        holdout_vectors[PRIMARY_METRIC],
        samples=config.bootstrap_samples,
        block=config.bootstrap_block,
        seed=(
            f"{EXPERIMENT_ID}|{game}|{selected}|holdout|"
            f"{PRIMARY_METRIC}"
        ),
    )
    eligible = (
        selected != "round_robin"
        and primary_ci[0] > 0
        and all(
            holdout_deltas[metric] >= 0
            for metric in GUARDRAILS
        )
    )
    return {
        "development_selected_partitioner": selected,
        "development_deltas_vs_round_robin": development_deltas,
        "holdout_deltas_vs_round_robin": holdout_deltas,
        "holdout_any_three_plus_ci_low": primary_ci[0],
        "holdout_any_three_plus_ci_high": primary_ci[1],
        "promotion_eligible": eligible,
        "decision": (
            f"promote_{selected}"
            if eligible
            else "retain_round_robin"
        ),
    }


def run_partition_signal_study(
    ledger_paths: dict[str, Path],
    *,
    base: Path,
    config: PartitionSignalConfig | None = None,
    verify_ledgers: bool = True,
) -> dict:
    config = config or PartitionSignalConfig()
    config.validate()
    base = Path(base)
    records_before = tree_sha256(base / "records")
    split_profiles = {}
    ledger_verification = {}
    source_last_dates = {}
    summary = []
    decisions = {}
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
        pair_state = _initial_pair_state(game)
        eligible_rows = []
        last_date = None
        with path.open(encoding="utf-8") as handle:
            for sequence, line in enumerate(handle, 1):
                event = json.loads(line)
                _validate_event(event, game, sequence)
                decision = event["decision"]
                partitions = candidate_partitions(
                    game, decision, pair_state
                )
                if sequence > config.warmup_draws:
                    reveal = event["reveal"]
                    metrics = {
                        name: _realized_metrics(
                            game,
                            _tickets_from_partition(
                                game, decision, groups
                            ),
                            reveal,
                        )
                        for name, groups in partitions.items()
                    }
                    union_hits = {
                        row["union_main_hits"]
                        for row in metrics.values()
                    }
                    if len(union_hits) != 1:
                        raise RuntimeError(
                            "partitioner 改變了 30 號聯集"
                        )
                    eligible_rows.append(metrics)
                reveal = event["reveal"]
                _update_pair_state(pair_state, reveal["numbers"])
                last_date = reveal["date"]
        if len(eligible_rows) != profile["eligible_draws"]:
            raise RuntimeError("partition signal eligible 期數不符")
        source_last_dates[game] = last_date
        development_count = profile["development_draws"]
        split_rows = {
            "development": eligible_rows[:development_count],
            "holdout": eligible_rows[development_count:],
        }
        for split, rows in split_rows.items():
            for partitioner in PARTITIONER_NAMES:
                summary.append(
                    {
                        "game": game,
                        "game_name": GAME_NAMES[game],
                        "split": split,
                        "partitioner": partitioner,
                        "draws": len(rows),
                        **{
                            metric: _mean(
                                rows, partitioner, metric
                            )
                            for metric in METRICS
                        },
                        **{
                            f"{metric}_minus_round_robin": (
                                _mean(rows, partitioner, metric)
                                - _mean(
                                    rows,
                                    "round_robin",
                                    metric,
                                )
                            )
                            for metric in METRICS
                        },
                    }
                )
        selected = _choose_development_partitioner(
            split_rows["development"]
        )
        decisions[game] = _decision(
            game,
            selected,
            split_rows["development"],
            split_rows["holdout"],
            config,
        )

    records_after = tree_sha256(base / "records")
    if records_before != records_after:
        raise RuntimeError("partition signal 研究不應改動正式 records")
    promotion = all(
        row["promotion_eligible"] for row in decisions.values()
    )
    return {
        "schema_version": "1",
        "experiment_id": EXPERIMENT_ID,
        "source_experiment_id": LOOP_EXPERIMENT_ID,
        "generated_at": max(source_last_dates.values())
        + "T23:59:59+08:00",
        "question": (
            "同一批 30 個 Agent 共識主號，在保持五注完全互斥時，"
            "提案或歷史共現分組能否於封存 holdout 提高三主號事件？"
        ),
        "methodology": {
            "warmup_draws": config.warmup_draws,
            "development_fraction": config.development_fraction,
            "bootstrap_samples": config.bootstrap_samples,
            "bootstrap_block_draws": config.bootstrap_block,
            "partitioners": list(PARTITIONER_NAMES),
            "primary_metric": PRIMARY_METRIC,
            "guardrails": list(GUARDRAILS),
            "selection_rule": (
                "development 的 any_three_plus 嚴格提高，且最佳主號"
                "命中與完整任一獎級均不下降者才可進 holdout；"
                "holdout 區塊區間下界須大於 0 且護欄不下降。"
            ),
            "lookahead_control": (
                "candidate_partitions 不接受 reveal；歷史 pair state"
                "只在該期評分後更新。"
            ),
            "structural_invariance": (
                "所有候選使用完全相同的 30 個主號、五注各六號且"
                "兩兩互斥，精確理論結構機率完全相同。"
            ),
            "structural_optimum_proof": structural_proof_reference(),
        },
        "data_quality": {
            "status": "pass",
            "ledger_verification": ledger_verification,
            "split_profiles": split_profiles,
            "source_last_dates": source_last_dates,
        },
        "summary": summary,
        "development_selection_and_holdout": decisions,
        "conclusion": {
            "status": (
                "eligible_for_partition_upgrade"
                if promotion
                else "retain_round_robin_partition"
            ),
            "both_games_promotion_eligible": promotion,
            "decision_rule": (
                "禁止依 holdout 改選其他分組；未同時通過兩款遊戲"
                "就保留 round-robin。"
            ),
        },
        "records_integrity": {
            "before_sha256": records_before,
            "after_sha256": records_after,
            "unchanged": records_before == records_after,
        },
        "limitations": [
            "公平獨立開獎下，30 號的任何互斥五注分割理論機率相同。",
            "歷史共現只是假說，不能從單一 holdout 失敗後改選另一候選。",
            "純模擬，不構成購買或下注建議。",
        ],
    }


def write_results(result: dict, output_dir: Path) -> dict[str, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "json": output_dir / "partition_signal.json",
        "summary": output_dir / "partition_signal_summary.csv",
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
