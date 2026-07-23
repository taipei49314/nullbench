"""五注完全分散結構的精確獎級、同時中獎與邊際機率分解。

本模組只做有限組合計數，不使用歷史開獎、Monte Carlo 或目標期 reveal。
主號動態規劃保留每注 0 至 6 個命中的完整向量；大樂透另保留每個
membership 群組已被六個主號抽走的總數，據此精確計算剩餘特別號的歸屬。
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from functools import lru_cache
import json
import math
import os
from pathlib import Path

from engine.agent_loop import SELECTED_TICKETS, canonical_hash
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
from research.portfolio_coverage import (
    MAIN_HIT_THRESHOLD,
    _favorable_main_draw_count,
    _membership_counts,
    _ticket_sets,
)
from research.structural_optimum import (
    OFFICIAL_RULE_URLS,
    disjoint_reference_tickets,
    structural_proof_reference,
)


EXPERIMENT_ID = "five-ticket-prize-tier-profile-v1"


def _validate_membership_counts(
    pool: int,
    membership_counts: tuple[int, ...],
) -> int:
    ticket_count = (len(membership_counts)).bit_length() - 1
    if (
        len(membership_counts) != 1 << ticket_count
        or not 1 <= ticket_count <= SELECTED_TICKETS
    ):
        raise ValueError(
            f"membership_counts 必須描述 1 至 {SELECTED_TICKETS} 注"
        )
    if (
        pool <= PICK_N
        or any(value < 0 for value in membership_counts)
        or sum(membership_counts) != pool
    ):
        raise ValueError("membership_counts 必須完整分割合法號碼池")
    return ticket_count


@lru_cache(maxsize=512)
def _exact_hit_state_distribution(
    pool: int,
    membership_counts: tuple[int, ...],
) -> tuple[tuple[tuple[int, ...], int, tuple[int, ...]], ...]:
    """回傳六主號的精確命中向量、組合數與各 membership 抽中總數。

    ``selected_by_mask[mask]`` 是所有產生同一命中向量的主號組合中，
    從「恰好屬於 mask」群組抽中的號碼總數。大樂透用
    ``group_size * ways - selected_by_mask[mask]`` 得到尚可成為特別號的
    精確個數。
    """
    ticket_count = _validate_membership_counts(
        pool, membership_counts
    )
    mask_count = 1 << ticket_count
    states: dict[
        tuple[int, tuple[int, ...]],
        tuple[int, tuple[int, ...]],
    ] = {
        (0, (0,) * ticket_count): (1, (0,) * mask_count)
    }
    for mask, group_size in enumerate(membership_counts):
        if group_size == 0:
            continue
        next_states: dict[tuple[int, tuple[int, ...]], list] = {}
        for (chosen, hits), (ways, selected_by_mask) in states.items():
            maximum = min(group_size, PICK_N - chosen)
            for take in range(maximum + 1):
                factor = math.comb(group_size, take)
                next_hits = tuple(
                    hit
                    + (
                        take
                        if mask & (1 << ticket_index)
                        else 0
                    )
                    for ticket_index, hit in enumerate(hits)
                )
                key = (chosen + take, next_hits)
                aggregate = next_states.setdefault(
                    key, [0, [0] * mask_count]
                )
                aggregate[0] += ways * factor
                for exact_mask, selected in enumerate(
                    selected_by_mask
                ):
                    aggregate[1][exact_mask] += selected * factor
                aggregate[1][mask] += ways * take * factor
        states = {
            key: (value[0], tuple(value[1]))
            for key, value in next_states.items()
        }

    distribution = tuple(
        (hits, ways, selected_by_mask)
        for (chosen, hits), (ways, selected_by_mask) in sorted(
            states.items()
        )
        if chosen == PICK_N
    )
    if sum(ways for _, ways, _ in distribution) != math.comb(
        pool, PICK_N
    ):
        raise RuntimeError("精確命中向量的主號組合總數不守恆")
    return distribution


def _tier_by_result(game: str) -> dict[tuple[int, bool], object]:
    return {
        (tier.match_main, tier.match_special): tier
        for tier in TIERS[game]
    }


def _exact_prize_profile_from_memberships(
    game: str,
    pool: int,
    membership_counts: tuple[int, ...],
    specials: tuple[int | None, ...],
) -> dict:
    """以可縮小的號碼池精確計數，供正式計算與獨立窮舉測試共用。"""
    ticket_count = _validate_membership_counts(
        pool, membership_counts
    )
    if len(specials) != ticket_count:
        raise ValueError("specials 長度必須等於票券數")
    if game == SUPER:
        if any(
            not isinstance(special, int)
            or not 1 <= special <= SPECIAL_POOL[SUPER]
            for special in specials
        ):
            raise ValueError("威力彩第二區必須介於 1 至 8")
        extra_outcomes = SPECIAL_POOL[SUPER]
    elif game == LOTTO649:
        if any(special is not None for special in specials):
            raise ValueError("大樂透玩家不選特別號")
        extra_outcomes = pool - PICK_N
    else:
        raise ValueError(f"不支援的遊戲：{game}")

    best_tier_counts = {
        tier.rank: 0 for tier in TIERS[game]
    }
    awarded_tier_ticket_counts = {
        tier.rank: 0 for tier in TIERS[game]
    }
    winning_ticket_count_counts = {
        count: 0 for count in range(ticket_count + 1)
    }
    maximum_main_hits_counts = {
        hits: 0 for hits in range(PICK_N + 1)
    }
    no_prize = 0
    tier_lookup = _tier_by_result(game)

    def add_outcome(
        hits: tuple[int, ...],
        special_hits: tuple[bool, ...],
        weight: int,
    ) -> None:
        nonlocal no_prize
        winning_ranks = []
        for main_hits, special_hit in zip(hits, special_hits):
            tier = tier_lookup.get((main_hits, special_hit))
            if tier is not None:
                winning_ranks.append(tier.rank)
                awarded_tier_ticket_counts[tier.rank] += weight
        winning_ticket_count_counts[len(winning_ranks)] += weight
        maximum_main_hits_counts[max(hits)] += weight
        if winning_ranks:
            best_tier_counts[min(winning_ranks)] += weight
        else:
            no_prize += weight

    distribution = _exact_hit_state_distribution(
        pool, membership_counts
    )
    if game == SUPER:
        for hits, ways, _ in distribution:
            for special_outcome in range(
                1, SPECIAL_POOL[SUPER] + 1
            ):
                add_outcome(
                    hits,
                    tuple(
                        selected == special_outcome
                        for selected in specials
                    ),
                    ways,
                )
    else:
        for hits, ways, selected_by_mask in distribution:
            for mask, group_size in enumerate(membership_counts):
                available = (
                    group_size * ways - selected_by_mask[mask]
                )
                if available < 0:
                    raise RuntimeError(
                        "大樂透剩餘特別號計數不得為負"
                    )
                if available == 0:
                    continue
                add_outcome(
                    hits,
                    tuple(
                        bool(mask & (1 << ticket_index))
                        for ticket_index in range(ticket_count)
                    ),
                    available,
                )

    denominator = math.comb(pool, PICK_N) * extra_outcomes
    if (
        sum(best_tier_counts.values()) + no_prize
        != denominator
        or sum(winning_ticket_count_counts.values())
        != denominator
        or sum(maximum_main_hits_counts.values())
        != denominator
    ):
        raise RuntimeError("獎級分解的開獎樣本空間不守恆")
    return {
        "denominator": denominator,
        "best_tier_counts": best_tier_counts,
        "awarded_tier_ticket_counts": (
            awarded_tier_ticket_counts
        ),
        "winning_ticket_count_counts": (
            winning_ticket_count_counts
        ),
        "maximum_main_hits_counts": maximum_main_hits_counts,
        "no_prize_count": no_prize,
    }


def _count_row(numerator: int, denominator: int) -> dict:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "probability": numerator / denominator,
    }


def exact_prize_profile(game: str, tickets: list[dict]) -> dict:
    """回傳 1 至 5 注的完整精確獎級與多注同中分布。"""
    sets = _ticket_sets(game, tickets, expected_count=None)
    if len(sets) > SELECTED_TICKETS:
        raise ValueError(
            f"精確獎級分解最多支援 {SELECTED_TICKETS} 注"
        )
    pool = POOL[game]
    raw = _exact_prize_profile_from_memberships(
        game,
        pool,
        _membership_counts(pool, sets),
        tuple(ticket.get("special") for ticket in tickets),
    )
    denominator = raw["denominator"]
    cumulative = 0
    best_tiers = []
    awarded_tiers = []
    for tier in TIERS[game]:
        best_count = raw["best_tier_counts"][tier.rank]
        awarded_count = raw["awarded_tier_ticket_counts"][
            tier.rank
        ]
        cumulative += best_count
        best_tiers.append(
            {
                "rank": tier.rank,
                "label": tier.label,
                **_count_row(best_count, denominator),
                "best_rank_at_most_probability": (
                    cumulative / denominator
                ),
            }
        )
        awarded_tiers.append(
            {
                "rank": tier.rank,
                "label": tier.label,
                "ticket_outcome_count": awarded_count,
                "expected_winning_tickets": (
                    awarded_count / denominator
                ),
            }
        )

    any_prize_count = denominator - raw["no_prize_count"]
    expected_winning_ticket_numerator = sum(
        count * outcomes
        for count, outcomes in raw[
            "winning_ticket_count_counts"
        ].items()
    )
    if expected_winning_ticket_numerator != sum(
        raw["awarded_tier_ticket_counts"].values()
    ):
        raise RuntimeError("中獎注數期望值與逐獎級票券數不守恆")
    return {
        "game": game,
        "ticket_count": len(tickets),
        "denominator": denominator,
        "any_prize": _count_row(any_prize_count, denominator),
        "no_prize": _count_row(
            raw["no_prize_count"], denominator
        ),
        "best_tier_distribution": best_tiers,
        "awarded_tier_ticket_expectation": awarded_tiers,
        "winning_ticket_count_distribution": [
            {
                "winning_tickets": count,
                **_count_row(outcomes, denominator),
            }
            for count, outcomes in sorted(
                raw["winning_ticket_count_counts"].items()
            )
        ],
        "expected_winning_tickets": (
            expected_winning_ticket_numerator / denominator
        ),
        "maximum_main_hits_distribution": [
            {
                "maximum_main_hits": hits,
                **_count_row(outcomes, denominator),
            }
            for hits, outcomes in sorted(
                raw["maximum_main_hits_counts"].items()
            )
        ],
    }


def _reference_tickets(game: str, ticket_count: int) -> list[dict]:
    if not 1 <= ticket_count <= SELECTED_TICKETS:
        raise ValueError("ticket_count 必須介於 1 與 5")
    return disjoint_reference_tickets(game)[:ticket_count]


def _ticket_count_curve(game: str) -> list[dict]:
    rows = []
    previous_any = 0
    previous_three_main = 0
    for ticket_count in range(1, SELECTED_TICKETS + 1):
        tickets = _reference_tickets(game, ticket_count)
        profile = exact_prize_profile(game, tickets)
        sets = [set(ticket["numbers"]) for ticket in tickets]
        three_main_denominator = math.comb(POOL[game], PICK_N)
        three_main_count = _favorable_main_draw_count(
            POOL[game],
            _membership_counts(POOL[game], sets),
            require_all=False,
            threshold=MAIN_HIT_THRESHOLD,
        )
        any_count = profile["any_prize"]["numerator"]
        any_denominator = profile["any_prize"]["denominator"]
        row = {
            "ticket_count": ticket_count,
            "simulated_cost_ntd": (
                ticket_count * TICKET_PRICE[game]
            ),
            "any_prize": _count_row(
                any_count, any_denominator
            ),
            "marginal_any_prize": _count_row(
                any_count - previous_any,
                any_denominator,
            ),
            "at_least_three_main": _count_row(
                three_main_count, three_main_denominator
            ),
            "marginal_at_least_three_main": _count_row(
                three_main_count - previous_three_main,
                three_main_denominator,
            ),
        }
        rows.append(row)
        previous_any = any_count
        previous_three_main = three_main_count
    return rows


@lru_cache(maxsize=1)
def _study_payload_cached() -> dict:
    games = {}
    for game in (SUPER, LOTTO649):
        curve = _ticket_count_curve(game)
        five_profile = exact_prize_profile(
            game, _reference_tickets(game, SELECTED_TICKETS)
        )
        games[game] = {
            "game_name": GAME_NAMES[game],
            "pool": POOL[game],
            "pick_n": PICK_N,
            "ticket_price_ntd": TICKET_PRICE[game],
            "special_pool": (
                SPECIAL_POOL[SUPER] if game == SUPER else None
            ),
            "ticket_count_curve": curve,
            "five_ticket_profile": five_profile,
            "jackpot_probability_five_tickets": (
                five_profile["best_tier_distribution"][0]
            ),
            "multi_win_probability": sum(
                row["probability"]
                for row in five_profile[
                    "winning_ticket_count_distribution"
                ]
                if row["winning_tickets"] >= 2
            ),
        }
    return {
        "schema_version": "1",
        "experiment_id": EXPERIMENT_ID,
        "rules_as_of": "2026-07-19",
        "official_prize_rules": OFFICIAL_RULE_URLS,
        "question": (
            "五注完全分散的任一獎機率由哪些最高獎級組成，"
            "可能同時中幾注，第 1 至第 5 注各增加多少聯集機率？"
        ),
        "methodology": {
            "main_draws": (
                "依票券 Venn membership 群組，以整數動態規劃精確"
                "計數每注 0 至 6 個主號的完整命中向量。"
            ),
            "super_special": "逐一枚舉第二區 1 至 8。",
            "lotto649_bonus": (
                "對每個精確 membership 群組，從群組大小扣除已被"
                "六主號抽走的總數，計數剩餘特別號歸屬。"
            ),
            "tier_assignment": (
                "每個完整開獎結果逐注套用現行獎級；另記錄最高"
                "獎級、所有獲獎票券與同時中獎注數。"
            ),
            "calculation": "全程整數組合計數；不使用 Monte Carlo",
            "lookahead": "純規則與結構分析，不讀歷史開獎或目標期 reveal",
            "structural_optimum_proof": (
                structural_proof_reference()
            ),
        },
        "games": games,
        "conclusion": {
            "scope": (
                "54.2963% 與 15.2966% 是五注至少一注落入任一"
                "獎級的聯集機率，不是頭獎機率。"
            ),
            "jackpot": (
                "五注完全分散只把五個不同頭獎組合相加；每注的"
                "頭獎機率不變，五注頭獎機率仍極低。"
            ),
            "marginal": (
                "第 1 至第 5 注的聯集增益逐注列示；重疊事件會使"
                "新增一注的任一獎增益低於單注任一獎機率。"
            ),
            "strategy": (
                "本分析釐清風險與獎級構成，不提供新的歷史標籤"
                "預測訊號，也不改動已凍結號碼。"
            ),
        },
        "limitations": [
            "依賴現行獎級定義、公平且各期獨立的官方開獎模型。",
            "只分析命中機率；浮動獎金、多人均分與期望報酬另需模型。",
            "任一獎機率主要受低獎級影響，不能代表獲利機率。",
            "純模擬，不構成購買或下注建議。",
        ],
    }


def study_payload() -> dict:
    return deepcopy(_study_payload_cached())


def build_prize_tier_certificate(base: Path) -> dict:
    base = Path(base)
    records_before = tree_sha256(base / "records")
    payload = study_payload()
    records_after = tree_sha256(base / "records")
    if records_before != records_after:
        raise RuntimeError("獎級機率分析不應改動正式 records")
    return {
        **payload,
        "certificate_hash": canonical_hash(payload),
        "records_integrity": {
            "before_sha256": records_before,
            "after_sha256": records_after,
            "unchanged": records_before == records_after,
        },
    }


def verify_prize_tier_certificate(result: dict) -> None:
    payload = study_payload()
    expected = {
        **payload,
        "certificate_hash": canonical_hash(payload),
    }
    actual = {key: result.get(key) for key in expected}
    if actual != expected:
        raise RuntimeError("獎級機率分析內容或 certificate hash 不符")
    integrity = result.get("records_integrity", {})
    if (
        integrity.get("unchanged") is not True
        or integrity.get("before_sha256")
        != integrity.get("after_sha256")
    ):
        raise RuntimeError("獎級機率分析 records 完整性不符")


def write_results(result: dict, path: Path) -> Path:
    verify_prize_tier_certificate(result)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return path
