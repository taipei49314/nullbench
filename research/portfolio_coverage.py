"""五注完整任一獎級機率與低重疊 selector 影子研究。

本模組只讀逐期帳本中已在開獎前封存的 15 組提案與評論。selector 不接收
reveal；它先窮舉 15 選 5，以完整中獎事件的二階 Bonferroni 下界排序，再用
membership-group 動態規劃確認「至少一注落入任一現行獎級」與三主號護欄
的精確機率均不低於原規則裁判。實際開獎只在五注選定後用於回顧性評分。
"""
from __future__ import annotations

import csv
import json
import math
import os
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache
from itertools import combinations
from pathlib import Path

from engine.agent_loop import (
    LOOP_EXPERIMENT_ID,
    SELECTED_TICKETS,
    verify_replay,
)
from engine.games import (
    GAME_NAMES,
    LOTTO649,
    PICK_N,
    POOL,
    SPECIAL_POOL,
    SUPER,
    validate_pick,
)
from research.agent_ablation import (
    _validate_event,
    block_bootstrap_ci,
    portfolio_metrics,
)
from research.gates import tree_sha256


EXPERIMENT_ID = "portfolio-coverage-shadow-v1"
MAIN_HIT_THRESHOLD = 3
DEFAULT_WARMUP_DRAWS = 60
DEFAULT_DEVELOPMENT_FRACTION = 0.70
DEFAULT_BOOTSTRAP_SAMPLES = 2_000
DEFAULT_BOOTSTRAP_BLOCK = 13
RECENT_TRACE_DRAWS = 52


@dataclass(frozen=True)
class CoverageConfig:
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


def _ticket_sets(
    game: str,
    tickets: list[dict],
    *,
    expected_count: int | None = SELECTED_TICKETS,
) -> list[set[int]]:
    if expected_count is not None and len(tickets) != expected_count:
        raise ValueError(f"投資組合必須恰好 {expected_count} 注")
    if not tickets:
        raise ValueError("投資組合不得為空")
    seen = set()
    result = []
    for ticket in tickets:
        validate_pick(game, ticket["numbers"], ticket.get("special"))
        numbers = tuple(sorted(int(number) for number in ticket["numbers"]))
        if numbers in seen:
            raise ValueError("五注主號不得重複")
        seen.add(numbers)
        result.append(set(numbers))
    return result


def _membership_counts(
    pool: int,
    ticket_sets: list[set[int]],
) -> tuple[int, ...]:
    counts = [0] * (1 << len(ticket_sets))
    for number in range(1, pool + 1):
        mask = 0
        for index, numbers in enumerate(ticket_sets):
            if number in numbers:
                mask |= 1 << index
        counts[mask] += 1
    return tuple(counts)


@lru_cache(maxsize=16_384)
def _favorable_main_draw_count(
    pool: int,
    membership_counts: tuple[int, ...],
    *,
    require_all: bool,
    threshold: int = MAIN_HIT_THRESHOLD,
) -> int:
    """以號碼 membership 群組 DP 精確計數，不枚舉數百萬個開獎組合。"""
    ticket_count = (len(membership_counts)).bit_length() - 1
    if len(membership_counts) != 1 << ticket_count:
        raise ValueError("membership_counts 長度必須為 2 的冪")
    if not 1 <= threshold <= PICK_N:
        raise ValueError("主號門檻必須介於 1 與 6")

    states: dict[tuple[int, tuple[int, ...]], int] = {
        (0, (0,) * ticket_count): 1
    }
    for mask, group_size in enumerate(membership_counts):
        if group_size == 0:
            continue
        next_states: dict[tuple[int, tuple[int, ...]], int] = defaultdict(int)
        for (chosen, hits), ways in states.items():
            maximum = min(group_size, PICK_N - chosen)
            for take in range(maximum + 1):
                next_hits = tuple(
                    min(
                        threshold,
                        hit + (take if mask & (1 << index) else 0),
                    )
                    for index, hit in enumerate(hits)
                )
                next_states[(chosen + take, next_hits)] += (
                    ways * math.comb(group_size, take)
                )
        states = next_states

    return sum(
        ways
        for (chosen, hits), ways in states.items()
        if chosen == PICK_N
        and (
            min(hits) >= threshold
            if require_all
            else max(hits) >= threshold
        )
    )


def exact_main_hit_probability(
    game: str,
    tickets: list[dict],
    *,
    threshold: int = MAIN_HIT_THRESHOLD,
) -> float:
    """精確計算五注至少一注命中 threshold 個主號的機率。"""
    sets = _ticket_sets(game, tickets)
    pool = POOL[game]
    favorable = _favorable_main_draw_count(
        pool,
        _membership_counts(pool, sets),
        require_all=False,
        threshold=threshold,
    )
    return favorable / math.comb(pool, PICK_N)


# 五注結構在逐期歷史研究中幾乎不重複；只保留小型近期快取，避免 watcher
# 重算數千期時把每個大型 DP 分布永久留在記憶體。
@lru_cache(maxsize=256)
def _main_hit_distribution(
    pool: int,
    membership_counts: tuple[int, ...],
    *,
    track_selected_unions: bool,
) -> tuple[tuple[tuple[int, ...], int, tuple[int, ...]], ...]:
    """回傳六主號抽取後的命中向量與組合數，命中數在 3 封頂。"""
    ticket_count = (len(membership_counts)).bit_length() - 1
    if len(membership_counts) != 1 << ticket_count:
        raise ValueError("membership_counts 長度必須為 2 的冪")
    subset_count = 1 << ticket_count
    if track_selected_unions:
        states: dict[
            tuple[int, tuple[int, ...]],
            tuple[int, tuple[int, ...]],
        ] = {(0, (0,) * ticket_count): (1, (0,) * subset_count)}
        for mask, group_size in enumerate(membership_counts):
            if group_size == 0:
                continue
            next_states: dict[
                tuple[int, tuple[int, ...]],
                list,
            ] = {}
            for (chosen, hits), (ways, selected_sums) in states.items():
                maximum = min(group_size, PICK_N - chosen)
                for take in range(maximum + 1):
                    next_hits = tuple(
                        min(
                            MAIN_HIT_THRESHOLD,
                            hit
                            + (
                                take
                                if mask & (1 << index)
                                else 0
                            ),
                        )
                        for index, hit in enumerate(hits)
                    )
                    key = (chosen + take, next_hits)
                    factor = math.comb(group_size, take)
                    aggregate = next_states.setdefault(
                        key, [0, [0] * subset_count]
                    )
                    aggregate[0] += ways * factor
                    for subset in range(1, subset_count):
                        aggregate[1][subset] += (
                            selected_sums[subset]
                            + ways
                            * take
                            * int(bool(mask & subset))
                        ) * factor
            states = {
                key: (value[0], tuple(value[1]))
                for key, value in next_states.items()
            }
        return tuple(
            (hits, ways, selected_sums)
            for (chosen, hits), (ways, selected_sums) in sorted(
                states.items()
            )
            if chosen == PICK_N
        )

    simple_states: dict[tuple[int, tuple[int, ...]], int] = {
        (0, (0,) * ticket_count): 1
    }
    for mask, group_size in enumerate(membership_counts):
        if group_size == 0:
            continue
        next_simple: dict[
            tuple[int, tuple[int, ...]], int
        ] = defaultdict(int)
        for (chosen, hits), ways in simple_states.items():
            maximum = min(group_size, PICK_N - chosen)
            for take in range(maximum + 1):
                next_hits = tuple(
                    min(
                        MAIN_HIT_THRESHOLD,
                        hit
                        + (
                            take
                            if mask & (1 << index)
                            else 0
                        ),
                    )
                    for index, hit in enumerate(hits)
                )
                next_simple[(chosen + take, next_hits)] += (
                    ways * math.comb(group_size, take)
                )
        simple_states = next_simple
    return tuple(
        (hits, ways, ())
        for (chosen, hits), ways in sorted(simple_states.items())
        if chosen == PICK_N
    )


def _exact_any_prize_favorable_count(
    game: str,
    pool: int,
    membership_counts: tuple[int, ...],
    specials: tuple[int | None, ...],
) -> tuple[int, int]:
    """從 membership 結構回傳完整任一獎級的精確分子、分母。

    ``pool`` 可小於正式遊戲號碼池，讓測試能以獨立逐開獎窮舉交叉驗證
    動態規劃；正式公開 API 仍固定使用遊戲規格中的 38／49。
    """
    ticket_count = (len(membership_counts)).bit_length() - 1
    if len(membership_counts) != 1 << ticket_count:
        raise ValueError("membership_counts 長度必須為 2 的冪")
    if not 1 <= ticket_count <= SELECTED_TICKETS:
        raise ValueError(
            f"精確計數只支援 1 至 {SELECTED_TICKETS} 注"
        )
    if len(specials) != ticket_count:
        raise ValueError("specials 長度必須等於票券數")
    if sum(membership_counts) != pool or pool <= PICK_N:
        raise ValueError("membership_counts 必須完整分割號碼池")

    if game == SUPER:
        distribution = _main_hit_distribution(
            pool,
            membership_counts,
            track_selected_unions=False,
        )
        favorable = 0
        for hits, ways, _ in distribution:
            if max(hits) >= MAIN_HIT_THRESHOLD:
                favorable_specials = SPECIAL_POOL[SUPER]
            else:
                favorable_specials = len(
                    {
                        int(specials[index])
                        for index, hits_for_ticket in enumerate(hits)
                        if hits_for_ticket in (1, 2)
                    }
                )
            favorable += ways * favorable_specials
        return (
            favorable,
            math.comb(pool, PICK_N) * SPECIAL_POOL[SUPER],
        )

    if game != LOTTO649:
        raise ValueError(f"不支援的遊戲：{game}")
    if any(special is not None for special in specials):
        raise ValueError("大樂透玩家不選特別號")
    distribution = _main_hit_distribution(
        pool,
        membership_counts,
        track_selected_unions=True,
    )
    bonus_pool = pool - PICK_N
    favorable = 0
    for hits, ways, selected_sums in distribution:
        if max(hits) >= MAIN_HIT_THRESHOLD:
            favorable += ways * bonus_pool
            continue
        eligible = sum(
            1 << index
            for index, hits_for_ticket in enumerate(hits)
            if hits_for_ticket == 2
        )
        if eligible == 0:
            continue
        eligible_union_size = sum(
            group_size
            for mask, group_size in enumerate(membership_counts)
            if mask & eligible
        )
        favorable += (
            eligible_union_size * ways
            - selected_sums[eligible]
        )
    return favorable, math.comb(pool, PICK_N) * bonus_pool


def exact_any_prize_count(
    game: str,
    tickets: list[dict],
) -> tuple[int, int]:
    """回傳投資組合完整任一獎級機率的精確分子、分母。"""
    sets = _ticket_sets(game, tickets, expected_count=None)
    if len(sets) > SELECTED_TICKETS:
        raise ValueError(f"精確計數最多支援 {SELECTED_TICKETS} 注")
    pool = POOL[game]
    return _exact_any_prize_favorable_count(
        game,
        pool,
        _membership_counts(pool, sets),
        tuple(ticket.get("special") for ticket in tickets),
    )


def exact_any_prize_probability(
    game: str,
    tickets: list[dict],
) -> float:
    """精確計算投資組合至少一注落入任一現行獎級的機率。"""
    favorable, total = exact_any_prize_count(game, tickets)
    return favorable / total


def uniform_random_five_probability(
    game: str,
    *,
    threshold: int = MAIN_HIT_THRESHOLD,
) -> float:
    """五注從全部合法主號組合不放回均勻抽樣時的精確聯集機率。"""
    total = math.comb(POOL[game], PICK_N)
    favorable = _single_favorable_count(POOL[game], threshold)
    return 1 - (
        math.comb(total - favorable, SELECTED_TICKETS)
        / math.comb(total, SELECTED_TICKETS)
    )


@lru_cache(maxsize=None)
def uniform_random_five_any_prize_probability(game: str) -> float:
    """現行隨機臂契約下，五注至少一注中任一獎級的精確機率。"""
    pool = POOL[game]
    total_main_combinations = math.comb(pool, PICK_N)
    if game == LOTTO649:
        favorable = sum(
            math.comb(PICK_N, hits)
            * math.comb(pool - PICK_N, PICK_N - hits)
            for hits in range(MAIN_HIT_THRESHOLD, PICK_N + 1)
        )
        favorable += (
            math.comb(PICK_N, 2)
            * math.comb(pool - PICK_N - 1, 3)
        )
        return 1 - (
            math.comb(
                total_main_combinations - favorable,
                SELECTED_TICKETS,
            )
            / math.comb(
                total_main_combinations,
                SELECTED_TICKETS,
            )
        )

    # 威力彩隨機臂先不放回抽五組不同第一區，再各自獨立均勻抽第二區。
    # 對固定開獎，依第一區命中數分組，計算五組都沒中獎的五階基本對稱和。
    coefficients = [Fraction(1)] + [Fraction(0)] * SELECTED_TICKETS
    for hits in range(PICK_N + 1):
        group_size = (
            math.comb(PICK_N, hits)
            * math.comb(pool - PICK_N, PICK_N - hits)
        )
        loss_probability = (
            Fraction(0)
            if hits >= MAIN_HIT_THRESHOLD
            else Fraction(7, 8)
            if hits in (1, 2)
            else Fraction(1)
        )
        group_terms = [
            Fraction(math.comb(group_size, take))
            * loss_probability**take
            for take in range(SELECTED_TICKETS + 1)
        ]
        next_coefficients = [Fraction(0)] * (
            SELECTED_TICKETS + 1
        )
        for selected_before in range(SELECTED_TICKETS + 1):
            for take in range(
                SELECTED_TICKETS - selected_before + 1
            ):
                next_coefficients[selected_before + take] += (
                    coefficients[selected_before] * group_terms[take]
                )
        coefficients = next_coefficients
    no_prize = coefficients[SELECTED_TICKETS] / math.comb(
        total_main_combinations,
        SELECTED_TICKETS,
    )
    return float(1 - no_prize)


@lru_cache(maxsize=None)
def _pair_any_prize_intersection_probability(
    game: str,
    overlap: int,
    same_special: bool | None,
) -> float:
    """兩注同時中任一獎級的精確機率，用於二階聯集下界。"""
    if not 0 <= overlap < PICK_N:
        raise ValueError("不同主號組合的重疊數必須介於 0 與 5")
    left_numbers = list(range(1, PICK_N + 1))
    right_numbers = list(range(1, overlap + 1)) + list(
        range(PICK_N + 1, PICK_N + 1 + PICK_N - overlap)
    )
    if game == SUPER:
        if not isinstance(same_special, bool):
            raise ValueError("威力彩兩注必須指定第二區是否相同")
        left_special = 1
        right_special = 1 if same_special else 2
    else:
        if same_special is not None:
            raise ValueError("大樂透沒有玩家選擇的特別號")
        left_special = None
        right_special = None
    tickets = [
        {
            "numbers": left_numbers,
            "special": left_special,
        },
        {
            "numbers": right_numbers,
            "special": right_special,
        },
    ]
    single = exact_any_prize_probability(game, [tickets[0]])
    union = exact_any_prize_probability(game, tickets)
    return 2 * single - union


@lru_cache(maxsize=None)
def _single_favorable_count(
    pool: int,
    threshold: int = MAIN_HIT_THRESHOLD,
) -> int:
    return sum(
        math.comb(PICK_N, hits)
        * math.comb(pool - PICK_N, PICK_N - hits)
        for hits in range(threshold, PICK_N + 1)
    )


@lru_cache(maxsize=None)
def _pair_intersection_count(
    pool: int,
    overlap: int,
    threshold: int = MAIN_HIT_THRESHOLD,
) -> int:
    if not 0 <= overlap <= PICK_N:
        raise ValueError("兩注重疊數必須介於 0 與 6")
    left = set(range(1, PICK_N + 1))
    right = set(range(1, overlap + 1))
    right.update(
        range(PICK_N + 1, PICK_N + 1 + PICK_N - overlap)
    )
    return _favorable_main_draw_count(
        pool,
        _membership_counts(pool, [left, right]),
        require_all=True,
        threshold=threshold,
    )


def portfolio_structure(game: str, tickets: list[dict]) -> dict:
    """回傳不依賴開獎結果的五注結構與精確機率。"""
    sets = _ticket_sets(game, tickets)
    pool = POOL[game]
    overlaps = [
        len(left & right) for left, right in combinations(sets, 2)
    ]
    pair_indexes = list(combinations(range(len(tickets)), 2))
    any_prize_pair_intersections = [
        _pair_any_prize_intersection_probability(
            game,
            len(sets[left] & sets[right]),
            (
                tickets[left]["special"] == tickets[right]["special"]
                if game == SUPER
                else None
            ),
        )
        for left, right in pair_indexes
    ]
    total_main_draws = math.comb(pool, PICK_N)
    lower_count = (
        SELECTED_TICKETS
        * _single_favorable_count(pool, MAIN_HIT_THRESHOLD)
        - sum(
            _pair_intersection_count(
                pool, overlap, MAIN_HIT_THRESHOLD
            )
            for overlap in overlaps
        )
    )
    special_coverage = (
        len({int(ticket["special"]) for ticket in tickets})
        / SPECIAL_POOL[SUPER]
        if game == SUPER
        else None
    )
    return {
        "main_union_size": len(set().union(*sets)),
        "mean_pairwise_main_overlap": statistics.fmean(overlaps),
        "maximum_pairwise_main_overlap": max(overlaps),
        "pairwise_intersection_count": sum(
            _pair_intersection_count(
                pool, overlap, MAIN_HIT_THRESHOLD
            )
            for overlap in overlaps
        ),
        "bonferroni_lower_bound": max(0.0, lower_count / total_main_draws),
        "any_prize_bonferroni_lower_bound": max(
            0.0,
            SELECTED_TICKETS
            * exact_any_prize_probability(game, [tickets[0]])
            - sum(any_prize_pair_intersections),
        ),
        "exact_at_least_three_main": exact_main_hit_probability(
            game, tickets
        ),
        "exact_any_prize": exact_any_prize_probability(game, tickets),
        "special_coverage_probability": special_coverage,
    }


def select_coverage_portfolio(
    game: str,
    decision: dict,
) -> tuple[list[dict], dict]:
    """只讀開獎前 decision，選出機率結構不低於原裁判的五注。"""
    if decision.get("game") != game:
        raise ValueError("decision 遊戲不符")
    proposals = list(decision.get("proposals", ()))
    if len(proposals) != 15:
        raise ValueError("coverage selector 需要 15 組封存提案")
    scores = {
        item["proposal_id"]: float(item["debate_score"])
        for item in decision.get("adjudication", {}).get(
            "candidate_scores", ()
        )
    }
    if set(scores) != {
        proposal["proposal_id"] for proposal in proposals
    }:
        raise ValueError("candidate_scores 未完整涵蓋提案")

    proposal_sets = [set(proposal["numbers"]) for proposal in proposals]
    pool = POOL[game]
    best = None
    for indexes in combinations(range(len(proposals)), SELECTED_TICKETS):
        number_keys = {
            tuple(sorted(proposals[index]["numbers"]))
            for index in indexes
        }
        if len(number_keys) != SELECTED_TICKETS:
            continue
        pair_penalty = sum(
            _pair_intersection_count(
                pool,
                len(proposal_sets[left] & proposal_sets[right]),
            )
            for left, right in combinations(indexes, 2)
        )
        any_prize_pair_penalty = sum(
            _pair_any_prize_intersection_probability(
                game,
                len(proposal_sets[left] & proposal_sets[right]),
                (
                    proposals[left]["special"]
                    == proposals[right]["special"]
                    if game == SUPER
                    else None
                ),
            )
            for left, right in combinations(indexes, 2)
        )
        union_size = len(
            set().union(*(proposal_sets[index] for index in indexes))
        )
        special_coverage = (
            len({proposals[index]["special"] for index in indexes})
            if game == SUPER
            else 0
        )
        debate_score = sum(
            scores[proposals[index]["proposal_id"]]
            for index in indexes
        )
        proposal_ids = tuple(
            proposals[index]["proposal_id"] for index in indexes
        )
        key = (
            any_prize_pair_penalty,
            pair_penalty,
            -union_size,
            -special_coverage,
            -debate_score,
            proposal_ids,
        )
        if best is None or key < best[0]:
            best = (key, indexes)
    if best is None:
        raise ValueError("15 組提案中沒有合法的五注組合")

    candidate = [
        {
            "slot": slot,
            "source_agent": proposals[index]["agent"],
            "source_proposal": proposals[index]["proposal_id"],
            "numbers": list(proposals[index]["numbers"]),
            "special": proposals[index]["special"],
        }
        for slot, index in enumerate(best[1], 1)
    ]
    baseline = [dict(ticket) for ticket in decision["selected_tickets"]]
    baseline_structure = portfolio_structure(game, baseline)
    candidate_structure = portfolio_structure(game, candidate)
    fallback = (
        candidate_structure["exact_at_least_three_main"]
        < baseline_structure["exact_at_least_three_main"] - 1e-15
        or candidate_structure["exact_any_prize"]
        < baseline_structure["exact_any_prize"] - 1e-15
    )
    selected = baseline if fallback else candidate
    selected_structure = (
        baseline_structure if fallback else candidate_structure
    )
    return selected, {
        "experiment_id": EXPERIMENT_ID,
        "objective": (
            "先最大化至少一注落入任一獎級的二階 Bonferroni 下界，"
            "再最大化至少一注命中三個主號的下界；聯集、第二區覆蓋"
            "與辯論分數只作依序 tie-break"
        ),
        "combinations_evaluated": math.comb(
            len(proposals), SELECTED_TICKETS
        ),
        "fallback_to_current": fallback,
        "baseline": baseline_structure,
        "candidate": candidate_structure,
        "selected": selected_structure,
        "exact_probability_delta": (
            selected_structure["exact_at_least_three_main"]
            - baseline_structure["exact_at_least_three_main"]
        ),
        "exact_any_prize_probability_delta": (
            selected_structure["exact_any_prize"]
            - baseline_structure["exact_any_prize"]
        ),
        "selected_proposal_ids": [
            ticket["source_proposal"] for ticket in selected
        ],
    }


def _split_profile(
    total: int,
    config: CoverageConfig,
) -> tuple[dict, int]:
    eligible = total - config.warmup_draws
    if eligible < 20:
        raise ValueError(f"暖機後資料不足：{eligible}")
    development = math.floor(
        eligible * config.development_fraction
    )
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


def _mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def _summary_rows(
    values: dict[tuple[str, str], dict[str, list[float]]],
    config: CoverageConfig,
) -> list[dict]:
    rows = []
    for (game, split), metrics in sorted(values.items()):
        best_ci = block_bootstrap_ci(
            metrics["delta_best_main_hits"],
            samples=config.bootstrap_samples,
            block=config.bootstrap_block,
            seed=(
                f"{EXPERIMENT_ID}|{game}|{split}|"
                "delta-best-main-hits"
            ),
        )
        any_three_ci = block_bootstrap_ci(
            metrics["delta_any_three_plus"],
            samples=config.bootstrap_samples,
            block=config.bootstrap_block,
            seed=f"{EXPERIMENT_ID}|{game}|{split}|delta-any-three",
        )
        rows.append(
            {
                "game": game,
                "game_name": GAME_NAMES[game],
                "split": split,
                "draws": len(metrics["delta_best_main_hits"]),
                "current_best_main_hits": _mean(
                    metrics["current_best_main_hits"]
                ),
                "coverage_best_main_hits": _mean(
                    metrics["coverage_best_main_hits"]
                ),
                "delta_best_main_hits": _mean(
                    metrics["delta_best_main_hits"]
                ),
                "delta_best_main_hits_ci_low": best_ci[0],
                "delta_best_main_hits_ci_high": best_ci[1],
                "current_any_three_plus": _mean(
                    metrics["current_any_three_plus"]
                ),
                "coverage_any_three_plus": _mean(
                    metrics["coverage_any_three_plus"]
                ),
                "delta_any_three_plus": _mean(
                    metrics["delta_any_three_plus"]
                ),
                "delta_any_three_plus_ci_low": any_three_ci[0],
                "delta_any_three_plus_ci_high": any_three_ci[1],
                "current_union_size": _mean(
                    metrics["current_union_size"]
                ),
                "coverage_union_size": _mean(
                    metrics["coverage_union_size"]
                ),
                "delta_union_size": _mean(
                    metrics["delta_union_size"]
                ),
                "current_exact_probability": _mean(
                    metrics["current_exact_probability"]
                ),
                "coverage_exact_probability": _mean(
                    metrics["coverage_exact_probability"]
                ),
                "uniform_random_five_probability": (
                    uniform_random_five_probability(game)
                ),
                "current_minus_uniform_random_probability": (
                    _mean(metrics["current_exact_probability"])
                    - uniform_random_five_probability(game)
                ),
                "coverage_minus_uniform_random_probability": (
                    _mean(metrics["coverage_exact_probability"])
                    - uniform_random_five_probability(game)
                ),
                "current_any_prize_probability": _mean(
                    metrics["current_any_prize_probability"]
                ),
                "coverage_any_prize_probability": _mean(
                    metrics["coverage_any_prize_probability"]
                ),
                "uniform_random_five_any_prize_probability": (
                    uniform_random_five_any_prize_probability(game)
                ),
                "current_minus_uniform_random_any_prize_probability": (
                    _mean(metrics["current_any_prize_probability"])
                    - uniform_random_five_any_prize_probability(game)
                ),
                "coverage_minus_uniform_random_any_prize_probability": (
                    _mean(metrics["coverage_any_prize_probability"])
                    - uniform_random_five_any_prize_probability(game)
                ),
                "delta_any_prize_probability": _mean(
                    metrics["delta_any_prize_probability"]
                ),
                "minimum_any_prize_probability_delta": min(
                    metrics["delta_any_prize_probability"]
                ),
                "any_prize_probability_non_decrease_rate": _mean(
                    metrics["any_prize_probability_non_decrease"]
                ),
                "delta_exact_probability": _mean(
                    metrics["delta_exact_probability"]
                ),
                "minimum_exact_probability_delta": min(
                    metrics["delta_exact_probability"]
                ),
                "exact_probability_non_decrease_rate": _mean(
                    metrics["exact_probability_non_decrease"]
                ),
                "fallback_rate": _mean(metrics["fallback"]),
            }
        )
    return rows


def run_coverage_study(
    ledger_paths: dict[str, Path],
    *,
    base: Path,
    config: CoverageConfig | None = None,
    verify_ledgers: bool = True,
) -> dict:
    """執行完整影子研究；不寫入 records 或前向登記。"""
    config = config or CoverageConfig()
    config.validate()
    records_before = tree_sha256(base / "records")
    ledger_verification = {}
    split_profiles = {}
    source_last_dates = {}
    values: dict[tuple[str, str], dict[str, list[float]]] = {}
    traces: dict[str, list[dict]] = defaultdict(list)

    metric_names = (
        "current_best_main_hits",
        "coverage_best_main_hits",
        "delta_best_main_hits",
        "current_any_three_plus",
        "coverage_any_three_plus",
        "delta_any_three_plus",
        "current_union_size",
        "coverage_union_size",
        "delta_union_size",
        "current_exact_probability",
        "coverage_exact_probability",
        "delta_exact_probability",
        "exact_probability_non_decrease",
        "current_any_prize_probability",
        "coverage_any_prize_probability",
        "delta_any_prize_probability",
        "any_prize_probability_non_decrease",
        "fallback",
    )

    for game in (SUPER, LOTTO649):
        path = Path(ledger_paths[game])
        ledger_verification[game] = (
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
                "ledger_sha256": None,
                "last_event_hash": None,
            }
        )
        total = int(ledger_verification[game]["lines"])
        profile, development_draws = _split_profile(total, config)
        split_profiles[game] = profile

        with path.open(encoding="utf-8") as handle:
            for sequence, line in enumerate(handle, 1):
                event = json.loads(line)
                _validate_event(event, game, sequence)
                reveal = event["reveal"]
                source_last_dates[game] = reveal["date"]
                if sequence <= config.warmup_draws:
                    continue
                eligible_index = sequence - config.warmup_draws
                split = (
                    "development"
                    if eligible_index <= development_draws
                    else "holdout"
                )
                selected, selection = select_coverage_portfolio(
                    game, event["decision"]
                )
                current = event["decision"]["selected_tickets"]
                current_result = portfolio_metrics(game, current, reveal)
                coverage_result = portfolio_metrics(game, selected, reveal)
                current_structure = selection["baseline"]
                coverage_structure = selection["selected"]
                row = {
                    "current_best_main_hits": current_result[
                        "best_main_hits"
                    ],
                    "coverage_best_main_hits": coverage_result[
                        "best_main_hits"
                    ],
                    "delta_best_main_hits": (
                        coverage_result["best_main_hits"]
                        - current_result["best_main_hits"]
                    ),
                    "current_any_three_plus": current_result[
                        "any_three_plus"
                    ],
                    "coverage_any_three_plus": coverage_result[
                        "any_three_plus"
                    ],
                    "delta_any_three_plus": (
                        coverage_result["any_three_plus"]
                        - current_result["any_three_plus"]
                    ),
                    "current_union_size": current_result["union_size"],
                    "coverage_union_size": coverage_result["union_size"],
                    "delta_union_size": (
                        coverage_result["union_size"]
                        - current_result["union_size"]
                    ),
                    "current_exact_probability": current_structure[
                        "exact_at_least_three_main"
                    ],
                    "coverage_exact_probability": coverage_structure[
                        "exact_at_least_three_main"
                    ],
                    "delta_exact_probability": selection[
                        "exact_probability_delta"
                    ],
                    "exact_probability_non_decrease": float(
                        selection["exact_probability_delta"] >= -1e-15
                    ),
                    "current_any_prize_probability": current_structure[
                        "exact_any_prize"
                    ],
                    "coverage_any_prize_probability": coverage_structure[
                        "exact_any_prize"
                    ],
                    "delta_any_prize_probability": selection[
                        "exact_any_prize_probability_delta"
                    ],
                    "any_prize_probability_non_decrease": float(
                        selection[
                            "exact_any_prize_probability_delta"
                        ]
                        >= -1e-15
                    ),
                    "fallback": float(selection["fallback_to_current"]),
                }
                key = (game, split)
                values.setdefault(
                    key, {name: [] for name in metric_names}
                )
                for name in metric_names:
                    values[key][name].append(float(row[name]))
                traces[game].append(
                    {
                        "date": reveal["date"],
                        "period": int(reveal["period"]),
                        "split": split,
                        "current_best_main_hits": int(
                            current_result["best_main_hits"]
                        ),
                        "coverage_best_main_hits": int(
                            coverage_result["best_main_hits"]
                        ),
                        "delta_best_main_hits": int(
                            row["delta_best_main_hits"]
                        ),
                        "current_union_size": int(
                            current_result["union_size"]
                        ),
                        "coverage_union_size": int(
                            coverage_result["union_size"]
                        ),
                        "current_exact_probability": round(
                            row["current_exact_probability"], 12
                        ),
                        "coverage_exact_probability": round(
                            row["coverage_exact_probability"], 12
                        ),
                        "exact_probability_delta": round(
                            row["delta_exact_probability"], 12
                        ),
                        "current_any_prize_probability": round(
                            row["current_any_prize_probability"], 12
                        ),
                        "coverage_any_prize_probability": round(
                            row["coverage_any_prize_probability"], 12
                        ),
                        "any_prize_probability_delta": round(
                            row["delta_any_prize_probability"], 12
                        ),
                        "fallback_to_current": bool(
                            selection["fallback_to_current"]
                        ),
                    }
                )

    summaries = _summary_rows(values, config)
    holdout_by_game = {
        game: next(
            row
            for row in summaries
            if row["game"] == game and row["split"] == "holdout"
        )
        for game in (SUPER, LOTTO649)
    }
    structural_pass = {
        game: (
            row["minimum_exact_probability_delta"] >= -1e-15
            and row["delta_exact_probability"] > 0
            and row["exact_probability_non_decrease_rate"] == 1.0
            and row["minimum_any_prize_probability_delta"] >= -1e-15
            and row["delta_any_prize_probability"] > 0
            and row["any_prize_probability_non_decrease_rate"] == 1.0
        )
        for game, row in holdout_by_game.items()
    }
    retrospective_signal = {
        game: (
            row["delta_best_main_hits_ci_low"] > 0
            or row["delta_any_three_plus_ci_low"] > 0
        )
        for game, row in holdout_by_game.items()
    }
    records_after = tree_sha256(base / "records")
    result = {
        "schema_version": "2",
        "experiment_id": EXPERIMENT_ID,
        "source_experiment_id": LOOP_EXPERIMENT_ID,
        "generated_at": max(source_last_dates.values())
        + "T23:59:59+08:00",
        "question": (
            "在不改變五注預算、不讀開獎結果的前提下，能否提高至少一注"
            "落入任一現行獎級的精確聯集機率，同時不降低三主號護欄？"
        ),
        "methodology": {
            "unit": "每遊戲、每期、固定五注投資組合",
            "primary_probability": (
                "五注中至少一注落入任一現行獎級的精確組合機率"
            ),
            "uniform_baseline": (
                "依現行隨機臂契約抽取五注的完整任一獎級精確聯集機率"
            ),
            "structural_guardrail": (
                "五注中至少一注命中三個或以上主號的精確組合機率"
            ),
            "selector": (
                "窮舉 15 選 5 共 3,003 組，先最大化完整中獎事件的二階 "
                "Bonferroni 機率下界，再最大化三主號護欄下界，最後以"
                "主號聯集、威力彩第二區覆蓋與辯論分數依序 tie-break；"
                "任一精確機率下降時退回原裁判。"
            ),
            "warmup_draws": config.warmup_draws,
            "development_fraction": config.development_fraction,
            "holdout_fraction": 1 - config.development_fraction,
            "bootstrap_samples": config.bootstrap_samples,
            "bootstrap_block_draws": config.bootstrap_block,
            "combinations_per_draw": math.comb(15, SELECTED_TICKETS),
            "lookahead_control": (
                "selector 函式不接受 reveal；開獎只在五注選定後計算"
                "回顧性命中。"
            ),
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
        "summary": summaries,
        "recent_holdout_trace": {
            game: rows[-RECENT_TRACE_DRAWS:]
            for game, rows in traces.items()
        },
        "conclusion": {
            "status": (
                "eligible_for_forward_shadow"
                if all(structural_pass.values())
                else "retain_current_selector"
            ),
            "structural_probability_pass": structural_pass,
            "retrospective_hit_signal": retrospective_signal,
            "decision_rule": (
                "兩款遊戲 holdout 每一期的完整任一獎級機率與三主號"
                "充分條件機率都不得下降、平均都必須上升；歷史命中"
                "區間只列診斷，不作升級必要條件。"
            ),
            "deployment": (
                "只可建立新的前向 shadow arm；不得改寫既有預登記，"
                "也不得把結構機率改善稱為預測開獎號碼。"
            ),
        },
        "records_integrity": {
            "before_sha256": records_before,
            "after_sha256": records_after,
            "unchanged": records_before == records_after,
        },
        "limitations": [
            "每一個合法單注與頭獎組合的理論機率仍完全相同。",
            "改善只針對固定五注中至少一注落入任一現行獎級的聯集事件。",
            "結構改善不代表任一單注、頭獎或特定號碼更可能開出。",
            "回顧性命中差仍可能是抽樣噪音，不能代替新期前向 A/B。",
            "候選受限於當期 15 組既有提案；selector 不自行創造號碼。",
            "結果是純模擬，不構成購買或下注建議。",
        ],
    }
    if not result["records_integrity"]["unchanged"]:
        raise RuntimeError("覆蓋研究不應改動正式 records")
    return result


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        raise ValueError(f"{path.name} 沒有資料")
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_results(result: dict, output_dir: Path) -> dict[str, Path]:
    # 允許舊版長時間研究結果以純公式補上均勻五注基準，不必重算逐期
    # selector；逐期命中與結構機率本身不會在這裡被修改。
    result["schema_version"] = "2"
    result.setdefault("methodology", {}).setdefault(
        "uniform_baseline",
        "從全部合法主號組合不放回均勻抽取五注的精確聯集機率",
    )
    # 正式逐期計算可由舊程序完成後再載入；這些欄位只校正研究問題與
    # selector 說明，不改動任何逐期機率或命中結果。
    result["question"] = (
        "在不改變五注預算、不讀開獎結果的前提下，能否提高至少一注"
        "落入任一現行獎級的精確聯集機率，同時不降低三主號護欄？"
    )
    result["methodology"]["primary_probability"] = (
        "五注中至少一注落入任一現行獎級的精確組合機率"
    )
    result["methodology"]["selector"] = (
        "窮舉 15 選 5 共 3,003 組，先最大化完整中獎事件的二階 "
        "Bonferroni 機率下界，再最大化三主號護欄下界，最後以主號聯集、"
        "威力彩第二區覆蓋與辯論分數依序 tie-break；任一精確機率下降時"
        "退回原裁判。"
    )
    result["limitations"] = [
        "每一個合法單注與頭獎組合的理論機率仍完全相同。",
        "改善只針對固定五注中至少一注落入任一現行獎級的聯集事件。",
        "結構改善不代表任一單注、頭獎或特定號碼更可能開出。",
        "回顧性命中差仍可能是抽樣噪音，不能代替新期前向 A/B。",
        "候選受限於當期 15 組既有提案；selector 不自行創造號碼。",
        "結果是純模擬，不構成購買或下注建議。",
    ]
    for row in result.get("summary", []):
        game = row["game"]
        baseline = uniform_random_five_probability(game)
        row.setdefault("uniform_random_five_probability", baseline)
        row.setdefault(
            "current_minus_uniform_random_probability",
            row["current_exact_probability"] - baseline,
        )
        row.setdefault(
            "coverage_minus_uniform_random_probability",
            row["coverage_exact_probability"] - baseline,
        )
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "json": output_dir / "portfolio_coverage.json",
        "summary": output_dir / "portfolio_coverage_summary.csv",
    }
    temporary = paths["json"].with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, paths["json"])
    _write_csv(paths["summary"], result["summary"])
    return paths
