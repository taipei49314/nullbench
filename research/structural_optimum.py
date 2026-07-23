"""五注完整中獎聯集機率的有限、精確全域最優證明。

證明不枚舉號碼標籤，而枚舉三注六號集合的全部 Venn membership 結構。
三階 Bonferroni 上界配合逐三注驗證的 charge inequality，可把任意五注
的高階交集補償，全部充回相對於互斥五注增加的兩兩交集成本。
"""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import json
import math
import os
from pathlib import Path
from typing import Iterator

from engine.agent_loop import canonical_hash
from engine.games import (
    LOTTO649,
    PICK_N,
    POOL,
    SPECIAL_POOL,
    SUPER,
)
from research.gates import tree_sha256
from research.portfolio_coverage import (
    MAIN_HIT_THRESHOLD,
    _favorable_main_draw_count,
    _membership_counts,
    _pair_intersection_count,
    _single_favorable_count,
    exact_any_prize_count,
)


EXPERIMENT_ID = "five-ticket-structural-optimum-proof-v1"
PORTFOLIO_TICKETS = 5
PROOF_SUBSET_TICKETS = 3
PROFILE_COUNT_EXPECTED = 256
VALID_PROFILE_COUNT_EXPECTED = 237
OFFICIAL_RULE_URLS = {
    SUPER: (
        "https://www.taiwanlottery.com/lotto/info/"
        "super_lotto638"
    ),
    LOTTO649: (
        "https://www.taiwanlottery.com/lotto/info/lotto649"
    ),
}


def three_ticket_membership_profiles() -> Iterator[tuple[int, ...]]:
    """列出三個六號集合的全部 256 個無標籤 Venn 計數向量。"""
    ticket_count = PROOF_SUBSET_TICKETS
    masks = tuple(range(1, 1 << ticket_count))
    counts = [0] * (1 << ticket_count)

    def visit(
        position: int,
        remaining: tuple[int, ...],
    ) -> Iterator[tuple[int, ...]]:
        if position == len(masks):
            if all(value == 0 for value in remaining):
                yield tuple(counts)
            return
        mask = masks[position]
        members = tuple(
            index
            for index in range(ticket_count)
            if mask & (1 << index)
        )
        maximum = min(remaining[index] for index in members)
        for amount in range(maximum + 1):
            counts[mask] = amount
            next_remaining = list(remaining)
            for index in members:
                next_remaining[index] -= amount
            yield from visit(position + 1, tuple(next_remaining))
        counts[mask] = 0

    yield from visit(0, (PICK_N,) * ticket_count)


def _pair_overlaps(profile: tuple[int, ...]) -> tuple[int, int, int]:
    return tuple(
        sum(
            amount
            for mask, amount in enumerate(profile)
            if mask & (1 << left) and mask & (1 << right)
        )
        for left, right in ((0, 1), (0, 2), (1, 2))
    )


def _valid_distinct_profile(profile: tuple[int, ...]) -> bool:
    return all(overlap < PICK_N for overlap in _pair_overlaps(profile))


def _canonical_tickets(
    game: str,
    profile: tuple[int, ...],
) -> list[dict]:
    ticket_count = (len(profile)).bit_length() - 1
    numbers = [[] for _ in range(ticket_count)]
    value = 1
    for mask, amount in enumerate(profile):
        for _ in range(amount):
            for index in range(ticket_count):
                if mask & (1 << index):
                    numbers[index].append(value)
            value += 1
    return [
        {
            "slot": index + 1,
            "source_agent": "structural_proof",
            "source_proposal": f"structural:{index + 1}",
            "numbers": row,
            "special": index + 1 if game == SUPER else None,
        }
        for index, row in enumerate(numbers)
    ]


def disjoint_reference_tickets(game: str) -> list[dict]:
    return [
        {
            "slot": index + 1,
            "source_agent": "structural_proof",
            "source_proposal": f"disjoint:{index + 1}",
            "numbers": list(
                range(index * PICK_N + 1, (index + 1) * PICK_N + 1)
            ),
            "special": index + 1 if game == SUPER else None,
        }
        for index in range(PORTFOLIO_TICKETS)
    ]


@lru_cache(maxsize=None)
def _any_single_count(game: str) -> tuple[int, int]:
    special = 1 if game == SUPER else None
    return exact_any_prize_count(
        game,
        [{"numbers": list(range(1, PICK_N + 1)), "special": special}],
    )


@lru_cache(maxsize=None)
def _any_pair_intersection_count(
    game: str,
    overlap: int,
    same_special: bool | None,
) -> int:
    if not 0 <= overlap < PICK_N:
        raise ValueError("不同票券的主號重疊必須介於 0 與 5")
    left = list(range(1, PICK_N + 1))
    right = list(range(1, overlap + 1)) + list(
        range(PICK_N + 1, PICK_N + 1 + PICK_N - overlap)
    )
    if game == SUPER:
        if not isinstance(same_special, bool):
            raise ValueError("威力彩必須指定第二區是否相同")
        specials = (1, 1 if same_special else 2)
    elif game == LOTTO649:
        if same_special is not None:
            raise ValueError("大樂透沒有玩家選擇的特別號")
        specials = (None, None)
    else:
        raise ValueError(f"不支援的遊戲：{game}")
    union, denominator = exact_any_prize_count(
        game,
        [
            {"numbers": left, "special": specials[0]},
            {"numbers": right, "special": specials[1]},
        ],
    )
    single, single_denominator = _any_single_count(game)
    if denominator != single_denominator:
        raise RuntimeError("任一獎級精確分母不一致")
    return 2 * single - union


def _full_membership_counts(
    game: str,
    profile: tuple[int, ...],
) -> tuple[int, ...]:
    counts = list(profile)
    outside = POOL[game] - sum(counts)
    if outside < 0:
        raise ValueError("membership 聯集超過號碼池")
    counts[0] = outside
    return tuple(counts)


def _main_union_count(
    game: str,
    profile: tuple[int, ...],
) -> int:
    return _favorable_main_draw_count(
        POOL[game],
        _full_membership_counts(game, profile),
        require_all=False,
        threshold=MAIN_HIT_THRESHOLD,
    )


def _metric_certificate(game: str, metric: str) -> dict:
    if metric == "any_prize":
        single, denominator = _any_single_count(game)
        pair = lambda overlap: _any_pair_intersection_count(
            game,
            overlap,
            False if game == SUPER else None,
        )

        def triple_union(profile: tuple[int, ...]) -> int:
            favorable, current_denominator = exact_any_prize_count(
                game,
                _canonical_tickets(game, profile),
            )
            if current_denominator != denominator:
                raise RuntimeError("三注任一獎級精確分母不一致")
            return favorable

        disjoint_actual, current_denominator = exact_any_prize_count(
            game, disjoint_reference_tickets(game)
        )
        if current_denominator != denominator:
            raise RuntimeError("五注任一獎級精確分母不一致")
    elif metric == "three_main":
        denominator = math.comb(POOL[game], PICK_N)
        single = _single_favorable_count(
            POOL[game], MAIN_HIT_THRESHOLD
        )
        pair = lambda overlap: _pair_intersection_count(
            POOL[game],
            overlap,
            MAIN_HIT_THRESHOLD,
        )
        triple_union = lambda profile: _main_union_count(game, profile)
        disjoint = disjoint_reference_tickets(game)
        disjoint_actual = _favorable_main_draw_count(
            POOL[game],
            _membership_counts(
                POOL[game],
                [set(ticket["numbers"]) for ticket in disjoint],
            ),
            require_all=False,
            threshold=MAIN_HIT_THRESHOLD,
        )
    else:
        raise ValueError(f"不支援的證明指標：{metric}")

    pair_counts = [pair(overlap) for overlap in range(PICK_N)]
    pair_minimum = pair_counts[0]
    profile_count = 0
    valid_profile_count = 0
    violations = 0
    disjoint_profiles = 0
    minimum_slack = None
    minimum_non_disjoint_slack = None
    maximum_triple = 0
    for profile in three_ticket_membership_profiles():
        profile_count += 1
        if not _valid_distinct_profile(profile):
            continue
        valid_profile_count += 1
        overlaps = _pair_overlaps(profile)
        pair_sum = sum(pair_counts[value] for value in overlaps)
        triple = triple_union(profile) - 3 * single + pair_sum
        if triple < 0:
            raise RuntimeError("三重交集精確計數不得為負")
        charge_slack = (
            sum(
                pair_counts[value] - pair_minimum
                for value in overlaps
            )
            - 3 * triple
        )
        if charge_slack < 0:
            violations += 1
        minimum_slack = (
            charge_slack
            if minimum_slack is None
            else min(minimum_slack, charge_slack)
        )
        if any(overlaps):
            minimum_non_disjoint_slack = (
                charge_slack
                if minimum_non_disjoint_slack is None
                else min(
                    minimum_non_disjoint_slack,
                    charge_slack,
                )
            )
        else:
            disjoint_profiles += 1
        maximum_triple = max(maximum_triple, triple)

    theoretical_maximum = (
        PORTFOLIO_TICKETS * single
        - math.comb(PORTFOLIO_TICKETS, 2) * pair_minimum
    )
    if (
        profile_count != PROFILE_COUNT_EXPECTED
        or valid_profile_count != VALID_PROFILE_COUNT_EXPECTED
        or violations
        or minimum_slack != 0
        or minimum_non_disjoint_slack is None
        or minimum_non_disjoint_slack <= 0
        or disjoint_actual != theoretical_maximum
    ):
        raise RuntimeError(f"{game} {metric} 結構最優證明未通過")

    return {
        "denominator": denominator,
        "single_ticket_favorable_count": single,
        "pair_intersection_by_main_overlap": [
            {
                "main_overlap": overlap,
                "favorable_count": count,
                "probability": count / denominator,
            }
            for overlap, count in enumerate(pair_counts)
        ],
        "pair_intersection_strictly_increasing": all(
            left < right
            for left, right in zip(pair_counts, pair_counts[1:])
        ),
        "three_ticket_profiles_total": profile_count,
        "three_ticket_profiles_valid_distinct": valid_profile_count,
        "three_ticket_profiles_excluded_duplicate": (
            profile_count - valid_profile_count
        ),
        "triple_charge_violations": violations,
        "minimum_charge_slack_numerator": minimum_slack,
        "minimum_non_disjoint_charge_slack_numerator": (
            minimum_non_disjoint_slack
        ),
        "maximum_triple_intersection_numerator": maximum_triple,
        "disjoint_triple_intersection_numerator": 0,
        "global_maximum_favorable_count": theoretical_maximum,
        "global_maximum_probability": (
            theoretical_maximum / denominator
        ),
        "disjoint_actual_favorable_count": disjoint_actual,
        "global_optimum_proved": True,
        "unique_structural_condition": (
            "五注主號兩兩互斥；號碼標籤與票券順序可任意置換"
        ),
    }


def _super_duplicate_special_certificate(
    disjoint_maximum: int,
) -> dict:
    denominator = _any_single_count(SUPER)[1]
    single = _any_single_count(SUPER)[0]
    different = [
        _any_pair_intersection_count(SUPER, overlap, False)
        for overlap in range(PICK_N)
    ]
    same = [
        _any_pair_intersection_count(SUPER, overlap, True)
        for overlap in range(PICK_N)
    ]
    hunter_upper = (
        PORTFOLIO_TICKETS * single - (same[0] + 3 * different[0])
    )
    margin = same[0] - 7 * different[0]
    if (
        not all(left < right for left, right in zip(same, same[1:]))
        or min(same) <= min(different)
        or margin <= 0
        or hunter_upper >= disjoint_maximum
    ):
        raise RuntimeError("威力彩重複第二區 Hunter 上界未通過")
    return {
        "same_special_pair_intersection_by_main_overlap": [
            {
                "main_overlap": overlap,
                "favorable_count": count,
                "probability": count / denominator,
            }
            for overlap, count in enumerate(same)
        ],
        "minimum_same_special_pair_intersection": same[0],
        "minimum_distinct_special_pair_intersection": different[0],
        "hunter_tree_margin_numerator": margin,
        "hunter_upper_bound_favorable_count": hunter_upper,
        "disjoint_distinct_special_favorable_count": (
            disjoint_maximum
        ),
        "duplicate_special_cannot_reach_global_maximum": True,
    }


@lru_cache(maxsize=1)
def _proof_payload_cached() -> dict:
    games = {}
    for game in (SUPER, LOTTO649):
        any_prize = _metric_certificate(game, "any_prize")
        three_main = _metric_certificate(game, "three_main")
        row = {
            "pool": POOL[game],
            "ticket_count": PORTFOLIO_TICKETS,
            "pick_n": PICK_N,
            "any_prize": any_prize,
            "three_main": three_main,
        }
        if game == SUPER:
            row["special_pool"] = SPECIAL_POOL[SUPER]
            row["duplicate_special_proof"] = (
                _super_duplicate_special_certificate(
                    any_prize["global_maximum_favorable_count"]
                )
            )
        games[game] = row
    return {
        "schema_version": "1",
        "experiment_id": EXPERIMENT_ID,
        "rules_as_of": "2026-07-18",
        "official_prize_rules": OFFICIAL_RULE_URLS,
        "question": (
            "固定五注時，主號完全互斥（威力彩第二區亦互異）是否為"
            "完整任一獎級與至少三主號聯集機率的全域最大結構？"
        ),
        "methodology": {
            "finite_state_space": (
                "三個六號集合的全部 256 個 Venn membership 計數向量；"
                "排除 19 個含重複票券結構後，逐遊戲精算 237 個。"
            ),
            "upper_bound": (
                "三階 Bonferroni：U <= sum(Pi) - sum(Pij) + "
                "sum(Pijk)。"
            ),
            "triple_charge_inequality": (
                "每個三注結構精確驗證 3*Pijk <= "
                "sum_pairs(Pij-P0)；加總時每一票對恰出現三次。"
            ),
            "super_duplicate_special": (
                "若任兩注第二區相同，Hunter spanning-tree 上界已"
                "嚴格低於五個互異第二區的完全分散值。"
            ),
            "calculation": "整數組合計數；不使用 Monte Carlo",
            "lookahead": "純結構定理，不讀取歷史開獎或目標期 reveal",
        },
        "games": games,
        "conclusion": {
            "global_optimum_proved": True,
            "super": (
                "五注主號兩兩互斥且五個第二區互異，完整任一獎級"
                "機率全域最大。"
            ),
            "lotto649": (
                "五注主號兩兩互斥，完整任一獎級機率全域最大。"
            ),
            "three_main_guardrail": (
                "兩款遊戲的至少一注命中三主號機率亦由主號完全"
                "互斥結構全域最大化。"
            ),
            "label_invariance": (
                "Agent 只在同一最優結構內排序號碼標籤；公平獨立"
                "開獎下，標籤不改變上述機率。"
            ),
        },
        "limitations": [
            "證明依賴現行獎級定義、公平且各期獨立的官方開獎模型。",
            "證明最大化五注聯集事件，不提高單注或頭獎組合機率。",
            "歷史命中差仍須由開獎前凍結的 forward shadow 驗證。",
            "純模擬，不構成購買或下注建議。",
        ],
    }


def proof_payload() -> dict:
    return deepcopy(_proof_payload_cached())


def structural_proof_reference() -> dict:
    payload = _proof_payload_cached()
    return {
        "experiment_id": EXPERIMENT_ID,
        "certificate_hash": canonical_hash(payload),
    }


def build_structural_optimum_certificate(
    base: Path,
) -> dict:
    base = Path(base)
    records_before = tree_sha256(base / "records")
    payload = proof_payload()
    records_after = tree_sha256(base / "records")
    if records_before != records_after:
        raise RuntimeError("結構最優證明不應改動正式 records")
    return {
        **payload,
        "certificate_hash": canonical_hash(payload),
        "records_integrity": {
            "before_sha256": records_before,
            "after_sha256": records_after,
            "unchanged": records_before == records_after,
        },
    }


def verify_structural_optimum_certificate(result: dict) -> None:
    payload = proof_payload()
    expected = {
        **payload,
        "certificate_hash": canonical_hash(payload),
    }
    actual = {
        key: result.get(key)
        for key in expected
    }
    if actual != expected:
        raise RuntimeError("結構最優證明內容或 certificate hash 不符")
    integrity = result.get("records_integrity", {})
    if (
        integrity.get("unchanged") is not True
        or integrity.get("before_sha256")
        != integrity.get("after_sha256")
    ):
        raise RuntimeError("結構最優證明 records 完整性不符")


def write_results(result: dict, path: Path) -> Path:
    verify_structural_optimum_certificate(result)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return path
