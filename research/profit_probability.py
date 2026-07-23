"""五注成本後的精確獲利機率與高獎守門 Pareto 搜尋。

威力彩五注成本為 500 元，因此「至少中一個獎」不等於「合計獎金超過
成本」。本模組完整枚舉所有仍保留「至少四個主號」全域最大機率的五注
主號結構，以及所有第二區相等模式，再用整數組合計數精算回本與獲利率。

大樂透五注成本為 250 元；在本研究凍結的規則與官方 API 歷史最低實領
快照中，每一個獎級的單注獎金都高於 250 元，因此其獲利事件等同任一獎
事件，沿用已證明全域最優的完全分散結構。
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from functools import lru_cache
from itertools import permutations
import json
import math
import os
from pathlib import Path
from typing import Iterator

from engine.agent_loop import SELECTED_TICKETS, canonical_hash
from engine.fetch import load_all_draws
from engine.games import (
    GAME_NAMES,
    LOTTO649,
    PICK_N,
    POOL,
    SPECIAL_POOL,
    SUPER,
    TICKET_PRICE,
    TIERS,
    floor_table_from_history,
)
from research.gates import tree_sha256
from research.prize_tier_profile import exact_prize_profile
from research.structural_optimum import (
    OFFICIAL_RULE_URLS,
    disjoint_reference_tickets,
    structural_proof_reference,
)


EXPERIMENT_ID = "five-ticket-profit-pareto-proof-v1"
HISTORY_CUTOFF = "2026-07-17"
PORTFOLIO_TICKETS = SELECTED_TICKETS
EXPECTED_LABELED_STRUCTURES = 2625
EXPECTED_CANONICAL_STRUCTURES = 72
EXPECTED_SPECIAL_PARTITIONS = 52
EXPECTED_SEARCH_CANDIDATES = (
    EXPECTED_CANONICAL_STRUCTURES * EXPECTED_SPECIAL_PARTITIONS
)
PAIR_INDEXES = tuple(
    (left, right)
    for left in range(PORTFOLIO_TICKETS)
    for right in range(left + 1, PORTFOLIO_TICKETS)
)
SHARED_MASKS = tuple(
    mask
    for mask in range(1, 1 << PORTFOLIO_TICKETS)
    if bin(mask).count("1") >= 2
)
TICKET_PERMUTATIONS = tuple(permutations(range(PORTFOLIO_TICKETS)))


def _pair_bits(mask: int) -> int:
    bits = 0
    for index, (left, right) in enumerate(PAIR_INDEXES):
        if mask & (1 << left) and mask & (1 << right):
            bits |= 1 << index
    return bits


PAIR_BITS = {mask: _pair_bits(mask) for mask in SHARED_MASKS}


def _labeled_linear_shared_structures(
) -> Iterator[tuple[int, ...]]:
    """列出所有五票間 pairwise overlap 不超過 1 的共享群組。

    每個大小至少二的 membership mask 最多出現一次；不同 mask 也不能
    重複使用同一票券對。這與 pairwise overlap <= 1 完全等價。每票尚缺
    的號碼最後由 singleton 群組補滿六個。
    """
    selected: list[int] = []

    def visit(
        position: int,
        used_pairs: int,
    ) -> Iterator[tuple[int, ...]]:
        if position == len(SHARED_MASKS):
            yield tuple(selected)
            return
        yield from visit(position + 1, used_pairs)
        mask = SHARED_MASKS[position]
        pair_bits = PAIR_BITS[mask]
        if used_pairs & pair_bits:
            return
        selected.append(mask)
        yield from visit(position + 1, used_pairs | pair_bits)
        selected.pop()

    yield from visit(0, 0)


def _permuted_mask(
    mask: int,
    permutation: tuple[int, ...],
) -> int:
    result = 0
    for old_index, new_index in enumerate(permutation):
        if mask & (1 << old_index):
            result |= 1 << new_index
    return result


def _canonical_shared_structure(
    structure: tuple[int, ...],
) -> tuple[int, ...]:
    return min(
        tuple(
            sorted(
                _permuted_mask(mask, permutation)
                for mask in structure
            )
        )
        for permutation in TICKET_PERMUTATIONS
    )


@lru_cache(maxsize=1)
def linear_shared_structures() -> tuple[tuple[int, ...], ...]:
    """回傳 72 個票券置換下不等價的完整結構代表。"""
    labeled = tuple(_labeled_linear_shared_structures())
    canonical = tuple(
        sorted(
            {
                _canonical_shared_structure(structure)
                for structure in labeled
            }
        )
    )
    if (
        len(labeled) != EXPECTED_LABELED_STRUCTURES
        or len(canonical) != EXPECTED_CANONICAL_STRUCTURES
    ):
        raise RuntimeError("線性五票結構的完整枚舉數量不符")
    return canonical


@lru_cache(maxsize=1)
def special_partitions() -> tuple[tuple[int, ...], ...]:
    """列出五票第二區相等關係的全部 52 個集合分割。

    restricted-growth string 的數字只是等價類標籤；第二區有八個值且票券
    只有五張，所以所有集合分割都可實現。
    """
    rows: list[tuple[int, ...]] = []
    current: list[int] = []

    def visit() -> None:
        if len(current) == PORTFOLIO_TICKETS:
            rows.append(tuple(current))
            return
        maximum = max(current) + 1 if current else 0
        for label in range(maximum + 1):
            current.append(label)
            visit()
            current.pop()

    visit()
    result = tuple(rows)
    if len(result) != EXPECTED_SPECIAL_PARTITIONS:
        raise RuntimeError("第二區集合分割的完整枚舉數量不符")
    return result


def _membership_counts_from_structure(
    pool: int,
    structure: tuple[int, ...],
) -> tuple[int, ...]:
    counts = [0] * (1 << PORTFOLIO_TICKETS)
    for mask in structure:
        if (
            mask not in PAIR_BITS
            or counts[mask]
            or any(
                counts[other]
                and PAIR_BITS[mask] & PAIR_BITS.get(other, 0)
                for other in range(len(counts))
            )
        ):
            raise ValueError("structure 不是合法的 pairwise overlap <= 1 結構")
        counts[mask] = 1
    for ticket_index in range(PORTFOLIO_TICKETS):
        incident = sum(
            amount
            for mask, amount in enumerate(counts)
            if mask & (1 << ticket_index)
        )
        if incident > PICK_N:
            raise ValueError("共享群組使單票超過六個主號")
        counts[1 << ticket_index] = PICK_N - incident
    counts[0] = pool - sum(counts)
    if counts[0] < 0:
        raise ValueError("票券聯集超出號碼池")
    return tuple(counts)


def tickets_from_design(
    structure: tuple[int, ...],
    special_pattern: tuple[int, ...],
) -> list[dict]:
    """把結構代表轉成可直接交給既有精確獎級引擎的五張票。"""
    if (
        len(special_pattern) != PORTFOLIO_TICKETS
        or special_pattern not in special_partitions()
    ):
        raise ValueError("special_pattern 必須是完整枚舉中的第二區集合分割")
    numbers = [[] for _ in range(PORTFOLIO_TICKETS)]
    value = 1
    for mask in structure:
        for ticket_index in range(PORTFOLIO_TICKETS):
            if mask & (1 << ticket_index):
                numbers[ticket_index].append(value)
        value += 1
    for ticket_numbers in numbers:
        while len(ticket_numbers) < PICK_N:
            ticket_numbers.append(value)
            value += 1
    return [
        {
            "slot": ticket_index + 1,
            "source_agent": "profit_pareto_proof",
            "source_proposal": f"profit:{ticket_index + 1}",
            "numbers": ticket_numbers,
            "special": special_pattern[ticket_index] + 1,
        }
        for ticket_index, ticket_numbers in enumerate(numbers)
    ]


@lru_cache(maxsize=512)
def _exact_main_hit_distribution(
    pool: int,
    membership_counts: tuple[int, ...],
) -> tuple[tuple[tuple[int, ...], int], ...]:
    """精確計數六個主號造成的逐票命中向量。

    這是獲利搜尋專用的較小 DP；大樂透特別號所需的 membership 抽取量
    不在本研究中使用，因此不攜帶額外狀態。
    """
    ticket_count = len(membership_counts).bit_length() - 1
    if (
        len(membership_counts) != 1 << ticket_count
        or not 1 <= ticket_count <= PORTFOLIO_TICKETS
        or sum(membership_counts) != pool
        or any(amount < 0 for amount in membership_counts)
    ):
        raise ValueError("membership_counts 不是合法的號碼池分割")
    states: dict[tuple[int, tuple[int, ...]], int] = {
        (0, (0,) * ticket_count): 1
    }
    for mask, group_size in enumerate(membership_counts):
        if group_size == 0:
            continue
        next_states: dict[tuple[int, tuple[int, ...]], int] = (
            defaultdict(int)
        )
        for (chosen, hits), ways in states.items():
            maximum = min(group_size, PICK_N - chosen)
            for take in range(maximum + 1):
                next_hits = tuple(
                    hit
                    + (
                        take
                        if mask & (1 << ticket_index)
                        else 0
                    )
                    for ticket_index, hit in enumerate(hits)
                )
                next_states[(chosen + take, next_hits)] += (
                    ways * math.comb(group_size, take)
                )
        states = dict(next_states)
    result = tuple(
        sorted(
            (hits, ways)
            for (chosen, hits), ways in states.items()
            if chosen == PICK_N
        )
    )
    if sum(ways for _, ways in result) != math.comb(pool, PICK_N):
        raise RuntimeError("主號命中向量 DP 不守恆")
    return result


def _payout_table(
    mode: str,
    empirical_floors: dict[str, int],
    cost: int,
) -> dict[tuple[int, bool], int]:
    table = {}
    for tier in TIERS[SUPER]:
        if mode == "nominal":
            amount = (
                tier.fixed_prize
                if tier.fixed_prize is not None
                else cost + 1
            )
        elif mode == "empirical_floor":
            amount = empirical_floors.get(tier.api_key, 0)
            if amount <= 0:
                raise RuntimeError(
                    f"缺少 {tier.api_key} 的歷史最低實領額"
                )
        else:
            raise ValueError(f"未知獎金口徑：{mode}")
        table[(tier.match_main, tier.match_special)] = amount
    return table


def _exact_super_payout_counts(
    pool: int,
    membership_counts: tuple[int, ...],
    special_pattern: tuple[int, ...],
    nominal_table: dict[tuple[int, bool], int],
    empirical_floor_table: dict[tuple[int, bool], int],
    cost: int,
    event_cache: dict | None = None,
) -> dict[str, int]:
    """精確計數威力彩任一獎、回本、嚴格獲利與主號門檻事件。"""
    ticket_count = len(membership_counts).bit_length() - 1
    if (
        len(special_pattern) != ticket_count
        or min(special_pattern, default=0) != 0
        or max(special_pattern, default=0) >= SPECIAL_POOL[SUPER]
    ):
        raise ValueError("第二區相等模式與票券數不符")
    counts = {
        "any_prize": 0,
        "nominal_break_even": 0,
        "nominal_strict_profit": 0,
        "empirical_floor_break_even": 0,
        "empirical_floor_strict_profit": 0,
        "at_least_three_main": 0,
        "at_least_four_main": 0,
    }
    distribution = _exact_main_hit_distribution(
        pool, membership_counts
    )
    for hits, ways in distribution:
        maximum_hits = max(hits)
        if maximum_hits >= 3:
            counts["at_least_three_main"] += (
                ways * SPECIAL_POOL[SUPER]
            )
        if maximum_hits >= 4:
            counts["at_least_four_main"] += (
                ways * SPECIAL_POOL[SUPER]
            )
        cache_key = (hits, special_pattern)
        special_counts = (
            event_cache.get(cache_key)
            if event_cache is not None
            else None
        )
        if special_counts is None:
            special_counts = _super_special_event_counts(
                hits,
                special_pattern,
                nominal_table,
                empirical_floor_table,
                cost,
            )
            if event_cache is not None:
                event_cache[cache_key] = special_counts
        for key, special_count in special_counts.items():
            counts[key] += ways * special_count
    denominator = math.comb(pool, PICK_N) * SPECIAL_POOL[SUPER]
    if any(
        numerator < 0 or numerator > denominator
        for numerator in counts.values()
    ):
        raise RuntimeError("獲利事件計數超出樣本空間")
    return {"denominator": denominator, **counts}


def _super_special_event_counts(
    hits: tuple[int, ...],
    special_pattern: tuple[int, ...],
    nominal_table: dict[tuple[int, bool], int],
    empirical_floor_table: dict[tuple[int, bool], int],
    cost: int,
) -> dict[str, int]:
    """固定主號命中向量時，彙總八個第二區結果的事件個數。"""
    ticket_count = len(hits)
    special_groups = max(special_pattern) + 1
    tier_keys = {
        (tier.match_main, tier.match_special)
        for tier in TIERS[SUPER]
    }
    counts = {
        "any_prize": 0,
        "nominal_break_even": 0,
        "nominal_strict_profit": 0,
        "empirical_floor_break_even": 0,
        "empirical_floor_strict_profit": 0,
    }
    special_cases = [
        (
            tuple(
                group == outcome for group in special_pattern
            ),
            1,
        )
        for outcome in range(special_groups)
    ]
    if special_groups < SPECIAL_POOL[SUPER]:
        special_cases.append(
            (
                (False,) * ticket_count,
                SPECIAL_POOL[SUPER] - special_groups,
            )
        )
    for special_hits, multiplicity in special_cases:
        results = tuple(zip(hits, special_hits))
        counts["any_prize"] += multiplicity * any(
            result in tier_keys for result in results
        )
        nominal = sum(
            nominal_table.get(result, 0) for result in results
        )
        empirical = sum(
            empirical_floor_table.get(result, 0)
            for result in results
        )
        counts["nominal_break_even"] += (
            multiplicity * (nominal >= cost)
        )
        counts["nominal_strict_profit"] += (
            multiplicity * (nominal > cost)
        )
        counts["empirical_floor_break_even"] += (
            multiplicity * (empirical >= cost)
        )
        counts["empirical_floor_strict_profit"] += (
            multiplicity * (empirical > cost)
        )
    if any(
        count < 0 or count > SPECIAL_POOL[SUPER]
        for count in counts.values()
    ):
        raise RuntimeError("第二區事件計數不守恆")
    return counts


def _count_row(numerator: int, denominator: int) -> dict:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "probability": numerator / denominator,
    }


def _structure_description(
    structure: tuple[int, ...],
) -> dict:
    memberships = [
        [
            ticket_index + 1
            for ticket_index in range(PORTFOLIO_TICKETS)
            if mask & (1 << ticket_index)
        ]
        for mask in structure
    ]
    pairwise = []
    for left, right in PAIR_INDEXES:
        overlap = sum(
            left + 1 in group and right + 1 in group
            for group in memberships
        )
        pairwise.append(
            {
                "left_slot": left + 1,
                "right_slot": right + 1,
                "main_overlap": overlap,
            }
        )
    singleton_counts = [
        PICK_N
        - sum(ticket_index + 1 in group for group in memberships)
        for ticket_index in range(PORTFOLIO_TICKETS)
    ]
    return {
        "canonical_shared_masks": list(structure),
        "shared_number_memberships": memberships,
        "ticket_singleton_counts": singleton_counts,
        "pairwise_overlaps": pairwise,
        "main_number_union_size": (
            len(structure) + sum(singleton_counts)
        ),
    }


def _candidate_row(
    structure: tuple[int, ...],
    special_pattern: tuple[int, ...],
    empirical_floors: dict[str, int],
    *,
    nominal_table: dict[tuple[int, bool], int] | None = None,
    empirical_floor_table: (
        dict[tuple[int, bool], int] | None
    ) = None,
    event_cache: dict | None = None,
) -> dict:
    cost = PORTFOLIO_TICKETS * TICKET_PRICE[SUPER]
    nominal_table = nominal_table or _payout_table(
        "nominal", empirical_floors, cost
    )
    empirical_floor_table = empirical_floor_table or _payout_table(
        "empirical_floor", empirical_floors, cost
    )
    raw = _exact_super_payout_counts(
        POOL[SUPER],
        _membership_counts_from_structure(
            POOL[SUPER], structure
        ),
        special_pattern,
        nominal_table,
        empirical_floor_table,
        cost,
        event_cache,
    )
    denominator = raw["denominator"]
    return {
        **_structure_description(structure),
        "special_partition": list(special_pattern),
        "distinct_special_values": len(set(special_pattern)),
        "example_tickets": tickets_from_design(
            structure, special_pattern
        ),
        "metrics": {
            key: _count_row(raw[key], denominator)
            for key in (
                "any_prize",
                "nominal_break_even",
                "nominal_strict_profit",
                "empirical_floor_break_even",
                "empirical_floor_strict_profit",
                "at_least_three_main",
                "at_least_four_main",
            )
        },
    }


def _pareto_frontier(rows: list[dict]) -> list[dict]:
    """取得歷史最低實領嚴格獲利率與任一獎率的二目標前緣。"""
    ordered = sorted(
        rows,
        key=lambda row: (
            -row["metrics"][
                "empirical_floor_strict_profit"
            ]["numerator"],
            -row["metrics"]["any_prize"]["numerator"],
            row["canonical_shared_masks"],
            row["special_partition"],
        ),
    )
    frontier = []
    maximum_any = -1
    for row in ordered:
        any_count = row["metrics"]["any_prize"]["numerator"]
        if any_count <= maximum_any:
            continue
        frontier.append(row)
        maximum_any = any_count
    return frontier


def _history_snapshot(base: Path) -> dict:
    games = {}
    for game in (SUPER, LOTTO649):
        draws = [
            draw
            for draw in load_all_draws(game, base / "data")
            if draw.date <= HISTORY_CUTOFF
        ]
        if not draws:
            raise RuntimeError(f"{game} 在凍結截止日前沒有官方 API 資料")
        floors = floor_table_from_history(draws)
        missing = [
            tier.api_key
            for tier in TIERS[game]
            if floors.get(tier.api_key, 0) <= 0
        ]
        if missing:
            raise RuntimeError(
                f"{game} 缺少歷史最低實領額：" + ", ".join(missing)
            )
        normalized = [
            {
                "period": draw.period,
                "date": draw.date,
                "prizes": {
                    tier.api_key: draw.prizes.get(tier.api_key, {})
                    for tier in TIERS[game]
                },
            }
            for draw in draws
        ]
        games[game] = {
            "draw_count": len(draws),
            "first_date": draws[0].date,
            "last_date": draws[-1].date,
            "normalized_prize_snapshot_hash": canonical_hash(
                {"rows": normalized}
            ),
            "minimum_observed_per_prize_ntd": {
                tier.api_key: floors[tier.api_key]
                for tier in TIERS[game]
            },
        }
    return {
        "cutoff_inclusive": HISTORY_CUTOFF,
        "source": (
            "台灣彩券官方 API 月快取；只納入截止日以前、實際有人中獎且"
            " per_prize > 0 的觀測值"
        ),
        "download_page": (
            "https://www.taiwanlottery.com/lotto/history/"
            "result_download/"
        ),
        "games": games,
    }


def _face_prize_snapshot() -> dict:
    return {
        game: {
            "ticket_price_ntd": TICKET_PRICE[game],
            "five_ticket_cost_ntd": (
                PORTFOLIO_TICKETS * TICKET_PRICE[game]
            ),
            "tiers": [
                {
                    "rank": tier.rank,
                    "label": tier.label,
                    "match_main": tier.match_main,
                    "match_special": tier.match_special,
                    "fixed_prize_ntd": tier.fixed_prize,
                    "api_key": tier.api_key,
                }
                for tier in TIERS[game]
            ],
        }
        for game in (SUPER, LOTTO649)
    }


@lru_cache(maxsize=4)
def _study_payload_cached(base_string: str) -> dict:
    base = Path(base_string)
    history = _history_snapshot(base)
    super_floors = history["games"][SUPER][
        "minimum_observed_per_prize_ntd"
    ]
    super_cost = PORTFOLIO_TICKETS * TICKET_PRICE[SUPER]
    nominal_table = _payout_table(
        "nominal", super_floors, super_cost
    )
    empirical_floor_table = _payout_table(
        "empirical_floor", super_floors, super_cost
    )
    event_cache: dict = {}
    rows = [
        _candidate_row(
            structure,
            special,
            super_floors,
            nominal_table=nominal_table,
            empirical_floor_table=empirical_floor_table,
            event_cache=event_cache,
        )
        for structure in linear_shared_structures()
        for special in special_partitions()
    ]
    if len(rows) != EXPECTED_SEARCH_CANDIDATES:
        raise RuntimeError("威力彩獲利候選搜尋數量不符")

    robust_key = lambda row: row["metrics"][
        "empirical_floor_strict_profit"
    ]["numerator"]
    nominal_key = lambda row: row["metrics"][
        "nominal_strict_profit"
    ]["numerator"]
    any_key = lambda row: row["metrics"]["any_prize"]["numerator"]
    robust_maximum = max(map(robust_key, rows))
    nominal_maximum = max(map(nominal_key, rows))
    any_maximum = max(map(any_key, rows))
    robust_winners = [row for row in rows if robust_key(row) == robust_maximum]
    nominal_winners = [
        row for row in rows if nominal_key(row) == nominal_maximum
    ]
    any_winners = [row for row in rows if any_key(row) == any_maximum]
    optimum = min(
        robust_winners,
        key=lambda row: (
            row["canonical_shared_masks"],
            row["special_partition"],
        ),
    )
    if optimum not in nominal_winners:
        raise RuntimeError("名目與歷史最低實領獲利最優結構不一致")

    disjoint = next(
        row
        for row in rows
        if row["canonical_shared_masks"] == []
        and row["special_partition"] == [0, 1, 2, 3, 4]
    )
    expected_profit_structure = tuple(
        mask
        for mask in SHARED_MASKS
        if bin(mask).count("1") == 2
    )
    if (
        tuple(optimum["canonical_shared_masks"])
        != expected_profit_structure
        or optimum["special_partition"] != [0, 0, 0, 0, 0]
        or len(robust_winners) != 1
        or len(nominal_winners) != 1
        or disjoint not in any_winners
    ):
        raise RuntimeError("威力彩獲利／任一獎最優結構與完整搜尋不符")

    lotto_floors = history["games"][LOTTO649][
        "minimum_observed_per_prize_ntd"
    ]
    lotto_cost = PORTFOLIO_TICKETS * TICKET_PRICE[LOTTO649]
    minimum_lotto_face = min(
        tier.fixed_prize
        for tier in TIERS[LOTTO649]
        if tier.fixed_prize is not None
    )
    minimum_lotto_floor = min(lotto_floors.values())
    if (
        minimum_lotto_face <= lotto_cost
        or minimum_lotto_floor <= lotto_cost
    ):
        raise RuntimeError("大樂透單一獎項不再保證五注嚴格獲利")
    lotto_profile = exact_prize_profile(
        LOTTO649, disjoint_reference_tickets(LOTTO649)
    )

    frontier = _pareto_frontier(rows)
    return {
        "schema_version": "1",
        "experiment_id": EXPERIMENT_ID,
        "rules_as_of": "2026-07-19",
        "official_prize_rules": OFFICIAL_RULE_URLS,
        "official_history": history,
        "face_prize_snapshot": _face_prize_snapshot(),
        "source_structural_proof": structural_proof_reference(),
        "question": (
            "五注合計成本後，能否在不犧牲至少四個主號全域最大機率的"
            "條件下，提高嚴格獲利機率？"
        ),
        "methodology": {
            "event_definitions": {
                "any_prize": "五注至少一注落入任一獎級。",
                "break_even": "五注獎金合計大於或等於五注成本。",
                "strict_profit": "五注獎金合計嚴格大於五注成本。",
            },
            "nominal_payout": (
                "固定獎級採規則面額；浮動獎級只作為必然高於五注成本的"
                "事件分類，不估算期望獎金。"
            ),
            "empirical_floor_stress": (
                "每個獎級改用凍結歷史中實際有人中獎時的最低 per_prize；"
                "這是資料壓力測試，不宣稱未來保證下限。"
            ),
            "main_structure_space": (
                "為保留至少四主號的 first-order union bound 全域最大值，"
                "限制任兩票主號 overlap <= 1。共享號碼形成五個票券頂點"
                "上的線性超圖；完整枚舉 2,625 個有標籤結構，再除以全部"
                " 120 個票券置換，得到 72 個不等價結構。"
            ),
            "special_space": (
                "第二區數字標籤本身對公平開獎機率不重要；完整枚舉五票"
                "相等關係的 52 個集合分割。"
            ),
            "search_candidates": EXPECTED_SEARCH_CANDIDATES,
            "exact_counting": (
                "逐 membership 群組用整數 DP 計數六個主號命中向量，再"
                "逐一枚舉八個第二區結果；不使用 Monte Carlo。"
            ),
            "pareto_objectives": (
                "同時最大化歷史最低實領壓力口徑的嚴格獲利率與任一獎率。"
            ),
            "lookahead": (
                "結構與規則分析不讀取任何目標期 reveal；不改動已凍結"
                " 7/20、7/21 前向號碼。"
            ),
        },
        "enumeration_certificate": {
            "labeled_linear_main_structures": (
                EXPECTED_LABELED_STRUCTURES
            ),
            "canonical_main_structures": (
                EXPECTED_CANONICAL_STRUCTURES
            ),
            "ticket_permutations_removed": len(TICKET_PERMUTATIONS),
            "special_partitions": EXPECTED_SPECIAL_PARTITIONS,
            "total_exact_candidates": len(rows),
            "pairwise_main_overlap_maximum": 1,
            "complete_within_high_tier_guardrail": True,
        },
        "games": {
            SUPER: {
                "game_name": GAME_NAMES[SUPER],
                "five_ticket_cost_ntd": (
                    PORTFOLIO_TICKETS * TICKET_PRICE[SUPER]
                ),
                "coverage_optimum_baseline": disjoint,
                "strict_profit_optimum": optimum,
                "robust_optimum_is_unique": (
                    len(robust_winners) == 1
                ),
                "nominal_optimum_is_unique": (
                    len(nominal_winners) == 1
                ),
                "same_optimum_under_both_payout_models": True,
                "pareto_frontier": frontier,
                "pareto_frontier_size": len(frontier),
                "tradeoff": {
                    "empirical_floor_strict_profit_probability_gain": (
                        robust_key(optimum)
                        / optimum["metrics"][
                            "empirical_floor_strict_profit"
                        ]["denominator"]
                        - robust_key(disjoint)
                        / disjoint["metrics"][
                            "empirical_floor_strict_profit"
                        ]["denominator"]
                    ),
                    "any_prize_probability_change": (
                        optimum["metrics"]["any_prize"]["probability"]
                        - disjoint["metrics"][
                            "any_prize"
                        ]["probability"]
                    ),
                    "at_least_three_main_probability_change": (
                        optimum["metrics"][
                            "at_least_three_main"
                        ]["probability"]
                        - disjoint["metrics"][
                            "at_least_three_main"
                        ]["probability"]
                    ),
                    "at_least_four_main_probability_change": (
                        optimum["metrics"][
                            "at_least_four_main"
                        ]["probability"]
                        - disjoint["metrics"][
                            "at_least_four_main"
                        ]["probability"]
                    ),
                },
            },
            LOTTO649: {
                "game_name": GAME_NAMES[LOTTO649],
                "five_ticket_cost_ntd": lotto_cost,
                "minimum_fixed_face_prize_ntd": minimum_lotto_face,
                "minimum_observed_per_prize_ntd": (
                    minimum_lotto_floor
                ),
                "any_prize_equals_nominal_strict_profit": True,
                "any_prize_equals_empirical_floor_strict_profit": True,
                "strict_profit_global_optimum": {
                    "structure": "五注主號兩兩互斥",
                    "probability": lotto_profile["any_prize"],
                    "proof": structural_proof_reference(),
                },
            },
        },
        "decision": {
            "automatic_switch": False,
            "reason": (
                "獲利最優與任一獎最優是不同效用函數；在使用者明確選擇"
                "前保留現行 coverage 策略，獲利結構只作已驗證候選。"
            ),
            "current_forward_registrations_unchanged": True,
            "profit_structure_available_for_future_shadow": True,
        },
        "conclusion": {
            "super": (
                "若目標改成五注合計嚴格獲利，完整搜尋的唯一最優結構是"
                "每一對票共享恰好一個主號，且五注第二區相同；它仍保持"
                "至少四主號的全域最大機率，但會降低任一獎與至少三主號"
                "的機率。"
            ),
            "lotto649": (
                "大樂透任一獎已高於五注成本，故完全分散五注同時是任一"
                "獎與嚴格獲利機率的全域最優結構。"
            ),
            "no_predictive_label_claim": (
                "本結果提高的是五注事件結構機率，不代表某個號碼標籤"
                "更容易被開出，也不改變單注頭獎機率。"
            ),
        },
        "limitations": [
            "完整性只針對保留至少四主號全域最優的 pairwise overlap <= 1 搜尋域；不宣稱是無守門條件的獲利全域最優。",
            "歷史最低實領額是截至凍結日的壓力情境，不是未來獎金保證。",
            "未估算浮動獎金期望值、多人均分、稅負或效用函數。",
            "依賴現行獎級、票價與公平且各期獨立的開獎模型。",
            "純模擬研究，不構成購買或下注建議。",
        ],
    }


def study_payload(base: Path) -> dict:
    return deepcopy(
        _study_payload_cached(str(Path(base).resolve()))
    )


def build_profit_probability_certificate(base: Path) -> dict:
    base = Path(base)
    records_before = tree_sha256(base / "records")
    payload = study_payload(base)
    records_after = tree_sha256(base / "records")
    if records_before != records_after:
        raise RuntimeError("獲利機率研究不應改動正式 records")
    return {
        **payload,
        "certificate_hash": canonical_hash(payload),
        "records_integrity": {
            "before_sha256": records_before,
            "after_sha256": records_after,
            "unchanged": records_before == records_after,
        },
    }


def verify_profit_probability_certificate(
    result: dict,
    base: Path,
) -> None:
    payload = study_payload(base)
    expected = {
        **payload,
        "certificate_hash": canonical_hash(payload),
    }
    actual = {key: result.get(key) for key in expected}
    if actual != expected:
        raise RuntimeError("獲利機率研究內容或 certificate hash 不符")
    integrity = result.get("records_integrity", {})
    if (
        integrity.get("unchanged") is not True
        or integrity.get("before_sha256")
        != integrity.get("after_sha256")
    ):
        raise RuntimeError("獲利機率研究 records 完整性不符")


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
