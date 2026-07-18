"""Agent 品質、替換候選、辯論校準與裁判敏感度的唯讀影子研究。

本模組只重用逐期帳本中開獎前已封存的提案、評論與評等。實際開獎只在
五注選定後用於配對評分；替換候選「覆蓋稽核員」也只能看當期其他 Agent
已封存的提案，不能讀取當期或未來開獎。
"""
from __future__ import annotations

import csv
import json
import math
import os
import random
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Iterable

from engine.agent_loop import (
    AGENT_IDS,
    LOOP_EXPERIMENT_ID,
    SELECTED_TICKETS,
    _analysis_context,
    _critique_score,
    verify_replay,
)
from engine.analysts import NAMES
from engine.games import (
    GAME_NAMES,
    LOTTO649,
    PICK_N,
    POOL,
    SPECIAL_POOL,
    SUPER,
    Draw,
    validate_pick,
)
from engine.seeds import seed_int
from research.agent_ablation import (
    _validate_event,
    adjudicate_council,
    block_bootstrap_ci,
    portfolio_metrics,
)
from research.gates import tree_sha256


EXPERIMENT_ID = "council-quality-shadow-v1"
CANDIDATE_AGENT_ID = "coverage_auditor"
CANDIDATE_AGENT_NAME = "覆蓋稽核員"
DEFAULT_WARMUP_DRAWS = 60
DEFAULT_DEVELOPMENT_FRACTION = 0.70
DEFAULT_BOOTSTRAP_SAMPLES = 2_000
DEFAULT_BOOTSTRAP_BLOCK = 13
RECENT_TRACE_DRAWS = 52

SENSITIVITY_VARIANTS = {
    "equal_ratings": {
        "label": "所有 Agent 等權",
        "use_ratings": False,
    },
    "confidence_off": {
        "label": "評論信心度關閉",
        "use_confidence": False,
    },
    "disagreement_off": {
        "label": "分歧懲罰關閉",
        "disagreement_penalty": 0.0,
    },
    "diversity_off": {
        "label": "五注重疊懲罰關閉",
        "diversity_penalty": 0.0,
    },
    "voice_off": {
        "label": "同 Agent 集中懲罰關閉",
        "voice_penalty": 0.0,
    },
}


@dataclass(frozen=True)
class QualityConfig:
    warmup_draws: int = DEFAULT_WARMUP_DRAWS
    development_fraction: float = DEFAULT_DEVELOPMENT_FRACTION
    bootstrap_samples: int = DEFAULT_BOOTSTRAP_SAMPLES
    bootstrap_block: int = DEFAULT_BOOTSTRAP_BLOCK

    def validate(self) -> None:
        if self.warmup_draws < 0:
            raise ValueError("warmup_draws 不得為負")
        if not 0.5 <= self.development_fraction < 1:
            raise ValueError("development_fraction 必須介於 0.5（含）與 1 之間")
        if self.bootstrap_samples < 100:
            raise ValueError("bootstrap_samples 至少為 100")
        if self.bootstrap_block < 1:
            raise ValueError("bootstrap_block 至少為 1")


def _mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def _population_std(values: list[float]) -> float:
    return statistics.pstdev(values) if len(values) > 1 else 0.0


def _quantile(values: list[float], probability: float) -> float:
    if not values:
        raise ValueError("quantile 沒有資料")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right):
        raise ValueError("相關序列長度不一致")
    if len(left) < 2:
        return None
    left_mean = _mean(left)
    right_mean = _mean(right)
    left_variance = sum((value - left_mean) ** 2 for value in left)
    right_variance = sum((value - right_mean) ** 2 for value in right)
    if left_variance <= 1e-15 or right_variance <= 1e-15:
        return None
    covariance = sum(
        (a - left_mean) * (b - right_mean)
        for a, b in zip(left, right)
    )
    return covariance / math.sqrt(left_variance * right_variance)


def _rank(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: (values[index], index))
    ranks = [0.0] * len(values)
    position = 0
    while position < len(order):
        end = position + 1
        value = values[order[position]]
        while end < len(order) and values[order[end]] == value:
            end += 1
        average_rank = (position + 1 + end) / 2
        for offset in range(position, end):
            ranks[order[offset]] = average_rank
        position = end
    return ranks


def _spearman(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right):
        raise ValueError("秩相關序列長度不一致")
    if not left:
        return None
    return _pearson(_rank(left), _rank(right))


def _ticket_numbers(tickets: list[dict]) -> set[tuple[int, ...]]:
    return {tuple(ticket["numbers"]) for ticket in tickets}


def _adjudicate_variant(
    proposals: list[dict],
    critiques: list[dict],
    ratings: dict[str, float],
    *,
    use_ratings: bool = True,
    use_confidence: bool = True,
    disagreement_penalty: float = 0.08,
    diversity_penalty: float = 0.14,
    voice_penalty: float = 0.05,
) -> list[dict]:
    """以顯式旋鈕重算規則裁判；預設值與正式裁判相同。"""
    proposal_agents = {proposal["agent"] for proposal in proposals}
    missing_ratings = proposal_agents - set(ratings)
    if missing_ratings:
        raise ValueError(f"缺少 Agent 評等：{sorted(missing_ratings)}")

    scored = []
    for proposal in proposals:
        relevant = [
            critique
            for critique in critiques
            if critique["target"] == proposal["proposal_id"]
        ]
        if not relevant:
            raise ValueError(f"{proposal['proposal_id']} 沒有評論")
        weights = []
        for critique in relevant:
            rating = ratings[critique["critic"]] if use_ratings else 1.0
            confidence = (
                float(critique.get("confidence", 1.0))
                if use_confidence
                else 1.0
            )
            weights.append(rating * confidence)
        total_weight = sum(weights)
        consensus = sum(
            critique["score"] * weight
            for critique, weight in zip(relevant, weights)
        ) / total_weight
        disagreement = math.sqrt(
            sum(
                weight * (critique["score"] - consensus) ** 2
                for critique, weight in zip(relevant, weights)
            )
            / total_weight
        )
        proposer_rating = (
            ratings[proposal["agent"]] if use_ratings else 1.0
        )
        debate_score = (
            consensus
            - disagreement_penalty * disagreement
            + 0.05 * (proposer_rating - 1.0)
        )
        scored.append(
            {
                "proposal": proposal,
                "debate_score": debate_score,
            }
        )

    selected = []
    remaining = list(scored)
    while len(selected) < SELECTED_TICKETS:
        selected_agents = Counter(
            item["proposal"]["agent"] for item in selected
        )
        choices = []
        for item in remaining:
            proposal = item["proposal"]
            overlap = (
                max(
                    len(
                        set(proposal["numbers"])
                        & set(other["proposal"]["numbers"])
                    )
                    / PICK_N
                    for other in selected
                )
                if selected
                else 0.0
            )
            final_score = (
                item["debate_score"]
                - diversity_penalty * overlap
                - voice_penalty * selected_agents[proposal["agent"]]
            )
            choices.append(
                (
                    -final_score,
                    -item["debate_score"],
                    proposal["proposal_id"],
                    item,
                )
            )
        chosen = sorted(choices)[0][3]
        selected.append(chosen)
        remaining.remove(chosen)

    return [
        {
            "slot": slot,
            "source_agent": item["proposal"]["agent"],
            "source_proposal": item["proposal"]["proposal_id"],
            "numbers": item["proposal"]["numbers"],
            "special": item["proposal"]["special"],
        }
        for slot, item in enumerate(selected, 1)
    ]


def _coverage_objective(
    numbers: list[int],
    coverage_counts: Counter,
    existing: list[dict],
    selected: list[dict],
) -> tuple[float, float, float]:
    existing_overlap = max(
        len(set(numbers) & set(proposal["numbers"]))
        for proposal in existing
    )
    selected_overlap = (
        max(
            len(set(numbers) & set(proposal["numbers"]))
            for proposal in selected
        )
        if selected
        else 0
    )
    concentration = sum(coverage_counts[number] for number in numbers)
    return (
        concentration + 1.25 * existing_overlap + 0.75 * selected_overlap,
        abs(sum(numbers) / PICK_N - (max(coverage_counts) + 1) / 2),
        float(sum(number % 2 for number in numbers) not in (2, 3, 4)),
    )


def build_coverage_proposals(
    game: str,
    target: dict,
    existing_proposals: list[dict],
    *,
    samples_per_variant: int = 160,
) -> list[dict]:
    """只看其他席位當期提案，產生低重疊的三組合法影子候選。"""
    if not existing_proposals:
        raise ValueError("覆蓋候選需要其他 Agent 的已封存提案")
    coverage_counts = Counter(
        number
        for proposal in existing_proposals
        for number in proposal["numbers"]
    )
    for number in range(1, POOL[game] + 1):
        coverage_counts.setdefault(number, 0)

    proposals = []
    seen = {tuple(proposal["numbers"]) for proposal in existing_proposals}
    for variant in range(1, 4):
        rng = random.Random(
            seed_int(
                f"{EXPERIMENT_ID}|{game}|{target['date']}|"
                f"period{target['period']}|coverage|variant{variant}"
            )
        )
        choices = []
        for sample in range(samples_per_variant):
            numbers = sorted(
                rng.sample(range(1, POOL[game] + 1), PICK_N)
            )
            key = tuple(numbers)
            if key in seen:
                continue
            choices.append(
                (
                    _coverage_objective(
                        numbers,
                        coverage_counts,
                        existing_proposals,
                        proposals,
                    ),
                    sample,
                    numbers,
                )
            )
        if not choices:
            raise RuntimeError("覆蓋候選無法產生不重複提案")
        _, _, numbers = sorted(choices)[0]
        special = (
            rng.randint(1, SPECIAL_POOL[SUPER])
            if game == SUPER
            else None
        )
        validate_pick(game, numbers, special)
        seen.add(tuple(numbers))
        proposals.append(
            {
                "proposal_id": f"{CANDIDATE_AGENT_ID}:{variant}",
                "agent": CANDIDATE_AGENT_ID,
                "agent_name": CANDIDATE_AGENT_NAME,
                "variant": variant,
                "numbers": numbers,
                "special": special,
                "retry": 0,
                "thesis": (
                    "只降低與其他席位候選的覆蓋重複；不宣稱歷史能提高開出率。"
                ),
                "evidence": {
                    "history_used": 0,
                    "mean_existing_coverage": round(
                        _mean(
                            [
                                float(coverage_counts[number])
                                for number in numbers
                            ]
                        ),
                        6,
                    ),
                    "maximum_existing_overlap": max(
                        len(set(numbers) & set(item["numbers"]))
                        for item in existing_proposals
                    ),
                },
            }
        )
    return proposals


def _coverage_critiques(
    proposals: list[dict],
    targets: list[dict],
) -> list[dict]:
    counts = Counter(
        number for proposal in proposals for number in proposal["numbers"]
    )
    raw_scores = {
        target["proposal_id"]: _mean(
            [1 / max(1, counts[number]) for number in target["numbers"]]
        )
        for target in targets
    }
    population = list(raw_scores.values())
    critiques = []
    for target in targets:
        raw = raw_scores[target["proposal_id"]]
        below = sum(value < raw for value in population)
        equal = sum(value == raw for value in population)
        percentile = (below + 0.5 * equal) / len(population)
        score = 0.25 + 0.5 * percentile
        critiques.append(
            {
                "critic": CANDIDATE_AGENT_ID,
                "critic_name": CANDIDATE_AGENT_NAME,
                "target": target["proposal_id"],
                "score": round(score, 6),
                "confidence": 0.8,
                "stance": (
                    "support"
                    if score > 0.60
                    else "oppose"
                    if score < 0.40
                    else "neutral"
                ),
                "reason": "依當期候選池的號碼覆蓋重複度評議。",
                "evidence": {
                    "coverage_novelty": round(raw, 6),
                    "coverage_percentile": round(percentile, 6),
                },
            }
        )
    return critiques


def replacement_council(
    game: str,
    target: dict,
    history: list[Draw],
    decision: dict,
    removed_agent: str,
) -> tuple[list[dict], list[dict], list[dict]]:
    """以覆蓋稽核員替換指定完整席位，回傳五注、提案與評論。"""
    if removed_agent not in AGENT_IDS:
        raise ValueError(removed_agent)
    remaining_agents = set(AGENT_IDS) - {removed_agent}
    original_proposals = [
        proposal
        for proposal in decision["proposals"]
        if proposal["agent"] in remaining_agents
    ]
    candidate_proposals = build_coverage_proposals(
        game,
        target,
        original_proposals,
    )
    proposals = original_proposals + candidate_proposals
    proposal_ids = {proposal["proposal_id"] for proposal in original_proposals}
    critiques = [
        critique
        for critique in decision["critiques"]
        if critique["critic"] in remaining_agents
        and critique["target"] in proposal_ids
    ]

    context = _analysis_context(game, history)
    for critic in sorted(remaining_agents):
        for proposal in candidate_proposals:
            score, confidence, reason, evidence = _critique_score(
                critic,
                game,
                history,
                proposal,
                context,
            )
            critiques.append(
                {
                    "critic": critic,
                    "critic_name": NAMES[critic],
                    "target": proposal["proposal_id"],
                    "score": round(score, 6),
                    "confidence": round(confidence, 6),
                    "stance": (
                        "support"
                        if score > 0.60
                        else "oppose"
                        if score < 0.40
                        else "neutral"
                    ),
                    "reason": reason,
                    "evidence": evidence,
                }
            )
    critiques.extend(_coverage_critiques(proposals, original_proposals))

    ratings = {
        agent: float(state["rating"])
        for agent, state in decision["state_before"]["agents"].items()
        if agent in remaining_agents
    }
    ratings[CANDIDATE_AGENT_ID] = 1.0
    tickets = _adjudicate_variant(
        proposals,
        critiques,
        ratings,
    )
    return tickets, proposals, critiques


def _append_metric(
    store: dict,
    key: tuple,
    metric: str,
    value: float,
) -> None:
    store.setdefault(key, defaultdict(list))[metric].append(float(value))


def _draw_from_reveal(game: str, reveal: dict) -> Draw:
    return Draw(
        game=game,
        period=int(reveal["period"]),
        date=reveal["date"],
        numbers=tuple(reveal["numbers"]),
        special=int(reveal["special"]),
    )


def _split_profile(
    total: int,
    config: QualityConfig,
) -> tuple[dict, int]:
    eligible = total - config.warmup_draws
    if eligible < 20:
        raise ValueError(f"暖機後資料不足：{eligible}")
    development = math.floor(eligible * config.development_fraction)
    holdout = eligible - development
    if development < 1 or holdout < 1:
        raise ValueError("時序切分失敗")
    return {
        "total_draws": total,
        "warmup_draws": config.warmup_draws,
        "eligible_draws": eligible,
        "development_draws": development,
        "holdout_draws": holdout,
    }, development


def _agent_summary_rows(
    values: dict,
    config: QualityConfig,
) -> list[dict]:
    rows = []
    for (game, split, agent), metrics in sorted(values.items()):
        leaveout_ci = block_bootstrap_ci(
            metrics["leaveout_delta_best_main_hits"],
            samples=config.bootstrap_samples,
            block=config.bootstrap_block,
            seed=f"{EXPERIMENT_ID}|{game}|{split}|{agent}|leaveout",
        )
        replacement_ci = block_bootstrap_ci(
            metrics["replacement_delta_best_main_hits"],
            samples=config.bootstrap_samples,
            block=config.bootstrap_block,
            seed=f"{EXPERIMENT_ID}|{game}|{split}|{agent}|replacement",
        )
        replacement_mean = _mean(
            metrics["replacement_delta_best_main_hits"]
        )
        rows.append(
            {
                "game": game,
                "game_name": GAME_NAMES[game],
                "split": split,
                "agent": agent,
                "agent_name": NAMES[agent],
                "draws": len(metrics["proposal_mean_main_hits"]),
                "proposal_mean_main_hits": _mean(
                    metrics["proposal_mean_main_hits"]
                ),
                "proposal_best_main_hits": _mean(
                    metrics["proposal_best_main_hits"]
                ),
                "unique_candidate_numbers": _mean(
                    metrics["unique_candidate_numbers"]
                ),
                "selected_ticket_share": _mean(
                    metrics["selected_ticket_share"]
                ),
                "leaveout_delta_best_main_hits": _mean(
                    metrics["leaveout_delta_best_main_hits"]
                ),
                "leaveout_delta_best_main_hits_ci_low": leaveout_ci[0],
                "leaveout_delta_best_main_hits_ci_high": leaveout_ci[1],
                "leaveout_delta_union_main_hits": _mean(
                    metrics["leaveout_delta_union_main_hits"]
                ),
                "replacement_delta_best_main_hits": replacement_mean,
                "replacement_delta_best_main_hits_ci_low": replacement_ci[0],
                "replacement_delta_best_main_hits_ci_high": replacement_ci[1],
                "replacement_delta_total_main_hits": _mean(
                    metrics["replacement_delta_total_main_hits"]
                ),
                "replacement_delta_union_main_hits": _mean(
                    metrics["replacement_delta_union_main_hits"]
                ),
                "replacement_delta_union_size": _mean(
                    metrics["replacement_delta_union_size"]
                ),
                "replacement_selection_overlap": _mean(
                    metrics["replacement_selection_overlap"]
                ),
                "action": (
                    "replacement_supported"
                    if replacement_ci[0] > 0
                    else "keep_existing"
                    if replacement_ci[1] < 0
                    else "inconclusive"
                ),
            }
        )
    return rows


def _critic_summary_rows(critic_values: dict) -> list[dict]:
    rows = []
    for (game, split, critic), values in sorted(critic_values.items()):
        threshold = _quantile(values["score"], 0.75)
        top_actual = [
            actual
            for score, actual in zip(values["score"], values["actual"])
            if score >= threshold
        ]
        rows.append(
            {
                "game": game,
                "game_name": GAME_NAMES[game],
                "split": split,
                "critic": critic,
                "critic_name": NAMES[critic],
                "critiques": len(values["score"]),
                "mean_score": _mean(values["score"]),
                "score_std": _population_std(values["score"]),
                "pearson_score_to_actual": _pearson(
                    values["score"], values["actual"]
                ),
                "spearman_score_to_actual": _spearman(
                    values["score"], values["actual"]
                ),
                "top_quartile_actual_lift": (
                    _mean(top_actual) - _mean(values["actual"])
                ),
                "constant_score": _population_std(values["score"]) <= 1e-12,
            }
        )
    return rows


def _pair_summary_rows(pair_values: dict) -> list[dict]:
    rows = []
    for (game, split, left, right), values in sorted(pair_values.items()):
        correlation = _pearson(values["left"], values["right"])
        rows.append(
            {
                "game": game,
                "game_name": GAME_NAMES[game],
                "split": split,
                "left_critic": left,
                "left_name": NAMES[left],
                "right_critic": right,
                "right_name": NAMES[right],
                "shared_critiques": len(values["left"]),
                "score_correlation": correlation,
                "mean_absolute_score_gap": _mean(
                    [
                        abs(a - b)
                        for a, b in zip(values["left"], values["right"])
                    ]
                ),
                "redundancy_flag": (
                    correlation is not None and abs(correlation) >= 0.85
                ),
            }
        )
    return rows


def _sensitivity_summary_rows(sensitivity_values: dict) -> list[dict]:
    rows = []
    for (game, split, variant), values in sorted(
        sensitivity_values.items()
    ):
        rows.append(
            {
                "game": game,
                "game_name": GAME_NAMES[game],
                "split": split,
                "variant": variant,
                "variant_label": SENSITIVITY_VARIANTS[variant]["label"],
                "draws": len(values["selection_overlap"]),
                "selection_overlap": _mean(values["selection_overlap"]),
                "exact_selection_rate": _mean(values["exact_selection"]),
                "delta_best_main_hits": _mean(
                    values["delta_best_main_hits"]
                ),
                "delta_total_main_hits": _mean(
                    values["delta_total_main_hits"]
                ),
                "delta_union_main_hits": _mean(
                    values["delta_union_main_hits"]
                ),
                "delta_union_size": _mean(values["delta_union_size"]),
            }
        )
    return rows


def _select_replacement(
    agent_rows: list[dict],
    traces: dict,
) -> tuple[dict, dict]:
    selected = {}
    recent = {}
    for game in (SUPER, LOTTO649):
        development = [
            row
            for row in agent_rows
            if row["game"] == game and row["split"] == "development"
        ]
        winner = sorted(
            development,
            key=lambda row: (
                -row["replacement_delta_best_main_hits"],
                -row["replacement_delta_union_main_hits"],
                -row["replacement_delta_union_size"],
                row["agent"],
            ),
        )[0]
        holdout = next(
            row
            for row in agent_rows
            if row["game"] == game
            and row["split"] == "holdout"
            and row["agent"] == winner["agent"]
        )
        selected[game] = {
            "removed_agent": winner["agent"],
            "removed_agent_name": winner["agent_name"],
            "candidate_agent": CANDIDATE_AGENT_ID,
            "candidate_agent_name": CANDIDATE_AGENT_NAME,
            "development": winner,
            "holdout": holdout,
            "selection_note": (
                "只依 development 的替換後最佳主號命中差、聯集命中差與"
                "聯集大小差依序選擇；holdout 不參與席位選擇。"
            ),
        }
        recent[game] = traces[
            (game, "holdout", winner["agent"])
        ][-RECENT_TRACE_DRAWS:]
    return selected, recent


def run_quality_study(
    ledger_paths: dict[str, Path],
    *,
    base: Path,
    config: QualityConfig | None = None,
    verify_ledgers: bool = True,
) -> dict:
    """執行完整影子研究；不寫入正式 records 或前向登記。"""
    config = config or QualityConfig()
    config.validate()
    records_before = tree_sha256(base / "records")

    ledger_verification = {}
    split_profiles = {}
    source_last_dates = {}
    agent_values = {}
    critic_values = {}
    pair_values = {}
    sensitivity_values = {}
    traces = defaultdict(list)

    for game in (SUPER, LOTTO649):
        path = Path(ledger_paths[game])
        ledger_verification[game] = (
            verify_replay(path)
            if verify_ledgers
            else {
                "lines": sum(
                    1
                    for line in path.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ),
                "ledger_sha256": None,
                "last_event_hash": None,
            }
        )
        total = int(ledger_verification[game]["lines"])
        profile, development_draws = _split_profile(total, config)
        split_profiles[game] = profile
        history: list[Draw] = []

        with path.open(encoding="utf-8") as handle:
            for sequence, line in enumerate(handle, 1):
                event = json.loads(line)
                _validate_event(event, game, sequence)
                decision = event["decision"]
                reveal = event["reveal"]
                if sequence > config.warmup_draws:
                    eligible_index = sequence - config.warmup_draws
                    split = (
                        "development"
                        if eligible_index <= development_draws
                        else "holdout"
                    )
                    ratings = {
                        agent: float(state["rating"])
                        for agent, state in decision["state_before"][
                            "agents"
                        ].items()
                    }
                    baseline_tickets = _adjudicate_variant(
                        decision["proposals"],
                        decision["critiques"],
                        ratings,
                    )
                    if baseline_tickets != decision["selected_tickets"]:
                        raise ValueError(
                            f"{game} 第 {sequence} 期規則裁判重算不一致"
                        )
                    baseline_metrics = portfolio_metrics(
                        game, baseline_tickets, reveal
                    )
                    actual = set(reveal["numbers"])
                    proposal_actual = {
                        proposal["proposal_id"]: len(
                            set(proposal["numbers"]) & actual
                        )
                        for proposal in decision["proposals"]
                    }

                    for agent in AGENT_IDS:
                        key = (game, split, agent)
                        own = [
                            proposal
                            for proposal in decision["proposals"]
                            if proposal["agent"] == agent
                        ]
                        others = [
                            proposal
                            for proposal in decision["proposals"]
                            if proposal["agent"] != agent
                        ]
                        own_hits = [
                            proposal_actual[proposal["proposal_id"]]
                            for proposal in own
                        ]
                        own_union = set().union(
                            *(set(proposal["numbers"]) for proposal in own)
                        )
                        other_union = set().union(
                            *(set(proposal["numbers"]) for proposal in others)
                        )
                        selected_count = sum(
                            ticket["source_agent"] == agent
                            for ticket in baseline_tickets
                        )
                        _append_metric(
                            agent_values,
                            key,
                            "proposal_mean_main_hits",
                            _mean([float(value) for value in own_hits]),
                        )
                        _append_metric(
                            agent_values,
                            key,
                            "proposal_best_main_hits",
                            max(own_hits),
                        )
                        _append_metric(
                            agent_values,
                            key,
                            "unique_candidate_numbers",
                            len(own_union - other_union),
                        )
                        _append_metric(
                            agent_values,
                            key,
                            "selected_ticket_share",
                            selected_count / SELECTED_TICKETS,
                        )

                        subset = tuple(
                            member
                            for member in AGENT_IDS
                            if member != agent
                        )
                        leaveout_tickets = adjudicate_council(
                            decision["proposals"],
                            decision["critiques"],
                            ratings,
                            subset,
                        )
                        leaveout_metrics = portfolio_metrics(
                            game, leaveout_tickets, reveal
                        )
                        _append_metric(
                            agent_values,
                            key,
                            "leaveout_delta_best_main_hits",
                            leaveout_metrics["best_main_hits"]
                            - baseline_metrics["best_main_hits"],
                        )
                        _append_metric(
                            agent_values,
                            key,
                            "leaveout_delta_union_main_hits",
                            leaveout_metrics["union_main_hits"]
                            - baseline_metrics["union_main_hits"],
                        )

                        replacement_tickets, _, _ = replacement_council(
                            game,
                            decision["target"],
                            history,
                            decision,
                            agent,
                        )
                        replacement_metrics = portfolio_metrics(
                            game, replacement_tickets, reveal
                        )
                        exact_overlap = len(
                            _ticket_numbers(baseline_tickets)
                            & _ticket_numbers(replacement_tickets)
                        ) / SELECTED_TICKETS
                        for metric in (
                            "best_main_hits",
                            "total_main_hits",
                            "union_main_hits",
                            "union_size",
                        ):
                            _append_metric(
                                agent_values,
                                key,
                                f"replacement_delta_{metric}",
                                replacement_metrics[metric]
                                - baseline_metrics[metric],
                            )
                        _append_metric(
                            agent_values,
                            key,
                            "replacement_selection_overlap",
                            exact_overlap,
                        )
                        traces[key].append(
                            {
                                "date": reveal["date"],
                                "period": int(reveal["period"]),
                                "baseline_best_main_hits": int(
                                    baseline_metrics["best_main_hits"]
                                ),
                                "replacement_best_main_hits": int(
                                    replacement_metrics["best_main_hits"]
                                ),
                                "delta_best_main_hits": int(
                                    replacement_metrics["best_main_hits"]
                                    - baseline_metrics["best_main_hits"]
                                ),
                                "baseline_union_main_hits": int(
                                    baseline_metrics["union_main_hits"]
                                ),
                                "replacement_union_main_hits": int(
                                    replacement_metrics["union_main_hits"]
                                ),
                                "selection_overlap": round(
                                    exact_overlap, 3
                                ),
                            }
                        )

                    critiques_by_critic = defaultdict(dict)
                    for critique in decision["critiques"]:
                        critic_key = (game, split, critique["critic"])
                        _append_metric(
                            critic_values,
                            critic_key,
                            "score",
                            critique["score"],
                        )
                        _append_metric(
                            critic_values,
                            critic_key,
                            "actual",
                            proposal_actual[critique["target"]],
                        )
                        critiques_by_critic[critique["critic"]][
                            critique["target"]
                        ] = float(critique["score"])

                    for left, right in combinations(AGENT_IDS, 2):
                        shared = sorted(
                            set(critiques_by_critic[left])
                            & set(critiques_by_critic[right])
                        )
                        pair_key = (game, split, left, right)
                        for proposal_id in shared:
                            _append_metric(
                                pair_values,
                                pair_key,
                                "left",
                                critiques_by_critic[left][proposal_id],
                            )
                            _append_metric(
                                pair_values,
                                pair_key,
                                "right",
                                critiques_by_critic[right][proposal_id],
                            )

                    baseline_ids = {
                        ticket["source_proposal"]
                        for ticket in baseline_tickets
                    }
                    for variant, options in SENSITIVITY_VARIANTS.items():
                        variant_options = {
                            key: value
                            for key, value in options.items()
                            if key != "label"
                        }
                        variant_tickets = _adjudicate_variant(
                            decision["proposals"],
                            decision["critiques"],
                            ratings,
                            **variant_options,
                        )
                        variant_metrics = portfolio_metrics(
                            game, variant_tickets, reveal
                        )
                        variant_ids = {
                            ticket["source_proposal"]
                            for ticket in variant_tickets
                        }
                        sensitivity_key = (game, split, variant)
                        _append_metric(
                            sensitivity_values,
                            sensitivity_key,
                            "selection_overlap",
                            len(baseline_ids & variant_ids)
                            / SELECTED_TICKETS,
                        )
                        _append_metric(
                            sensitivity_values,
                            sensitivity_key,
                            "exact_selection",
                            float(baseline_ids == variant_ids),
                        )
                        for metric in (
                            "best_main_hits",
                            "total_main_hits",
                            "union_main_hits",
                            "union_size",
                        ):
                            _append_metric(
                                sensitivity_values,
                                sensitivity_key,
                                f"delta_{metric}",
                                variant_metrics[metric]
                                - baseline_metrics[metric],
                            )

                history.append(_draw_from_reveal(game, reveal))
                source_last_dates[game] = reveal["date"]

        if len(history) != total:
            raise AssertionError(f"{game} 實際讀取期數不符")

    agent_rows = _agent_summary_rows(agent_values, config)
    critic_rows = _critic_summary_rows(critic_values)
    pair_rows = _pair_summary_rows(pair_values)
    sensitivity_rows = _sensitivity_summary_rows(sensitivity_values)
    selected_replacements, recent_traces = _select_replacement(
        agent_rows, traces
    )

    promotion_by_game = {
        game: (
            item["holdout"][
                "replacement_delta_best_main_hits_ci_low"
            ]
            > 0
            and item["holdout"]["replacement_delta_union_main_hits"] >= 0
        )
        for game, item in selected_replacements.items()
    }
    conclusion = {
        "status": (
            "promote_candidate"
            if all(promotion_by_game.values())
            else "retain_current_council"
        ),
        "candidate": CANDIDATE_AGENT_ID,
        "candidate_name": CANDIDATE_AGENT_NAME,
        "by_game": promotion_by_game,
        "decision_rule": (
            "每款遊戲只依 development 選一個被替換席位；該席位在一次性"
            "holdout 的替換後最佳主號命中差，其 13 期區塊 bootstrap 95% "
            "區間下界必須大於 0，且聯集主號命中不得下降。兩款遊戲都通過"
            "才可升級。"
        ),
        "recommendation": (
            "promote_coverage_auditor"
            if all(promotion_by_game.values())
            else "keep_as_shadow_only"
        ),
    }

    records_after = tree_sha256(base / "records")
    result = {
        "schema_version": "1",
        "experiment_id": EXPERIMENT_ID,
        "source_experiment_id": LOOP_EXPERIMENT_ID,
        "generated_at": max(source_last_dates.values())
        + "T23:59:59+08:00",
        "question": (
            "哪個現有席位可被較低重疊的覆蓋稽核員取代，且辯論與裁判是否"
            "提供穩定、非重複的歷史訊號？"
        ),
        "methodology": {
            "unit": "每遊戲、每期、固定五注投資組合",
            "warmup_draws": config.warmup_draws,
            "development_fraction": config.development_fraction,
            "holdout_fraction": 1 - config.development_fraction,
            "bootstrap_samples": config.bootstrap_samples,
            "bootstrap_block_draws": config.bootstrap_block,
            "candidate_agent": CANDIDATE_AGENT_ID,
            "candidate_proposals_per_draw": 3,
            "candidate_search_samples_per_proposal": 160,
            "selection_budget": f"每期固定 {SELECTED_TICKETS} 注",
            "lookahead_control": (
                "替換候選只讀當期其他席位已封存提案；所有五注先選定，"
                "reveal 才進入配對評分。"
            ),
            "sensitivity_variants": {
                variant: options["label"]
                for variant, options in SENSITIVITY_VARIANTS.items()
            },
        },
        "data_quality": {
            "status": "pass",
            "ledger_verification": ledger_verification,
            "split_profiles": split_profiles,
            "source_last_dates": source_last_dates,
            "chronology": "strictly_increasing",
            "proposal_coverage": "5 agents × 3 proposals per draw",
            "critique_coverage": "60 cross-agent critiques per draw",
        },
        "agent_quality": agent_rows,
        "critic_quality": critic_rows,
        "critic_pair_redundancy": pair_rows,
        "judge_sensitivity": sensitivity_rows,
        "selected_replacements": selected_replacements,
        "recent_holdout_trace": recent_traces,
        "conclusion": conclusion,
        "records_integrity": {
            "before_sha256": records_before,
            "after_sha256": records_after,
            "unchanged": records_before == records_after,
        },
        "limitations": [
            "合法彩票組合在理論模型下等機率；正負歷史差都可能是抽樣噪音。",
            "覆蓋稽核員改善的是候選與五注分散，不宣稱能改變單一組合開出率。",
            "development 同時比較五個被替換席位，仍有探索性多重比較。",
            "評論分數與事後命中的相關只用來檢查校準，不是開獎因果證據。",
            "研究只比較可重現規則裁判；Qwen 的正式證據仍以預註冊前向 A/B 為準。",
            "結果是純模擬，不構成購買或下注建議。",
        ],
    }
    if not result["records_integrity"]["unchanged"]:
        raise RuntimeError("影子研究不應改動正式 records")
    return result


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        raise ValueError(f"{path.name} 沒有資料")
    fields = list(rows[0])
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_results(result: dict, output_dir: Path) -> dict[str, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "json": output_dir / "council_quality.json",
        "agents": output_dir / "council_agent_quality.csv",
        "critics": output_dir / "council_debate_quality.csv",
        "sensitivity": output_dir / "council_judge_sensitivity.csv",
    }
    json_temp = paths["json"].with_suffix(".json.tmp")
    json_temp.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(json_temp, paths["json"])
    _write_csv(paths["agents"], result["agent_quality"])
    _write_csv(paths["critics"], result["critic_quality"])
    _write_csv(paths["sensitivity"], result["judge_sensitivity"])
    return paths
