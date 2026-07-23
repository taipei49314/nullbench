"""威力彩五注歷史壓力獲利率的無 overlap 守門全域最優證明。

前一份 Pareto 證書只枚舉仍保留至少四主號全域上限的結構。本模組移除
該限制，允許任意五張六號票（證明甚至涵蓋重複票），以有限整數枚舉與
鬆弛上界證明「十個三票共享號碼＋五注同一第二區」最大化凍結歷史最低
實領壓力口徑的五注嚴格獲利機率。
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from functools import lru_cache
from itertools import combinations, permutations, product
import json
import math
import os
from pathlib import Path

from engine.agent_loop import canonical_hash
from engine.games import (
    GAME_NAMES,
    LOTTO649,
    PICK_N,
    POOL,
    SPECIAL_POOL,
    SUPER,
    TICKET_PRICE,
    TIERS,
)
from research.gates import tree_sha256
from research.profit_probability import (
    EXPERIMENT_ID as PARETO_EXPERIMENT_ID,
    _exact_main_hit_distribution,
    _exact_super_payout_counts,
    _history_snapshot,
    _payout_table,
)
from research.structural_optimum import OFFICIAL_RULE_URLS


EXPERIMENT_ID = "five-ticket-unconstrained-profit-optimum-proof-v2"
SOURCE_PARETO_CERTIFICATE_HASH = (
    "b91fb1e1f4a4f7ba6478389b05182761472fcdc9784460967b9011a739356ee4"
)
PORTFOLIO_TICKETS = 5
PORTFOLIO_COST = PORTFOLIO_TICKETS * TICKET_PRICE[SUPER]
TOTAL_TICKET_INCIDENCES = PORTFOLIO_TICKETS * PICK_N
MAIN_DRAW_DENOMINATOR = math.comb(POOL[SUPER], PICK_N)
FULL_DENOMINATOR = MAIN_DRAW_DENOMINATOR * SPECIAL_POOL[SUPER]
MAIN_FOUR_GLOBAL_MAXIMUM_COUNT = 38_165
EXPECTED_MULTIPLICITY_HISTOGRAMS = 674
EXPECTED_THREE_UNIFORM_PROFILES = 158
TRIPLE_MASKS = tuple(
    mask for mask in range(1, 1 << PORTFOLIO_TICKETS)
    if bin(mask).count("1") == 3
)
OPTIMUM_SPECIAL_PATTERN = (0, 0, 0, 0, 0)
PROPER_SPECIAL_COMPOSITIONS = (
    (4, 1),
    (3, 2),
    (3, 1, 1),
    (2, 2, 1),
    (2, 1, 1, 1),
    (1, 1, 1, 1, 1),
)
MACRO_BLOCK_COUNTS = {
    (4, 1): 1,
    (3, 2): 1,
    (3, 1, 1): 1,
    (2, 2, 1): 2,
    (2, 1, 1, 1): 1,
    (1, 1, 1, 1, 1): 1,
}
EXPECTED_RELAXED_PROFILE_COUNTS = {
    (4, 1): 8_621,
    (3, 2): 42_125,
    (3, 1, 1): 42_125,
    (2, 2, 1): 8_621,
    (2, 1, 1, 1): 42_125,
    (1, 1, 1, 1, 1): 8_621,
}
EXPECTED_EMPIRICAL_PROPER_UPPERS = {
    (4, 1): 1_429_070,
    (3, 2): 1_582_520,
    (3, 1, 1): 1_173_320,
    (2, 2, 1): 1_534_195,
    (2, 1, 1, 1): 1_241_520,
    (1, 1, 1, 1, 1): 801_320,
}
NOMINAL_OPTIMUM_COUNT = 1_648_101
EXPECTED_NOMINAL_SINGLE_BLOCK_UPPERS = {
    1: 139_500,
    2: 725_555,
    3: 1_012_100,
    4: 1_162_055,
}
PAIR_MAIN_FOUR_INTERSECTION_COUNTS = (
    0,
    0,
    36,
    306,
    1_063,
    2_983,
    7_633,
)
EXPECTED_NOMINAL_PROPER_GLOBAL_UPPERS = {
    (4, 1): 1_606_875,
    (3, 2): 1_647_962,
    (3, 1, 1): 1_596_420,
    (2, 2, 1): 1_648_088,
    (2, 1, 1, 1): 1_449_375,
    (1, 1, 1, 1, 1): 1_002_820,
}
EXPECTED_NOMINAL_DANGER_CERTIFICATES = {
    (3, 2): {
        "dangerous_macro_histograms": 160,
        "labeled_degree_valid_refinements": 4_083,
        "cross_macro_survivors": 4_083,
        "hunter_survivors": 4_083,
        "canonical_exact_candidates": 565,
        "maximum_exact_nominal_strict_profit_count": 906_434,
    },
    (2, 2, 1): {
        "dangerous_macro_histograms": 2_098,
        "labeled_degree_valid_refinements": 1_721_537,
        "cross_macro_survivors": 814_501,
        "hunter_survivors": 75_195,
        "canonical_exact_candidates": 10_199,
        "maximum_exact_nominal_strict_profit_count": 606_888,
    },
}


@lru_cache(maxsize=1)
def multiplicity_histograms() -> tuple[tuple[int, ...], ...]:
    """列出號碼分別出現在 1 至 5 張票的全部 incidence 分割。"""
    rows = []
    for count_five in range(7):
        for count_four in range(8):
            for count_three in range(11):
                for count_two in range(16):
                    count_one = (
                        TOTAL_TICKET_INCIDENCES
                        - 5 * count_five
                        - 4 * count_four
                        - 3 * count_three
                        - 2 * count_two
                    )
                    row = (
                        count_one,
                        count_two,
                        count_three,
                        count_four,
                        count_five,
                    )
                    if count_one >= 0 and sum(row) <= POOL[SUPER]:
                        rows.append(row)
    result = tuple(sorted(rows))
    if len(result) != EXPECTED_MULTIPLICITY_HISTOGRAMS:
        raise RuntimeError("主號 multiplicity histogram 枚舉數量不符")
    return result


@lru_cache(maxsize=1024)
def weighted_hit_distribution(
    histogram: tuple[int, ...],
) -> tuple[tuple[int, int], ...]:
    """只依號碼出現在幾張票，計數六主號造成的總 ticket-hit incidence。"""
    if (
        len(histogram) != PORTFOLIO_TICKETS
        or sum(
            multiplicity * count
            for multiplicity, count in enumerate(histogram, 1)
        )
        != TOTAL_TICKET_INCIDENCES
        or sum(histogram) > POOL[SUPER]
    ):
        raise ValueError("非法的 multiplicity histogram")
    groups = (POOL[SUPER] - sum(histogram),) + histogram
    states: dict[tuple[int, int], int] = {(0, 0): 1}
    for multiplicity, group_size in enumerate(groups):
        next_states: dict[tuple[int, int], int] = defaultdict(int)
        for (chosen, total_hits), ways in states.items():
            for take in range(
                min(group_size, PICK_N - chosen) + 1
            ):
                next_states[
                    (
                        chosen + take,
                        total_hits + multiplicity * take,
                    )
                ] += ways * math.comb(group_size, take)
        states = dict(next_states)
    result = tuple(
        sorted(
            (total_hits, ways)
            for (chosen, total_hits), ways in states.items()
            if chosen == PICK_N
        )
    )
    if sum(ways for _, ways in result) != MAIN_DRAW_DENOMINATOR:
        raise RuntimeError("總 ticket-hit incidence 分布不守恆")
    return result


def _at_least_total_hits_count(
    histogram: tuple[int, ...],
    minimum: int,
) -> int:
    return sum(
        ways
        for total_hits, ways in weighted_hit_distribution(histogram)
        if total_hits >= minimum
    )


def _three_uniform_profiles() -> tuple[tuple[int, ...], ...]:
    """列出十個三票 membership mask 上、每票 degree=6 的全部 158 解。"""
    current: list[int] = []
    rows: list[tuple[int, ...]] = []

    def visit(
        position: int,
        remaining: tuple[int, ...],
    ) -> None:
        if position == len(TRIPLE_MASKS):
            if not any(remaining):
                rows.append(tuple(current))
            return
        mask = TRIPLE_MASKS[position]
        members = tuple(
            index
            for index in range(PORTFOLIO_TICKETS)
            if mask & (1 << index)
        )
        maximum = min(remaining[index] for index in members)
        for amount in range(maximum + 1):
            next_remaining = list(remaining)
            for index in members:
                next_remaining[index] -= amount
            current.append(amount)
            visit(position + 1, tuple(next_remaining))
            current.pop()

    visit(0, (PICK_N,) * PORTFOLIO_TICKETS)
    result = tuple(rows)
    if len(result) != EXPECTED_THREE_UNIFORM_PROFILES:
        raise RuntimeError("三均勻 membership profile 枚舉數量不符")
    return result


def _membership_counts_for_triple_profile(
    profile: tuple[int, ...],
) -> tuple[int, ...]:
    if len(profile) != len(TRIPLE_MASKS):
        raise ValueError("三均勻 profile 長度不符")
    counts = [0] * (1 << PORTFOLIO_TICKETS)
    for mask, amount in zip(TRIPLE_MASKS, profile):
        counts[mask] = amount
    counts[0] = POOL[SUPER] - sum(profile)
    if counts[0] < 0:
        raise ValueError("三均勻 profile 聯集超出號碼池")
    return tuple(counts)


@lru_cache(maxsize=1)
def _three_uniform_certificate() -> dict:
    rows = []
    for profile in _three_uniform_profiles():
        distribution = _exact_main_hit_distribution(
            POOL[SUPER],
            _membership_counts_for_triple_profile(profile),
        )
        four_count = sum(
            ways
            for hits, ways in distribution
            if max(hits) >= 4
        )
        rows.append((four_count, profile))
    maximum = max(count for count, _ in rows)
    winners = [
        profile for count, profile in rows if count == maximum
    ]
    second = max(
        count for count, _ in rows if count < maximum
    )
    if (
        maximum != 35_280
        or winners != [(1,) * len(TRIPLE_MASKS)]
        or second != 34_412
    ):
        raise RuntimeError("三均勻結構內的四主號最優證明不符")
    return {
        "profiles_evaluated": len(rows),
        "unique_maximum_profile": list(winners[0]),
        "maximum_at_least_four_main_count": maximum,
        "second_best_at_least_four_main_count": second,
        "unique_up_to_ticket_and_number_relabeling": True,
    }


def optimum_membership_counts() -> tuple[int, ...]:
    return _membership_counts_for_triple_profile(
        (1,) * len(TRIPLE_MASKS)
    )


def optimum_tickets() -> list[dict]:
    """十個三元 membership 各配置一碼的可讀代表。"""
    numbers = [[] for _ in range(PORTFOLIO_TICKETS)]
    for value, mask in enumerate(TRIPLE_MASKS, 1):
        for ticket_index in range(PORTFOLIO_TICKETS):
            if mask & (1 << ticket_index):
                numbers[ticket_index].append(value)
    return [
        {
            "slot": ticket_index + 1,
            "source_agent": "unconstrained_profit_proof",
            "source_proposal": f"triple-design:{ticket_index + 1}",
            "numbers": ticket_numbers,
            "special": 1,
        }
        for ticket_index, ticket_numbers in enumerate(numbers)
    ]


@lru_cache(maxsize=1)
def _multiplicity_certificate() -> dict:
    rows = [
        (
            _at_least_total_hits_count(histogram, 6),
            histogram,
        )
        for histogram in multiplicity_histograms()
    ]
    optimum_histogram = (0, 0, 10, 0, 0)
    maximum = max(count for count, _ in rows)
    winners = [
        histogram
        for count, histogram in rows
        if count == maximum
    ]
    second = max(
        count
        for count, histogram in rows
        if histogram != optimum_histogram
    )
    if (
        maximum != 1_401_141
        or winners != [optimum_histogram]
        or second != 1_245_971
    ):
        raise RuntimeError("總命中至少六次的 multiplicity 最優證明不符")
    non_optimum_common_special_upper = (
        8 * MAIN_FOUR_GLOBAL_MAXIMUM_COUNT + second
    )
    return {
        "histograms_evaluated": len(rows),
        "unique_maximum_histogram_n1_to_n5": list(
            optimum_histogram
        ),
        "maximum_total_hits_at_least_six_count": maximum,
        "second_best_total_hits_at_least_six_count": second,
        "non_optimum_histogram_empirical_profit_upper_count": (
            non_optimum_common_special_upper
        ),
    }


def _special_composition_pattern(
    composition: tuple[int, ...],
) -> tuple[int, ...]:
    return tuple(
        group
        for group, size in enumerate(composition)
        for _ in range(size)
    )


@lru_cache(maxsize=8)
def _macro_histograms(
    macro_a_tickets: int,
    macro_b_tickets: int,
) -> tuple[
    tuple[tuple[int, int], ...],
    tuple[tuple[int, ...], ...],
]:
    categories = tuple(
        (a_count, b_count)
        for a_count in range(macro_a_tickets + 1)
        for b_count in range(macro_b_tickets + 1)
        if a_count + b_count
    )
    rows: list[tuple[int, ...]] = []
    current: list[int] = []

    def visit(position: int, remaining_a: int, remaining_b: int) -> None:
        if position == len(categories):
            if remaining_a == 0 and remaining_b == 0:
                rows.append(tuple(current))
            return
        a_count, b_count = categories[position]
        maximum = TOTAL_TICKET_INCIDENCES
        if a_count:
            maximum = min(maximum, remaining_a // a_count)
        if b_count:
            maximum = min(maximum, remaining_b // b_count)
        for amount in range(maximum + 1):
            current.append(amount)
            visit(
                position + 1,
                remaining_a - a_count * amount,
                remaining_b - b_count * amount,
            )
            current.pop()

    visit(
        0,
        PICK_N * macro_a_tickets,
        PICK_N * macro_b_tickets,
    )
    return categories, tuple(rows)


def _aggregate_draw_distribution(
    categories: tuple[tuple[int, int], ...],
    histogram: tuple[int, ...],
) -> dict[tuple[int, int], int]:
    groups = [
        ((0, 0), POOL[SUPER] - sum(histogram)),
        *[
            (category, amount)
            for category, amount in zip(categories, histogram)
            if amount
        ],
    ]
    states: dict[tuple[int, int, int], int] = {(0, 0, 0): 1}
    for (a_count, b_count), group_size in groups:
        next_states: dict[tuple[int, int, int], int] = (
            defaultdict(int)
        )
        for (chosen, hits_a, hits_b), ways in states.items():
            for take in range(
                min(group_size, PICK_N - chosen) + 1
            ):
                next_states[
                    (
                        chosen + take,
                        hits_a + a_count * take,
                        hits_b + b_count * take,
                    )
                ] += ways * math.comb(group_size, take)
        states = dict(next_states)
    result = {
        (hits_a, hits_b): ways
        for (chosen, hits_a, hits_b), ways in states.items()
        if chosen == PICK_N
    }
    if sum(result.values()) != MAIN_DRAW_DENOMINATOR:
        raise RuntimeError("macro 命中分布不守恆")
    return result


def _low_hit_weight_lookup(
    composition: tuple[int, ...],
    macro_block_count: int,
    payout_table: dict[tuple[int, bool], int],
) -> dict[tuple[int, int], int]:
    pattern = _special_composition_pattern(composition)
    macro_cut = sum(composition[:macro_block_count])
    lookup: dict[tuple[int, int], int] = defaultdict(int)
    for hits in product(range(4), repeat=PORTFOLIO_TICKETS):
        miss_payout = sum(
            payout_table.get((hit, False), 0)
            for hit in hits
        )
        winning_special_groups = 0
        for group in range(len(composition)):
            payout = miss_payout + sum(
                payout_table.get((hit, True), 0)
                - payout_table.get((hit, False), 0)
                for ticket_index, hit in enumerate(hits)
                if pattern[ticket_index] == group
            )
            winning_special_groups += payout > PORTFOLIO_COST
        aggregate = (
            sum(hits[:macro_cut]),
            sum(hits[macro_cut:]),
        )
        lookup[aggregate] = max(
            lookup[aggregate], winning_special_groups
        )
    return dict(lookup)


@lru_cache(maxsize=16)
def empirical_proper_special_upper(
    composition: tuple[int, ...],
    empirical_floor_items: tuple[tuple[str, int], ...],
) -> dict:
    """以兩個 macro 群組放鬆逐票 degree，取得 proper special 全域上界。"""
    if composition not in PROPER_SPECIAL_COMPOSITIONS:
        raise ValueError("不是五票第二區的 proper block-size composition")
    floors = dict(empirical_floor_items)
    payout = _payout_table(
        "empirical_floor", floors, PORTFOLIO_COST
    )
    macro_block_count = MACRO_BLOCK_COUNTS[composition]
    macro_a = sum(composition[:macro_block_count])
    macro_b = PORTFOLIO_TICKETS - macro_a
    categories, histograms = _macro_histograms(macro_a, macro_b)
    expected_profiles = EXPECTED_RELAXED_PROFILE_COUNTS[
        composition
    ]
    if len(histograms) != expected_profiles:
        raise RuntimeError("proper special macro 鬆弛枚舉數量不符")
    low_weight = _low_hit_weight_lookup(
        composition, macro_block_count, payout
    )
    maximum = -1
    winner = None
    for histogram in histograms:
        distribution = _aggregate_draw_distribution(
            categories, histogram
        )
        score = sum(
            ways * low_weight.get(aggregate, 0)
            for aggregate, ways in distribution.items()
        )
        if score > maximum:
            maximum = score
            winner = histogram
    total_upper = (
        8 * MAIN_FOUR_GLOBAL_MAXIMUM_COUNT + maximum
    )
    expected = EXPECTED_EMPIRICAL_PROPER_UPPERS[composition]
    if total_upper != expected or total_upper >= 1_648_101:
        raise RuntimeError("proper special 的歷史壓力獲利上界不符")
    return {
        "special_block_sizes": list(composition),
        "macro_ticket_sizes": [macro_a, macro_b],
        "relaxed_histograms_evaluated": len(histograms),
        "low_hit_special_outcome_weight_upper_count": maximum,
        "at_least_four_main_eight_outcome_upper_count": (
            8 * MAIN_FOUR_GLOBAL_MAXIMUM_COUNT
        ),
        "total_empirical_strict_profit_upper_count": total_upper,
        "upper_probability": total_upper / FULL_DENOMINATOR,
        "relaxation_winner": [
            {
                "macro_a_members": category[0],
                "macro_b_members": category[1],
                "number_count": amount,
            }
            for category, amount in zip(categories, winner)
            if amount
        ],
        "strictly_below_optimum": True,
    }


@lru_cache(maxsize=8)
def _weak_compositions(
    total: int,
    parts: int,
) -> tuple[tuple[int, ...], ...]:
    if total < 0 or parts < 1:
        raise ValueError("weak composition 參數不符")
    if parts == 1:
        return ((total,),)
    return tuple(
        (head, *tail)
        for head in range(total + 1)
        for tail in _weak_compositions(total - head, parts - 1)
    )


@lru_cache(maxsize=256)
def _category_refinement_options(
    macro_a_tickets: int,
    macro_b_tickets: int,
    a_count: int,
    b_count: int,
    number_count: int,
) -> tuple[
    tuple[tuple[int, ...], tuple[tuple[int, int], ...]],
    ...,
]:
    """把 aggregate membership 數量完整分配到具體五票 mask。"""
    variants = tuple(
        sum(1 << index for index in (*left, *right))
        for left in combinations(
            range(macro_a_tickets), a_count
        )
        for right in combinations(
            range(
                macro_a_tickets,
                macro_a_tickets + macro_b_tickets,
            ),
            b_count,
        )
    )
    rows = []
    for allocation in _weak_compositions(
        number_count, len(variants)
    ):
        degrees = tuple(
            sum(
                amount * bool(mask & (1 << ticket_index))
                for mask, amount in zip(variants, allocation)
            )
            for ticket_index in range(PORTFOLIO_TICKETS)
        )
        assignment = tuple(
            (mask, amount)
            for mask, amount in zip(variants, allocation)
            if amount
        )
        rows.append((degrees, assignment))
    return tuple(rows)


def _refine_macro_histogram(
    categories: tuple[tuple[int, int], ...],
    histogram: tuple[int, ...],
    *,
    macro_a_tickets: int,
    macro_b_tickets: int,
) -> tuple[tuple[int, ...], ...]:
    """列出某 aggregate histogram 下所有每票 degree=6 的真實結構。"""
    groups = [
        _category_refinement_options(
            macro_a_tickets,
            macro_b_tickets,
            category[0],
            category[1],
            amount,
        )
        for category, amount in zip(categories, histogram)
        if amount
    ]
    groups.sort(key=len)
    counts = [0] * (1 << PORTFOLIO_TICKETS)
    rows: list[tuple[int, ...]] = []

    def visit(
        position: int,
        remaining: tuple[int, ...],
    ) -> None:
        if position == len(groups):
            if remaining == (0,) * PORTFOLIO_TICKETS:
                counts[0] = POOL[SUPER] - sum(counts[1:])
                if counts[0] < 0:
                    raise RuntimeError("macro refinement 聯集超出號碼池")
                rows.append(tuple(counts))
                counts[0] = 0
            return
        for degrees, assignment in groups[position]:
            if any(
                degrees[index] > remaining[index]
                for index in range(PORTFOLIO_TICKETS)
            ):
                continue
            for mask, amount in assignment:
                counts[mask] += amount
            visit(
                position + 1,
                tuple(
                    remaining[index] - degrees[index]
                    for index in range(PORTFOLIO_TICKETS)
                ),
            )
            for mask, amount in assignment:
                counts[mask] -= amount

    visit(0, (PICK_N,) * PORTFOLIO_TICKETS)
    return tuple(rows)


def _ticket_permutations_for_composition(
    composition: tuple[int, ...],
) -> tuple[tuple[int, ...], ...]:
    if composition == (3, 2):
        return tuple(
            (*left, *right)
            for left in permutations(range(3))
            for right in permutations(range(3, 5))
        )
    if composition == (2, 2, 1):
        within = tuple(
            (*left, *right, 4)
            for left in permutations(range(2))
            for right in permutations(range(2, 4))
        )
        return tuple(
            dict.fromkeys(
                (
                    *within,
                    *(
                        (*row[2:4], *row[:2], 4)
                        for row in within
                    ),
                )
            )
        )
    raise ValueError("此 composition 不使用 exact refinement")


def _transform_profile(
    profile: tuple[int, ...],
    permutation: tuple[int, ...],
) -> tuple[int, ...]:
    transformed = [0] * len(profile)
    for mask, amount in enumerate(profile):
        new_mask = sum(
            1 << permutation[index]
            for index in range(PORTFOLIO_TICKETS)
            if mask & (1 << index)
        )
        transformed[new_mask] = amount
    return tuple(transformed)


def _canonical_profile_for_composition(
    profile: tuple[int, ...],
    composition: tuple[int, ...],
) -> tuple[int, ...]:
    return min(
        _transform_profile(profile, permutation)
        for permutation in _ticket_permutations_for_composition(
            composition
        )
    )


def _macro_histogram_from_profile(
    profile: tuple[int, ...],
    *,
    macro_a_mask: int,
    categories: tuple[tuple[int, int], ...],
) -> tuple[int, ...]:
    indexes = {
        category: index
        for index, category in enumerate(categories)
    }
    macro_b_mask = ((1 << PORTFOLIO_TICKETS) - 1) ^ macro_a_mask
    histogram = [0] * len(categories)
    for mask, amount in enumerate(profile):
        if not mask or not amount:
            continue
        category = (
            bin(mask & macro_a_mask).count("1"),
            bin(mask & macro_b_mask).count("1"),
        )
        histogram[indexes[category]] += amount
    return tuple(histogram)


@lru_cache(maxsize=16)
def _nominal_macro_low_scores(
    composition: tuple[int, ...],
    macro_block_count: int,
) -> tuple[
    tuple[tuple[int, int], ...],
    tuple[tuple[tuple[int, ...], int], ...],
]:
    macro_a = sum(composition[:macro_block_count])
    macro_b = PORTFOLIO_TICKETS - macro_a
    categories, histograms = _macro_histograms(macro_a, macro_b)
    payout = _payout_table("nominal", {}, PORTFOLIO_COST)
    low_weight = _low_hit_weight_lookup(
        composition, macro_block_count, payout
    )
    rows = []
    for histogram in histograms:
        distribution = _aggregate_draw_distribution(
            categories, histogram
        )
        rows.append(
            (
                histogram,
                sum(
                    ways * low_weight.get(aggregate, 0)
                    for aggregate, ways in distribution.items()
                ),
            )
        )
    return categories, tuple(rows)


@lru_cache(maxsize=4)
def nominal_single_block_upper(block_size: int) -> dict:
    """上界單一第二區 block 命中時、所有票主號至多三中的獲利事件。"""
    if not 1 <= block_size < PORTFOLIO_TICKETS:
        raise ValueError("single block size 必須介於 1 與 4")
    macro_a = block_size
    macro_b = PORTFOLIO_TICKETS - block_size
    categories, histograms = _macro_histograms(macro_a, macro_b)
    payout = _payout_table("nominal", {}, PORTFOLIO_COST)
    lookup: dict[tuple[int, int], int] = defaultdict(int)
    for hits in product(range(4), repeat=PORTFOLIO_TICKETS):
        amount = sum(
            payout.get((hit, index < block_size), 0)
            for index, hit in enumerate(hits)
        )
        aggregate = (
            sum(hits[:block_size]),
            sum(hits[block_size:]),
        )
        lookup[aggregate] = max(
            lookup[aggregate],
            int(amount > PORTFOLIO_COST),
        )
    maximum = -1
    winner = None
    for histogram in histograms:
        distribution = _aggregate_draw_distribution(
            categories, histogram
        )
        score = sum(
            ways * lookup.get(aggregate, 0)
            for aggregate, ways in distribution.items()
        )
        if score > maximum:
            maximum = score
            winner = histogram
    if maximum != EXPECTED_NOMINAL_SINGLE_BLOCK_UPPERS[block_size]:
        raise RuntimeError("名目 single-block 獲利上界不符")
    return {
        "special_block_size": block_size,
        "macro_ticket_sizes": [macro_a, macro_b],
        "relaxed_histograms_evaluated": len(histograms),
        "low_hit_profit_upper_count": maximum,
        "relaxation_winner": [
            {
                "macro_a_members": category[0],
                "macro_b_members": category[1],
                "number_count": amount,
            }
            for category, amount in zip(categories, winner)
            if amount
        ],
    }


def _pair_main_four_intersection_count(overlap: int) -> int:
    if not 0 <= overlap <= PICK_N:
        raise ValueError("票對 overlap 必須介於 0 與 6")
    groups = (
        overlap,
        PICK_N - overlap,
        PICK_N - overlap,
        POOL[SUPER] - (2 * PICK_N - overlap),
    )
    count = 0
    for shared in range(min(groups[0], PICK_N) + 1):
        for left in range(min(groups[1], PICK_N - shared) + 1):
            for right in range(
                min(
                    groups[2],
                    PICK_N - shared - left,
                )
                + 1
            ):
                outside = PICK_N - shared - left - right
                if (
                    0 <= outside <= groups[3]
                    and shared + left >= 4
                    and shared + right >= 4
                ):
                    count += (
                        math.comb(groups[0], shared)
                        * math.comb(groups[1], left)
                        * math.comb(groups[2], right)
                        * math.comb(groups[3], outside)
                    )
    return count


def _hunter_main_four_upper(
    profile: tuple[int, ...],
) -> int:
    """五個高命中事件的 Hunter 最大生成樹 union upper bound。"""
    edges = []
    for left in range(PORTFOLIO_TICKETS):
        for right in range(left + 1, PORTFOLIO_TICKETS):
            pair_mask = (1 << left) | (1 << right)
            overlap = sum(
                amount
                for mask, amount in enumerate(profile)
                if mask & pair_mask == pair_mask
            )
            edges.append(
                (
                    PAIR_MAIN_FOUR_INTERSECTION_COUNTS[overlap],
                    left,
                    right,
                )
            )
    parents = list(range(PORTFOLIO_TICKETS))

    def root(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    tree_intersection = 0
    edges_used = 0
    for weight, left, right in sorted(edges, reverse=True):
        left_root = root(left)
        right_root = root(right)
        if left_root == right_root:
            continue
        parents[left_root] = right_root
        tree_intersection += weight
        edges_used += 1
        if edges_used == PORTFOLIO_TICKETS - 1:
            break
    return MAIN_FOUR_GLOBAL_MAXIMUM_COUNT - tree_intersection


@lru_cache(maxsize=8)
def nominal_proper_special_upper(
    composition: tuple[int, ...],
) -> dict:
    """閉合現行名目獎金下 proper-special 的全域上界。"""
    if composition not in PROPER_SPECIAL_COMPOSITIONS:
        raise ValueError("不是 proper special composition")
    high_outcome_upper = (
        SPECIAL_POOL[SUPER] * MAIN_FOUR_GLOBAL_MAXIMUM_COUNT
    )
    single_blocks = [
        nominal_single_block_upper(size)
        for size in composition
    ]
    independent_upper = high_outcome_upper + sum(
        row["low_hit_profit_upper_count"]
        for row in single_blocks
    )
    if composition not in {(3, 2), (2, 2, 1)}:
        if (
            independent_upper >= NOMINAL_OPTIMUM_COUNT
            or independent_upper
            != EXPECTED_NOMINAL_PROPER_GLOBAL_UPPERS[composition]
        ):
            raise RuntimeError("名目 single-block 上界未閉合")
        return {
            "special_block_sizes": list(composition),
            "method": "independent_single_block_relaxation",
            "single_block_upper_counts": [
                row["low_hit_profit_upper_count"]
                for row in single_blocks
            ],
            "at_least_four_main_eight_outcome_upper_count": (
                high_outcome_upper
            ),
            "global_nominal_strict_profit_upper_count": (
                independent_upper
            ),
            "strictly_below_optimum": True,
        }

    macro_block_count = MACRO_BLOCK_COUNTS[composition]
    macro_a = sum(composition[:macro_block_count])
    macro_b = PORTFOLIO_TICKETS - macro_a
    categories, macro_rows = _nominal_macro_low_scores(
        composition, macro_block_count
    )
    dangerous = [
        (histogram, low_score)
        for histogram, low_score in macro_rows
        if high_outcome_upper + low_score
        >= NOMINAL_OPTIMUM_COUNT
    ]
    non_dangerous_macro_upper = max(
        high_outcome_upper + low_score
        for _, low_score in macro_rows
        if high_outcome_upper + low_score
        < NOMINAL_OPTIMUM_COUNT
    )
    permutations_checked = _ticket_permutations_for_composition(
        composition
    )
    exact_candidates: set[tuple[int, ...]] = set()
    labeled_refinements = 0
    cross_macro_survivors = 0
    hunter_survivors = 0
    cross_macro_pruned_upper = 0
    hunter_pruned_upper = 0

    if composition == (3, 2):
        for histogram, _ in dangerous:
            refinements = _refine_macro_histogram(
                categories,
                histogram,
                macro_a_tickets=macro_a,
                macro_b_tickets=macro_b,
            )
            labeled_refinements += len(refinements)
            for profile in refinements:
                exact_candidates.add(
                    _canonical_profile_for_composition(
                        profile, composition
                    )
                )
        cross_macro_survivors = labeled_refinements
        hunter_survivors = labeled_refinements
    else:
        alternative_categories, alternative_rows = (
            _nominal_macro_low_scores(composition, 1)
        )
        alternative_scores = dict(alternative_rows)
        current_scores = dict(macro_rows)
        for histogram, _ in dangerous:
            refinements = _refine_macro_histogram(
                categories,
                histogram,
                macro_a_tickets=macro_a,
                macro_b_tickets=macro_b,
            )
            labeled_refinements += len(refinements)
            for profile in refinements:
                first_histogram = _macro_histogram_from_profile(
                    profile,
                    macro_a_mask=0b00011,
                    categories=alternative_categories,
                )
                second_histogram = _macro_histogram_from_profile(
                    profile,
                    macro_a_mask=0b01100,
                    categories=alternative_categories,
                )
                low_upper = min(
                    current_scores[histogram],
                    alternative_scores[first_histogram],
                    alternative_scores[second_histogram],
                )
                if high_outcome_upper + low_upper < NOMINAL_OPTIMUM_COUNT:
                    cross_macro_pruned_upper = max(
                        cross_macro_pruned_upper,
                        high_outcome_upper + low_upper,
                    )
                    continue
                cross_macro_survivors += 1
                total_upper = (
                    SPECIAL_POOL[SUPER]
                    * _hunter_main_four_upper(profile)
                    + low_upper
                )
                if total_upper < NOMINAL_OPTIMUM_COUNT:
                    hunter_pruned_upper = max(
                        hunter_pruned_upper, total_upper
                    )
                    continue
                hunter_survivors += 1
                exact_candidates.add(
                    _canonical_profile_for_composition(
                        profile, composition
                    )
                )

    nominal = _payout_table("nominal", {}, PORTFOLIO_COST)
    pattern = _special_composition_pattern(composition)
    maximum = -1
    winner = None
    for profile in sorted(exact_candidates):
        raw = _exact_super_payout_counts(
            POOL[SUPER],
            profile,
            pattern,
            nominal,
            nominal,
            PORTFOLIO_COST,
        )
        score = raw["nominal_strict_profit"]
        if score > maximum:
            maximum = score
            winner = profile
    if maximum < 0 or maximum >= NOMINAL_OPTIMUM_COUNT:
        raise RuntimeError("proper special 名目危險集未嚴格閉合")
    global_upper = max(
        non_dangerous_macro_upper,
        cross_macro_pruned_upper,
        hunter_pruned_upper,
        maximum,
    )
    if global_upper >= NOMINAL_OPTIMUM_COUNT:
        raise RuntimeError("proper special 名目全域上界未嚴格閉合")
    result = {
        "special_block_sizes": list(composition),
        "method": (
            "macro_danger_set_exact_refinement"
            if composition == (3, 2)
            else (
                "cross_macro_hunter_exact_refinement"
            )
        ),
        "macro_ticket_sizes": [macro_a, macro_b],
        "macro_histograms_evaluated": len(macro_rows),
        "dangerous_macro_histograms": len(dangerous),
        "non_dangerous_macro_upper_count": (
            non_dangerous_macro_upper
        ),
        "labeled_degree_valid_refinements": labeled_refinements,
        "cross_macro_survivors": cross_macro_survivors,
        "cross_macro_pruned_upper_count": (
            cross_macro_pruned_upper
        ),
        "hunter_survivors": hunter_survivors,
        "hunter_pruned_upper_count": hunter_pruned_upper,
        "ticket_permutations_removed": len(permutations_checked),
        "canonical_exact_candidates": len(exact_candidates),
        "maximum_exact_nominal_strict_profit_count": maximum,
        "maximum_exact_probability": maximum / FULL_DENOMINATOR,
        "maximum_exact_structure": [
            {"membership_mask": mask, "number_count": amount}
            for mask, amount in enumerate(winner)
            if mask and amount
        ],
        "global_nominal_strict_profit_upper_count": global_upper,
        "strictly_below_optimum": True,
    }
    expected = EXPECTED_NOMINAL_DANGER_CERTIFICATES[composition]
    if (
        global_upper
        != EXPECTED_NOMINAL_PROPER_GLOBAL_UPPERS[composition]
        or any(result[key] != value for key, value in expected.items())
    ):
        raise RuntimeError("proper special 名目危險集證書不符")
    return result


def _designated_nominal_boundary_count(
    histogram: tuple[int, ...],
    included_by_multiplicity: tuple[int, ...],
) -> int:
    """計數指定票 h=3、其餘四票總命中=2 的名目專屬邊界。"""
    groups = [((0, 0), POOL[SUPER] - sum(histogram))]
    for multiplicity, count in enumerate(histogram, 1):
        included = included_by_multiplicity[multiplicity - 1]
        if count - included:
            groups.append(((0, multiplicity), count - included))
        if included:
            groups.append(((1, multiplicity - 1), included))
    states: dict[tuple[int, int, int], int] = {(0, 0, 0): 1}
    for (own, other), group_size in groups:
        next_states: dict[tuple[int, int, int], int] = (
            defaultdict(int)
        )
        for (chosen, own_hits, other_hits), ways in states.items():
            for take in range(
                min(group_size, PICK_N - chosen) + 1
            ):
                next_states[
                    (
                        chosen + take,
                        own_hits + own * take,
                        other_hits + other * take,
                    )
                ] += ways * math.comb(group_size, take)
        states = dict(next_states)
    return sum(
        ways
        for (chosen, own_hits, other_hits), ways in states.items()
        if (
            chosen == PICK_N
            and own_hits == 3
            and other_hits == 2
        )
    )


@lru_cache(maxsize=1024)
def _maximum_designated_nominal_boundary(
    histogram: tuple[int, ...],
) -> int:
    maximum = 0
    current: list[int] = []

    def visit(position: int, remaining: int) -> None:
        nonlocal maximum
        if position == len(histogram):
            if remaining == 0:
                maximum = max(
                    maximum,
                    _designated_nominal_boundary_count(
                        histogram, tuple(current)
                    ),
                )
            return
        for amount in range(
            min(histogram[position], remaining) + 1
        ):
            current.append(amount)
            visit(position + 1, remaining - amount)
            current.pop()

    visit(0, PICK_N)
    return maximum


@lru_cache(maxsize=1)
def _nominal_common_special_certificate() -> dict:
    optimum_histogram = (0, 0, 10, 0, 0)
    rows = []
    for histogram in multiplicity_histograms():
        total_six = _at_least_total_hits_count(histogram, 6)
        boundary = _maximum_designated_nominal_boundary(histogram)
        upper = (
            8 * MAIN_FOUR_GLOBAL_MAXIMUM_COUNT
            + total_six
            + PORTFOLIO_TICKETS * boundary
        )
        rows.append((upper, histogram, total_six, boundary))
    non_optimum = max(
        row for row in rows if row[1] != optimum_histogram
    )
    optimum_boundary = next(
        boundary
        for _, histogram, _, boundary in rows
        if histogram == optimum_histogram
    )
    if (
        non_optimum
        != (
            1_642_111,
            (3, 0, 9, 0, 0),
            1_219_791,
            23_400,
        )
        or optimum_boundary != 0
    ):
        raise RuntimeError("名目獎金同第二區的邊界上界不符")
    return {
        "nominal_only_low_hit_vectors": [
            [3, 2, 0, 0, 0],
            [3, 1, 1, 0, 0],
        ],
        "non_optimum_histogram_maximum_upper_count": (
            non_optimum[0]
        ),
        "upper_winner_histogram_n1_to_n5": list(
            non_optimum[1]
        ),
        "upper_winner_total_hits_at_least_six_count": (
            non_optimum[2]
        ),
        "upper_winner_designated_ticket_boundary_count": (
            non_optimum[3]
        ),
        "optimum_histogram_boundary_count": optimum_boundary,
        "common_special_nominal_global_optimum_proved": True,
        "certificate_scope": "common_special_structures",
    }


def _metric_rows(raw: dict) -> dict:
    denominator = raw["denominator"]
    return {
        key: {
            "numerator": raw[key],
            "denominator": denominator,
            "probability": raw[key] / denominator,
        }
        for key in (
            "any_prize",
            "nominal_break_even",
            "nominal_strict_profit",
            "empirical_floor_break_even",
            "empirical_floor_strict_profit",
            "at_least_three_main",
            "at_least_four_main",
        )
    }


@lru_cache(maxsize=4)
def _proof_payload_cached(base_string: str) -> dict:
    base = Path(base_string)
    history = _history_snapshot(base)
    floors = history["games"][SUPER][
        "minimum_observed_per_prize_ntd"
    ]
    floor_items = tuple(sorted(floors.items()))
    nominal = _payout_table("nominal", floors, PORTFOLIO_COST)
    empirical = _payout_table(
        "empirical_floor", floors, PORTFOLIO_COST
    )
    if (
        empirical[(3, False)] != 100
        or empirical[(3, True)] != 277
        or min(
            empirical[(hit, special)]
            for hit in range(4, 7)
            for special in (False, True)
        )
        <= PORTFOLIO_COST
    ):
        raise RuntimeError("歷史壓力獎金不再符合獲利事件化簡前提")
    optimum_raw = _exact_super_payout_counts(
        POOL[SUPER],
        optimum_membership_counts(),
        OPTIMUM_SPECIAL_PATTERN,
        nominal,
        empirical,
        PORTFOLIO_COST,
    )
    optimum_count = optimum_raw[
        "empirical_floor_strict_profit"
    ]
    if (
        optimum_count != NOMINAL_OPTIMUM_COUNT
        or optimum_raw["nominal_strict_profit"] != optimum_count
    ):
        raise RuntimeError("無守門獲利最優候選精確計數不符")
    multiplicity = _multiplicity_certificate()
    triple = _three_uniform_certificate()
    proper = [
        empirical_proper_special_upper(
            composition, floor_items
        )
        for composition in PROPER_SPECIAL_COMPOSITIONS
    ]
    maximum_proper_upper = max(
        row["total_empirical_strict_profit_upper_count"]
        for row in proper
    )
    nominal_common = _nominal_common_special_certificate()
    nominal_proper = [
        nominal_proper_special_upper(composition)
        for composition in PROPER_SPECIAL_COMPOSITIONS
    ]
    maximum_nominal_proper_upper = max(
        row["global_nominal_strict_profit_upper_count"]
        for row in nominal_proper
    )
    if (
        multiplicity[
            "non_optimum_histogram_empirical_profit_upper_count"
        ]
        >= optimum_count
        or maximum_proper_upper >= optimum_count
        or triple["maximum_at_least_four_main_count"]
        * 7
        + multiplicity[
            "maximum_total_hits_at_least_six_count"
        ]
        != optimum_count
        or nominal_common[
            "non_optimum_histogram_maximum_upper_count"
        ]
        >= optimum_count
        or maximum_nominal_proper_upper >= optimum_count
    ):
        raise RuntimeError("無守門獲利全域上界未嚴格閉合")

    return {
        "schema_version": "1",
        "experiment_id": EXPERIMENT_ID,
        "rules_as_of": "2026-07-19",
        "official_prize_rules": OFFICIAL_RULE_URLS,
        "official_history": history,
        "source_pareto_certificate": {
            "experiment_id": PARETO_EXPERIMENT_ID,
            "certificate_hash": SOURCE_PARETO_CERTIFICATE_HASH,
        },
        "question": (
            "移除 pairwise overlap <= 1 守門後，五張威力彩票在凍結"
            "歷史最低實領壓力與現行名目獎金兩種口徑下的嚴格獲利"
            "機率全域上限是多少？"
        ),
        "event_reduction": {
            "empirical_common_special": (
                "五注第二區全同時，第二區未中且任一票至少四主號會獲利；"
                "第二區命中時，任一票至少四主號，或五票 ticket-hit"
                " incidence 合計至少六，也會獲利。"
            ),
            "weighted_count_formula": (
                "empirical favorable count = "
                "7 * count(max_main_hits>=4) + "
                "count(max_main_hits>=4 or total_hits>=6)"
            ),
            "nominal_boundary": (
                "名目面額只多出總命中五次且排序為 [3,2,0,0,0] 或"
                " [3,1,1,0,0] 的第二區命中邊界。"
            ),
            "nominal_proper_special": (
                "proper special 先以 single-block 與兩群 macro 上界"
                "排除安全域；3+2 與 2+2+1 的危險域再完整展開每票"
                "degree=6 結構，配合交叉 macro、Hunter union bound"
                "與逐候選整數 DP 閉合。"
            ),
        },
        "proof": {
            "universal_main_four_upper_count": (
                MAIN_FOUR_GLOBAL_MAXIMUM_COUNT
            ),
            "multiplicity_histograms": multiplicity,
            "three_uniform_profiles": triple,
            "proper_special_partition_relaxations": proper,
            "maximum_proper_special_empirical_upper_count": (
                maximum_proper_upper
            ),
            "nominal_common_special": nominal_common,
            "nominal_proper_special_global_bounds": nominal_proper,
            "maximum_proper_special_nominal_upper_count": (
                maximum_nominal_proper_upper
            ),
            "global_empirical_optimum_proved": True,
            "global_empirical_optimum_unique_up_to_relabeling": True,
            "global_nominal_optimum_proved": True,
            "global_nominal_optimum_unique_up_to_relabeling": True,
            "calculation": (
                "全程整數組合計數。主號 multiplicity、三均勻 profile、"
                "proper special macro 鬆弛、single-block、degree "
                "refinement、Hunter 二階上界與名目危險集均有限枚舉；"
                "不使用 Monte Carlo。"
            ),
        },
        "games": {
            SUPER: {
                "game_name": GAME_NAMES[SUPER],
                "five_ticket_cost_ntd": PORTFOLIO_COST,
                "optimum_structure": {
                    "description": (
                        "十個三票子集各配置一個不同主號；每個主號恰好"
                        "出現在三張票、每張票包含六個主號；五注第二區相同。"
                    ),
                    "membership_masks": list(TRIPLE_MASKS),
                    "membership_counts": [
                        1 for _ in TRIPLE_MASKS
                    ],
                    "main_number_union_size": len(TRIPLE_MASKS),
                    "pairwise_main_overlap": 3,
                    "special_partition": list(
                        OPTIMUM_SPECIAL_PATTERN
                    ),
                    "example_tickets": optimum_tickets(),
                },
                "metrics": _metric_rows(optimum_raw),
                "empirical_floor_strict_profit_global_maximum": {
                    "numerator": optimum_count,
                    "denominator": FULL_DENOMINATOR,
                    "probability": (
                        optimum_count / FULL_DENOMINATOR
                    ),
                },
                "nominal_strict_profit_global_maximum": {
                    "numerator": optimum_raw[
                        "nominal_strict_profit"
                    ],
                    "denominator": FULL_DENOMINATOR,
                    "probability": (
                        optimum_raw[
                            "nominal_strict_profit"
                        ]
                        / FULL_DENOMINATOR
                    ),
                    "scope": (
                        "五注第二區全同與六類 proper special 均已完成"
                        "有限整數上界或危險集完整 refinement，證明為"
                        "現行名目獎金全域最優。"
                    ),
                },
            },
            LOTTO649: {
                "game_name": GAME_NAMES[LOTTO649],
                "conclusion": (
                    "大樂透任一獎即高於五注成本；本補充不改變完全分散"
                    "五注的嚴格獲利全域最優結論。"
                ),
            },
        },
        "comparison": {
            "coverage_empirical_profit_probability": (
                305_320 / FULL_DENOMINATOR
            ),
            "high_tier_guarded_profit_probability": (
                1_203_926 / FULL_DENOMINATOR
            ),
            "unconstrained_profit_probability": (
                optimum_count / FULL_DENOMINATOR
            ),
            "unconstrained_vs_coverage_ratio": (
                optimum_count / 305_320
            ),
            "unconstrained_vs_guarded_ratio": (
                optimum_count / 1_203_926
            ),
            "tradeoffs": {
                "any_prize_probability": (
                    optimum_raw["any_prize"] / FULL_DENOMINATOR
                ),
                "at_least_three_main_probability": (
                    optimum_raw["at_least_three_main"]
                    / FULL_DENOMINATOR
                ),
                "at_least_four_main_probability": (
                    optimum_raw["at_least_four_main"]
                    / FULL_DENOMINATOR
                ),
            },
        },
        "decision": {
            "automatic_switch": False,
            "reason": (
                "這是嚴格獲利效用的全域最優，但會顯著降低任一獎、"
                "三主號與四主號機率；未取得效用目標選擇前不替換"
                " coverage。"
            ),
            "current_forward_registrations_unchanged": True,
            "eligible_as_future_profit_shadow": True,
        },
        "limitations": [
            "全域結論針對截至 2026-07-17 的歷史最低實領壓力獎金；該最低值不是未來保證。",
            "現行名目獎金的全域結論依 2026-07-19 官方獎級面額；規則變更時必須開新證書重算。",
            "不估算浮動獎金期望值、多人均分、稅負或風險偏好。",
            "提高的是五注合計事件率，不讓任何號碼標籤或單注頭獎變得較可能。",
            "純模擬研究，不構成購買或下注建議。",
        ],
    }


def proof_payload(base: Path) -> dict:
    return deepcopy(
        _proof_payload_cached(str(Path(base).resolve()))
    )


def build_unconstrained_profit_certificate(base: Path) -> dict:
    base = Path(base)
    records_before = tree_sha256(base / "records")
    payload = proof_payload(base)
    records_after = tree_sha256(base / "records")
    if records_before != records_after:
        raise RuntimeError("無守門獲利證明不應改動正式 records")
    return {
        **payload,
        "certificate_hash": canonical_hash(payload),
        "records_integrity": {
            "before_sha256": records_before,
            "after_sha256": records_after,
            "unchanged": records_before == records_after,
        },
    }


def verify_unconstrained_profit_certificate(
    result: dict,
    base: Path,
) -> None:
    payload = proof_payload(base)
    expected = {
        **payload,
        "certificate_hash": canonical_hash(payload),
    }
    actual = {key: result.get(key) for key in expected}
    if actual != expected:
        raise RuntimeError("無守門獲利證明內容或 certificate hash 不符")
    integrity = result.get("records_integrity", {})
    if (
        integrity.get("unchanged") is not True
        or integrity.get("before_sha256")
        != integrity.get("after_sha256")
    ):
        raise RuntimeError("無守門獲利證明 records 完整性不符")


def write_results(result: dict, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return path
