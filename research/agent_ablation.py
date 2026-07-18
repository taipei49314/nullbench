"""Agent 數量消融研究。

這個模組只讀逐期 agent-loop JSONL 帳本，重用每期開獎前已封存的提案與評論，
比較 2、3、4、5 人子議會在固定五注預算下的表現。實際開獎只用於當期決策完成後
的評分與下一期評等更新，不會進入當期裁決。
"""
from __future__ import annotations

import csv
import json
import math
import random
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Iterable

from engine.agent_loop import (
    AGENT_IDS,
    LEARNING_RATE,
    LOOP_EXPERIMENT_ID,
    RATING_RANGE,
    SELECTED_TICKETS,
    _adjudicate,
    verify_replay,
)
from engine.games import (
    GAME_NAMES,
    LOTTO649,
    PICK_N,
    POOL,
    SPECIAL_POOL,
    SUPER,
    Draw,
    match_tier,
)
from engine.seeds import seed_int
from research.gates import tree_sha256


EXPERIMENT_ID = "agent-count-ablation-v1"
PRIMARY_METRIC = "best_main_hits"
METRICS = (
    PRIMARY_METRIC,
    "total_main_hits",
    "any_three_plus",
    "special_hit_tickets",
    "winning_tickets",
    "any_prize",
    "union_main_hits",
    "union_size",
)
DEFAULT_WARMUP_DRAWS = 60
DEFAULT_DEVELOPMENT_FRACTION = 0.70
DEFAULT_NULL_REPLICATES = 200
DEFAULT_BOOTSTRAP_SAMPLES = 2_000
DEFAULT_BOOTSTRAP_BLOCK = 13


@dataclass(frozen=True)
class AblationConfig:
    warmup_draws: int = DEFAULT_WARMUP_DRAWS
    development_fraction: float = DEFAULT_DEVELOPMENT_FRACTION
    null_replicates: int = DEFAULT_NULL_REPLICATES
    bootstrap_samples: int = DEFAULT_BOOTSTRAP_SAMPLES
    bootstrap_block: int = DEFAULT_BOOTSTRAP_BLOCK

    def validate(self) -> None:
        if self.warmup_draws < 0:
            raise ValueError("warmup_draws 不得為負")
        if not 0.5 <= self.development_fraction < 1.0:
            raise ValueError("development_fraction 必須介於 0.5（含）與 1 之間")
        if self.null_replicates < 2:
            raise ValueError("null_replicates 至少為 2")
        if self.bootstrap_samples < 100:
            raise ValueError("bootstrap_samples 至少為 100")
        if self.bootstrap_block < 1:
            raise ValueError("bootstrap_block 至少為 1")


def agent_subsets() -> tuple[tuple[str, ...], ...]:
    """回傳 2 至 5 人的全部 26 個組合，順序固定。"""
    return tuple(
        subset
        for size in range(2, len(AGENT_IDS) + 1)
        for subset in combinations(AGENT_IDS, size)
    )


def subset_id(subset: Iterable[str]) -> str:
    return "+".join(subset)


def _initial_ratings() -> dict[str, float]:
    return {agent: 1.0 for agent in AGENT_IDS}


def _state_for_adjudicator(ratings: dict[str, float]) -> dict:
    return {
        "agents": {
            agent: {"rating": float(ratings[agent])}
            for agent in AGENT_IDS
        }
    }


def _filter_council(
    proposals: list[dict],
    critiques: list[dict],
    subset: tuple[str, ...],
) -> tuple[list[dict], list[dict]]:
    members = set(subset)
    filtered_proposals = [
        proposal for proposal in proposals if proposal["agent"] in members
    ]
    proposal_ids = {
        proposal["proposal_id"] for proposal in filtered_proposals
    }
    filtered_critiques = [
        critique
        for critique in critiques
        if critique["critic"] in members and critique["target"] in proposal_ids
    ]
    return filtered_proposals, filtered_critiques


def adjudicate_council(
    proposals: list[dict],
    critiques: list[dict],
    ratings: dict[str, float],
    subset: tuple[str, ...],
) -> list[dict]:
    """只讓指定成員提案與互評，固定選出五注。"""
    filtered_proposals, filtered_critiques = _filter_council(
        proposals, critiques, subset
    )
    expected_proposals = len(subset) * 3
    expected_critiques = len(subset) * (len(subset) - 1) * 3
    if len(filtered_proposals) != expected_proposals:
        raise ValueError(
            f"{subset_id(subset)} 提案數不符："
            f"{len(filtered_proposals)} != {expected_proposals}"
        )
    if len(filtered_critiques) != expected_critiques:
        raise ValueError(
            f"{subset_id(subset)} 評論數不符："
            f"{len(filtered_critiques)} != {expected_critiques}"
        )
    tickets, _, _ = _adjudicate(
        filtered_proposals,
        filtered_critiques,
        _state_for_adjudicator(ratings),
    )
    if len(tickets) != SELECTED_TICKETS:
        raise AssertionError("子議會未選出五注")
    if any(ticket["source_agent"] not in subset for ticket in tickets):
        raise AssertionError("子議會選到非成員提案")
    return tickets


def _proposal_qualities(
    game: str,
    proposals: list[dict],
    reveal: dict,
) -> dict[str, float]:
    actual = set(reveal["numbers"])
    by_agent: dict[str, list[float]] = defaultdict(list)
    for proposal in proposals:
        main_hits = len(set(proposal["numbers"]) & actual)
        special_hit = (
            proposal["special"] == reveal["special"]
            if game == SUPER
            else reveal["special"] in proposal["numbers"]
        )
        by_agent[proposal["agent"]].append(
            main_hits + (0.25 if special_hit else 0.0)
        )
    if set(by_agent) != set(AGENT_IDS):
        raise ValueError("提案未涵蓋全部 Agent")
    return {agent: max(values) for agent, values in by_agent.items()}


def update_subset_ratings(
    ratings: dict[str, float],
    qualities: dict[str, float],
    subset: tuple[str, ...],
) -> dict[str, float]:
    """依當期揭曉後結果更新子議會評等；正規化只在子議會內進行。"""
    next_ratings = dict(ratings)
    mean_quality = statistics.fmean(qualities[agent] for agent in subset)
    raw = {
        agent: ratings[agent]
        * math.exp(LEARNING_RATE * (qualities[agent] - mean_quality))
        for agent in subset
    }
    mean_rating = statistics.fmean(raw.values())
    for agent in subset:
        next_ratings[agent] = min(
            RATING_RANGE[1],
            max(RATING_RANGE[0], raw[agent] / mean_rating),
        )
    return next_ratings


def portfolio_metrics(game: str, tickets: list[dict], reveal: dict) -> dict[str, float]:
    """在固定五注粒度計算命中與分散度；不估算獎金。"""
    if len(tickets) != SELECTED_TICKETS:
        raise ValueError(f"每期必須恰好 {SELECTED_TICKETS} 注")
    draw = Draw(
        game=game,
        period=int(reveal["period"]),
        date=reveal["date"],
        numbers=tuple(reveal["numbers"]),
        special=int(reveal["special"]),
    )
    actual = set(draw.numbers)
    main_hits: list[int] = []
    special_hits: list[bool] = []
    winning = 0
    union: set[int] = set()
    for ticket in tickets:
        numbers = list(ticket["numbers"])
        union.update(numbers)
        main_hits.append(len(set(numbers) & actual))
        special_hit = (
            ticket["special"] == draw.special
            if game == SUPER
            else draw.special in numbers
        )
        special_hits.append(special_hit)
        if match_tier(game, numbers, ticket["special"], draw) is not None:
            winning += 1
    return {
        "best_main_hits": float(max(main_hits)),
        "total_main_hits": float(sum(main_hits)),
        "any_three_plus": float(max(main_hits) >= 3),
        "special_hit_tickets": float(sum(special_hits)),
        "winning_tickets": float(winning),
        "any_prize": float(winning > 0),
        "union_main_hits": float(len(union & actual)),
        "union_size": float(len(union)),
    }


def _random_portfolio(
    game: str,
    period: int,
    replicate: int,
) -> list[dict]:
    rng = random.Random(
        seed_int(
            f"lotto-lab|{EXPERIMENT_ID}|{game}|period{period}|"
            f"uniform-null|replicate{replicate}"
        )
    )
    tickets: list[dict] = []
    seen: set[tuple[int, ...]] = set()
    while len(tickets) < SELECTED_TICKETS:
        numbers = tuple(sorted(rng.sample(range(1, POOL[game] + 1), PICK_N)))
        if numbers in seen:
            continue
        seen.add(numbers)
        tickets.append(
            {
                "numbers": list(numbers),
                "special": (
                    rng.randint(1, SPECIAL_POOL[SUPER])
                    if game == SUPER
                    else None
                ),
            }
        )
    return tickets


def random_baseline_metrics(
    game: str,
    reveal: dict,
    replicates: int,
) -> dict[str, float]:
    values = {metric: [] for metric in METRICS}
    for replicate in range(replicates):
        result = portfolio_metrics(
            game,
            _random_portfolio(game, int(reveal["period"]), replicate),
            reveal,
        )
        for metric in METRICS:
            values[metric].append(result[metric])
    return {
        metric: statistics.fmean(metric_values)
        for metric, metric_values in values.items()
    }


def _quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def block_bootstrap_ci(
    differences: list[float],
    *,
    samples: int,
    block: int,
    seed: str,
) -> tuple[float, float]:
    """以循環連續區塊 bootstrap 計算配對平均差的 95% 區間。"""
    if not differences:
        raise ValueError("bootstrap 沒有資料")
    if len(differences) == 1:
        return differences[0], differences[0]
    rng = random.Random(seed_int(seed))
    n = len(differences)
    block = min(block, n)
    blocks_needed = math.ceil(n / block)
    final_block = n - block * (blocks_needed - 1)
    full_block_sums = [
        sum(differences[(start + offset) % n] for offset in range(block))
        for start in range(n)
    ]
    final_block_sums = [
        sum(
            differences[(start + offset) % n]
            for offset in range(final_block)
        )
        for start in range(n)
    ]
    means = []
    for _ in range(samples):
        total = sum(
            full_block_sums[rng.randrange(n)]
            for _ in range(blocks_needed - 1)
        )
        total += final_block_sums[rng.randrange(n)]
        means.append(total / n)
    return _quantile(means, 0.025), _quantile(means, 0.975)


def _event_count(path: Path) -> int:
    with path.open(encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def _validate_event(event: dict, game: str, sequence: int) -> None:
    decision = event["decision"]
    reveal = event["reveal"]
    if event["sequence"] != sequence:
        raise ValueError(f"{game} 第 {sequence} 筆 sequence 不連續")
    if decision["game"] != game:
        raise ValueError(f"{game} 第 {sequence} 筆遊戲不符")
    if decision["experiment_id"] != LOOP_EXPERIMENT_ID:
        raise ValueError(f"{game} 第 {sequence} 筆實驗版本不符")
    if decision["history_count"] != sequence - 1:
        raise ValueError(f"{game} 第 {sequence} 筆歷史期數可能洩漏")
    if decision["target"] != {
        "date": reveal["date"],
        "period": reveal["period"],
    }:
        raise ValueError(f"{game} 第 {sequence} 筆決策與揭曉期別不符")
    proposal_counts = Counter(
        proposal["agent"] for proposal in decision["proposals"]
    )
    if proposal_counts != Counter({agent: 3 for agent in AGENT_IDS}):
        raise ValueError(f"{game} 第 {sequence} 筆提案配置不完整")
    expected_critiques = len(AGENT_IDS) * (len(AGENT_IDS) - 1) * 3
    if len(decision["critiques"]) != expected_critiques:
        raise ValueError(f"{game} 第 {sequence} 筆交叉評論不完整")


def _summarize_values(values: dict[str, list[float]]) -> dict[str, float]:
    return {
        metric: statistics.fmean(values[metric])
        for metric in METRICS
    }


def _paired_differences(
    left: list[float],
    right: list[float],
) -> list[float]:
    if len(left) != len(right):
        raise ValueError("配對序列長度不一致")
    return [a - b for a, b in zip(left, right)]


def _summaries(
    subset_values: dict,
    count_values: dict,
    baseline_values: dict,
    config: AblationConfig,
) -> tuple[list[dict], list[dict], list[dict], dict]:
    count_rows: list[dict] = []
    subset_rows: list[dict] = []
    baseline_rows: list[dict] = []

    for (game, split), metric_values in sorted(baseline_values.items()):
        baseline_rows.append(
            {
                "game": game,
                "game_name": GAME_NAMES[game],
                "split": split,
                "draws": len(metric_values[PRIMARY_METRIC]),
                **_summarize_values(metric_values),
            }
        )

    for (game, split, size), metric_values in sorted(count_values.items()):
        baseline = baseline_values[(game, split)]
        primary_diff = _paired_differences(
            metric_values[PRIMARY_METRIC],
            baseline[PRIMARY_METRIC],
        )
        ci_low, ci_high = block_bootstrap_ci(
            primary_diff,
            samples=config.bootstrap_samples,
            block=config.bootstrap_block,
            seed=f"{EXPERIMENT_ID}|{game}|{split}|count{size}|vs-null",
        )
        two_values = count_values[(game, split, 2)][PRIMARY_METRIC]
        versus_two = _paired_differences(
            metric_values[PRIMARY_METRIC],
            two_values,
        )
        two_ci_low, two_ci_high = block_bootstrap_ci(
            versus_two,
            samples=config.bootstrap_samples,
            block=config.bootstrap_block,
            seed=f"{EXPERIMENT_ID}|{game}|{split}|count{size}|vs-two",
        )
        summary = _summarize_values(metric_values)
        baseline_summary = _summarize_values(baseline)
        count_rows.append(
            {
                "game": game,
                "game_name": GAME_NAMES[game],
                "split": split,
                "agent_count": size,
                "agent_count_label": f"{size} 個 Agent",
                "combinations": math.comb(len(AGENT_IDS), size),
                "draws": len(metric_values[PRIMARY_METRIC]),
                **summary,
                "random_best_main_hits": baseline_summary[PRIMARY_METRIC],
                "delta_best_vs_random": statistics.fmean(primary_diff),
                "delta_best_vs_random_ci_low": ci_low,
                "delta_best_vs_random_ci_high": ci_high,
                "delta_best_vs_two": statistics.fmean(versus_two),
                "delta_best_vs_two_ci_low": two_ci_low,
                "delta_best_vs_two_ci_high": two_ci_high,
            }
        )

    for (game, split, council_id), metric_values in sorted(subset_values.items()):
        baseline = baseline_values[(game, split)]
        primary_diff = _paired_differences(
            metric_values[PRIMARY_METRIC],
            baseline[PRIMARY_METRIC],
        )
        subset_rows.append(
            {
                "game": game,
                "game_name": GAME_NAMES[game],
                "split": split,
                "subset_id": council_id,
                "agents": council_id.split("+"),
                "agent_count": len(council_id.split("+")),
                "draws": len(metric_values[PRIMARY_METRIC]),
                **_summarize_values(metric_values),
                "delta_best_vs_random": statistics.fmean(primary_diff),
                # 全部 26 組都重抽會製造不必要的多重比較與運算。
                # 先用 development 主指標選定候選，只對該候選補 development/holdout CI。
                "delta_best_vs_random_ci_low": None,
                "delta_best_vs_random_ci_high": None,
            }
        )

    selected: dict[str, dict] = {}
    for game in (SUPER, LOTTO649):
        development = [
            row
            for row in subset_rows
            if row["game"] == game and row["split"] == "development"
        ]
        winner = sorted(
            development,
            key=lambda row: (
                -row[PRIMARY_METRIC],
                -row["total_main_hits"],
                -row["any_three_plus"],
                row["subset_id"],
            ),
        )[0]
        holdout = next(
            row
            for row in subset_rows
            if row["game"] == game
            and row["split"] == "holdout"
            and row["subset_id"] == winner["subset_id"]
        )
        for chosen in (winner, holdout):
            metric_values = subset_values[
                (game, chosen["split"], winner["subset_id"])
            ]
            baseline = baseline_values[(game, chosen["split"])]
            differences = _paired_differences(
                metric_values[PRIMARY_METRIC],
                baseline[PRIMARY_METRIC],
            )
            ci_low, ci_high = block_bootstrap_ci(
                differences,
                samples=config.bootstrap_samples,
                block=config.bootstrap_block,
                seed=(
                    f"{EXPERIMENT_ID}|{game}|{chosen['split']}|"
                    f"{winner['subset_id']}|selected-vs-null"
                ),
            )
            chosen["delta_best_vs_random_ci_low"] = ci_low
            chosen["delta_best_vs_random_ci_high"] = ci_high
        selected[game] = {
            "subset_id": winner["subset_id"],
            "agents": winner["agents"],
            "agent_count": winner["agent_count"],
            "development": winner,
            "holdout": holdout,
            "selection_note": (
                "只依 development 主指標選擇；holdout 僅用於一次性評估，"
                "不得再回頭調整本次結論。"
            ),
        }

    evidence_by_game = {}
    for game in (SUPER, LOTTO649):
        rows = sorted(
            (
                row
                for row in count_rows
                if row["game"] == game and row["split"] == "holdout"
            ),
            key=lambda row: row["agent_count"],
        )
        monotonic = all(
            right[PRIMARY_METRIC] >= left[PRIMARY_METRIC]
            for left, right in zip(rows, rows[1:])
        )
        five = next(row for row in rows if row["agent_count"] == 5)
        five_beats_two = five["delta_best_vs_two_ci_low"] > 0
        evidence_by_game[game] = {
            "monotonic_non_decreasing": monotonic,
            "five_vs_two_mean_difference": five["delta_best_vs_two"],
            "five_vs_two_ci_low": five["delta_best_vs_two_ci_low"],
            "five_vs_two_ci_high": five["delta_best_vs_two_ci_high"],
            "five_beats_two_with_95pct_ci": five_beats_two,
        }
    conclusion = {
        "question": "Agent 設計越多是否越準？",
        "status": (
            "supported"
            if all(
                item["monotonic_non_decreasing"]
                and item["five_beats_two_with_95pct_ci"]
                for item in evidence_by_game.values()
            )
            else "not_supported"
        ),
        "by_game": evidence_by_game,
        "decision_rule": (
            "兩款遊戲的 holdout 平均最佳主號命中必須隨 Agent 數量單調不減，"
            "且 5 人相對 2 人的 13 期區塊 bootstrap 95% 區間下界皆大於 0。"
        ),
    }
    return count_rows, subset_rows, baseline_rows, {
        "selected_development_winners": selected,
        "conclusion": conclusion,
    }


def run_ablation(
    ledger_paths: dict[str, Path],
    *,
    base: Path,
    config: AblationConfig | None = None,
    verify_ledgers: bool = True,
) -> dict:
    """執行完整 Agent 數量消融；不寫入正式 records。"""
    config = config or AblationConfig()
    config.validate()
    subsets = agent_subsets()
    records_before = tree_sha256(base / "records")

    ledger_verification = {}
    for game in (SUPER, LOTTO649):
        path = Path(ledger_paths[game])
        if verify_ledgers:
            ledger_verification[game] = verify_replay(path)
        else:
            ledger_verification[game] = {
                "lines": _event_count(path),
                "ledger_sha256": None,
                "last_event_hash": None,
            }

    subset_values: dict[tuple[str, str, str], dict[str, list[float]]] = {}
    count_values: dict[tuple[str, str, int], dict[str, list[float]]] = {}
    baseline_values: dict[tuple[str, str], dict[str, list[float]]] = {}
    split_profiles = {}

    for game in (SUPER, LOTTO649):
        path = Path(ledger_paths[game])
        total = _event_count(path)
        eligible = total - config.warmup_draws
        if eligible < 20:
            raise ValueError(f"{game} 暖機後資料不足：{eligible}")
        development_draws = math.floor(
            eligible * config.development_fraction
        )
        holdout_draws = eligible - development_draws
        if development_draws < 1 or holdout_draws < 1:
            raise ValueError(f"{game} 時序切分失敗")
        split_profiles[game] = {
            "total_draws": total,
            "warmup_draws": config.warmup_draws,
            "eligible_draws": eligible,
            "development_draws": development_draws,
            "holdout_draws": holdout_draws,
        }
        ratings = {
            subset_id(subset): _initial_ratings()
            for subset in subsets
        }
        previous_key = None
        seen_periods = set()
        with path.open(encoding="utf-8") as handle:
            for sequence, line in enumerate(handle, 1):
                event = json.loads(line)
                _validate_event(event, game, sequence)
                decision = event["decision"]
                reveal = event["reveal"]
                key = (reveal["date"], int(reveal["period"]))
                if previous_key is not None and key <= previous_key:
                    raise ValueError(f"{game} 期別未嚴格遞增")
                if int(reveal["period"]) in seen_periods:
                    raise ValueError(f"{game} 期別重複")
                seen_periods.add(int(reveal["period"]))
                previous_key = key

                if sequence > config.warmup_draws:
                    eligible_index = sequence - config.warmup_draws
                    split = (
                        "development"
                        if eligible_index <= development_draws
                        else "holdout"
                    )
                    baseline_key = (game, split)
                    baseline_values.setdefault(
                        baseline_key,
                        {metric: [] for metric in METRICS},
                    )
                    baseline_result = random_baseline_metrics(
                        game, reveal, config.null_replicates
                    )
                    for metric in METRICS:
                        baseline_values[baseline_key][metric].append(
                            baseline_result[metric]
                        )

                    event_by_count: dict[int, dict[str, list[float]]] = {
                        size: {metric: [] for metric in METRICS}
                        for size in range(2, len(AGENT_IDS) + 1)
                    }
                    for subset in subsets:
                        council_id = subset_id(subset)
                        tickets = adjudicate_council(
                            decision["proposals"],
                            decision["critiques"],
                            ratings[council_id],
                            subset,
                        )
                        result = portfolio_metrics(game, tickets, reveal)
                        subset_key = (game, split, council_id)
                        subset_values.setdefault(
                            subset_key,
                            {metric: [] for metric in METRICS},
                        )
                        for metric in METRICS:
                            subset_values[subset_key][metric].append(
                                result[metric]
                            )
                            event_by_count[len(subset)][metric].append(
                                result[metric]
                            )
                    for size, metrics_by_subset in event_by_count.items():
                        count_key = (game, split, size)
                        count_values.setdefault(
                            count_key,
                            {metric: [] for metric in METRICS},
                        )
                        for metric in METRICS:
                            count_values[count_key][metric].append(
                                statistics.fmean(metrics_by_subset[metric])
                            )

                qualities = _proposal_qualities(
                    game, decision["proposals"], reveal
                )
                for subset in subsets:
                    council_id = subset_id(subset)
                    ratings[council_id] = update_subset_ratings(
                        ratings[council_id],
                        qualities,
                        subset,
                    )

        if sequence != total:
            raise AssertionError(f"{game} 實際讀取期數不符")

    count_rows, subset_rows, baseline_rows, decisions = _summaries(
        subset_values,
        count_values,
        baseline_values,
        config,
    )
    records_after = tree_sha256(base / "records")
    source_last_dates = {}
    for game, path in ledger_paths.items():
        last_event = None
        with Path(path).open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    last_event = json.loads(line)
        source_last_dates[game] = last_event["reveal"]["date"]
    generated_at = max(source_last_dates.values()) + "T23:59:59+08:00"

    result = {
        "schema_version": "1",
        "experiment_id": EXPERIMENT_ID,
        "source_experiment_id": LOOP_EXPERIMENT_ID,
        "generated_at": generated_at,
        "question": "Agent 設計越多是否越準？",
        "methodology": {
            "unit": "每遊戲、每期、固定五注投資組合",
            "primary_metric": PRIMARY_METRIC,
            "primary_metric_definition": "每期五注中，命中主號最多的一注之主號命中數（0 至 6）",
            "secondary_metrics": list(METRICS[1:]),
            "agent_subsets": len(subsets),
            "subset_counts": {
                str(size): math.comb(len(AGENT_IDS), size)
                for size in range(2, len(AGENT_IDS) + 1)
            },
            "warmup_draws": config.warmup_draws,
            "development_fraction": config.development_fraction,
            "holdout_fraction": 1 - config.development_fraction,
            "null_replicates_per_draw": config.null_replicates,
            "bootstrap_samples": config.bootstrap_samples,
            "bootstrap_block_draws": config.bootstrap_block,
            "selection_budget": f"每期固定 {SELECTED_TICKETS} 注",
            "lookahead_control": (
                "裁決只接收當期開獎前封存的 proposals、critiques 與前一期以前評等；"
                "reveal 僅在五注選定後計分並更新下一期評等。"
            ),
        },
        "data_quality": {
            "status": "pass",
            "ledger_verification": ledger_verification,
            "split_profiles": split_profiles,
            "source_last_dates": source_last_dates,
            "duplicate_periods": 0,
            "chronology": "strictly_increasing",
            "proposal_coverage": "5 agents × 3 proposals per draw",
            "critique_coverage": "60 cross-agent critiques per draw",
        },
        "count_summary": count_rows,
        "subset_summary": subset_rows,
        "random_baseline_summary": baseline_rows,
        **decisions,
        "records_integrity": {
            "before_sha256": records_before,
            "after_sha256": records_after,
            "unchanged": records_before == records_after,
        },
        "limitations": [
            "彩票開獎在理論模型下為獨立隨機事件；本研究只能檢查歷史樣本差異。",
            "26 個子議會組合造成多重比較；development 冠軍的 holdout 表現仍屬探索性結果。",
            "隨機基準每期採有限次 Monte Carlo；已用固定種子確保可重現。",
            "本研究比較規則裁決器，不代表 qwen3:8b 在未來期數能創造可用機率優勢。",
            "結果是純模擬，不構成購買或下注建議。",
        ],
    }
    if not result["records_integrity"]["unchanged"]:
        raise RuntimeError("Agent 消融研究不應改動正式 records")
    return result


def _write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    field: (
                        "+".join(row[field])
                        if isinstance(row.get(field), list)
                        else row.get(field)
                    )
                    for field in fields
                }
            )


def write_results(result: dict, output_dir: Path) -> dict[str, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "agent_ablation.json"
    count_path = output_dir / "agent_ablation_summary.csv"
    subset_path = output_dir / "agent_ablation_subsets.csv"
    json_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_csv(
        count_path,
        result["count_summary"],
        [
            "game",
            "game_name",
            "split",
            "agent_count",
            "agent_count_label",
            "combinations",
            "draws",
            *METRICS,
            "random_best_main_hits",
            "delta_best_vs_random",
            "delta_best_vs_random_ci_low",
            "delta_best_vs_random_ci_high",
            "delta_best_vs_two",
            "delta_best_vs_two_ci_low",
            "delta_best_vs_two_ci_high",
        ],
    )
    _write_csv(
        subset_path,
        result["subset_summary"],
        [
            "game",
            "game_name",
            "split",
            "subset_id",
            "agents",
            "agent_count",
            "draws",
            *METRICS,
            "delta_best_vs_random",
            "delta_best_vs_random_ci_low",
            "delta_best_vs_random_ci_high",
        ],
    )
    return {
        "json": json_path,
        "count_csv": count_path,
        "subset_csv": subset_path,
    }
