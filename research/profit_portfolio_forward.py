"""把開獎前 Agent 排序映射成已證明的威力彩五注獲利結構。

本模組只做標籤映射與輕量結構驗證，不重新搜尋策略，也不讀取開獎結果。
完整有限枚舉證明保存在兩個研究 certificate；forward 登記只引用固定 hash。
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy

from engine.agent_loop import canonical_hash
from engine.games import PICK_N, SPECIAL_POOL, SUPER, validate_pick


EXPERIMENT_ID = "profit-portfolio-forward-shadows-v1"
COMMON_SPECIAL_SHADOW_EXPERIMENT_ID = (
    "profit-common-special-forward-shadow-v1"
)
COMMON_SPECIAL_SOURCE_EXPERIMENT_ID = (
    "draw-mechanism-signal-audit-v1"
)
COMMON_SPECIAL_CANDIDATE_HASH = (
    "99a3f01dd841b566e4582aff9699500b07eab140cc101ec000e0463157abf987"
)
COMMON_SPECIAL_FITTED_THROUGH = "2021-03-01"
COMMON_SPECIAL_SELECTED = 2
GUARDED_PROFIT = "guarded_profit"
UNCONSTRAINED_PROFIT = "unconstrained_profit"
PORTFOLIO_IDS = (GUARDED_PROFIT, UNCONSTRAINED_PROFIT)
SELECTED_TICKETS = 5
FIVE_TICKET_COST_NTD = 500

GUARDED_PROOF = {
    "experiment_id": "five-ticket-profit-pareto-proof-v1",
    "certificate_hash": (
        "b91fb1e1f4a4f7ba6478389b05182761472fcdc9784460967b9011a739356ee4"
    ),
}
UNCONSTRAINED_PROOF = {
    "experiment_id": (
        "five-ticket-unconstrained-profit-optimum-proof-v2"
    ),
    "certificate_hash": (
        "9fa8d7949ce75887af774e664ef913392d723eb58c5bacab1e47e50838216acb"
    ),
}

# 五個 ticket vertex 的 bit mask。guarded 結構讓十組 ticket pair 各共享一碼；
# unconstrained 結構讓十組 ticket triple 各共享一碼。
GUARDED_SHARED_MASKS = (3, 5, 6, 9, 10, 12, 17, 18, 20, 24)
UNCONSTRAINED_MASKS = (7, 11, 13, 14, 19, 21, 22, 25, 26, 28)

EMPIRICAL_FLOOR_NTD = {
    "super638JackpotAssign": 176_434_164,
    "super638SecondAssign": 716_941,
    "super638ThirdAssign": 54_252,
    "super638FourthAssign": 9_462,
    "super638FifthAssign": 2_058,
    "super638SixthAssign": 540,
    "super638SeventhAssign": 277,
    "super638EighthAssign": 200,
    "super638NinthAssign": 100,
    "super638NormalAssign": 100,
}
EMPIRICAL_FLOOR_SNAPSHOT = {
    "cutoff_inclusive": "2026-07-17",
    "normalized_prize_snapshot_hash": (
        "1aee44402df74e99855fdfb0016648321b0fa94094b4bcf04d75cc00b60da6e6"
    ),
    "minimum_observed_per_prize_ntd": EMPIRICAL_FLOOR_NTD,
    "honesty_note": (
        "歷史最低實領只作壓力測試，不是未來獎金保證下限。"
    ),
}

EXACT_METRICS = {
    GUARDED_PROFIT: {
        "any_prize": {
            "numerator": 6_275_717,
            "denominator": 22_085_448,
            "probability": 0.2841562009518666,
        },
        "empirical_floor_strict_profit": {
            "numerator": 1_203_926,
            "denominator": 22_085_448,
            "probability": 0.054512183769149715,
        },
        "at_least_three_main": {
            "numerator": 4_038_400,
            "denominator": 22_085_448,
            "probability": 0.18285343362742743,
        },
        "at_least_four_main": {
            "numerator": 305_320,
            "denominator": 22_085_448,
            "probability": 0.013824487508698035,
        },
    },
    UNCONSTRAINED_PROFIT: {
        "any_prize": {
            "numerator": 5_054_343,
            "denominator": 22_085_448,
            "probability": 0.2288539947208678,
        },
        "empirical_floor_strict_profit": {
            "numerator": 1_648_101,
            "denominator": 22_085_448,
            "probability": 0.07462384281269731,
        },
        "at_least_three_main": {
            "numerator": 3_051_888,
            "denominator": 22_085_448,
            "probability": 0.1381854694548193,
        },
        "at_least_four_main": {
            "numerator": 282_240,
            "denominator": 22_085_448,
            "probability": 0.012779455503913708,
        },
    },
}


def _tickets_from_memberships(
    ranked_numbers: list[int],
    masks: tuple[int, ...],
    *,
    special: int,
    source_agent: str,
    source_prefix: str,
    singleton_count: int = 0,
) -> list[dict]:
    numbers = [[] for _ in range(SELECTED_TICKETS)]
    shared_count = len(masks)
    expected = shared_count + singleton_count * SELECTED_TICKETS
    selected = [int(number) for number in ranked_numbers[:expected]]
    if len(selected) != expected or len(set(selected)) != expected:
        raise ValueError("獲利 shadow 的辯論號碼排序不足或重複")
    if not 1 <= int(special) <= SPECIAL_POOL[SUPER]:
        raise ValueError("獲利 shadow 第二區號碼超出 1~8")

    for number, mask in zip(selected[:shared_count], masks):
        for ticket_index in range(SELECTED_TICKETS):
            if mask & (1 << ticket_index):
                numbers[ticket_index].append(number)
    cursor = shared_count
    for ticket_numbers in numbers:
        ticket_numbers.extend(selected[cursor : cursor + singleton_count])
        cursor += singleton_count

    tickets = [
        {
            "slot": ticket_index + 1,
            "source_agent": source_agent,
            "source_proposal": f"{source_prefix}:{ticket_index + 1}",
            "numbers": sorted(ticket_numbers),
            "special": int(special),
        }
        for ticket_index, ticket_numbers in enumerate(numbers)
    ]
    for ticket in tickets:
        validate_pick(SUPER, ticket["numbers"], ticket["special"])
    if len({tuple(ticket["numbers"]) for ticket in tickets}) != 5:
        raise RuntimeError("獲利 shadow 產生重複票券")
    return tickets


def _membership_histogram(tickets: list[dict]) -> dict[str, int]:
    memberships: dict[int, int] = {}
    for ticket_index, ticket in enumerate(tickets):
        for number in ticket["numbers"]:
            memberships[int(number)] = memberships.get(int(number), 0) | (
                1 << ticket_index
            )
    return {
        str(mask): count
        for mask, count in sorted(Counter(memberships.values()).items())
    }


def _structure_signature(tickets: list[dict]) -> dict:
    pairwise = []
    for left in range(SELECTED_TICKETS):
        for right in range(left + 1, SELECTED_TICKETS):
            pairwise.append(
                len(
                    set(tickets[left]["numbers"])
                    & set(tickets[right]["numbers"])
                )
            )
    return {
        "main_union_size": len(
            {
                number
                for ticket in tickets
                for number in ticket["numbers"]
            }
        ),
        "membership_histogram": _membership_histogram(tickets),
        "pairwise_main_overlaps": pairwise,
        "distinct_special_values": len(
            {ticket["special"] for ticket in tickets}
        ),
    }


def _portfolio_row(
    portfolio_id: str,
    tickets: list[dict],
    ranked_prefix: list[int],
) -> dict:
    guarded = portfolio_id == GUARDED_PROFIT
    return {
        "portfolio_id": portfolio_id,
        "objective": (
            "在至少四主號全域最大守門下，提高五注嚴格獲利率"
            if guarded
            else "不設重疊守門，最大化五注歷史最低實領壓力嚴格獲利率"
        ),
        "proof": deepcopy(
            GUARDED_PROOF if guarded else UNCONSTRAINED_PROOF
        ),
        "ranked_main_prefix": list(ranked_prefix),
        "tickets": tickets,
        "selection_hash": canonical_hash(
            {"game": SUPER, "tickets": tickets}
        ),
        "structure": _structure_signature(tickets),
        "exact_metrics": deepcopy(EXACT_METRICS[portfolio_id]),
    }


def validate_common_special_candidate(candidate: dict) -> dict:
    """驗證正式機制研究凍結的共同第二區 forward 候選。"""
    if not isinstance(candidate, dict):
        raise ValueError("共同第二區 shadow 候選格式不符")
    expected_keys = {
        "experiment_id",
        "source_experiment_id",
        "game",
        "fitted_through",
        "selected_special",
        "source_candidate",
        "promotion_eligible",
        "use",
        "guarded_profit_proof",
        "unconstrained_profit_proof",
        "candidate_hash",
    }
    payload = {
        key: deepcopy(value)
        for key, value in candidate.items()
        if key != "candidate_hash"
    }
    if (
        set(candidate) != expected_keys
        or candidate.get("experiment_id")
        != COMMON_SPECIAL_SHADOW_EXPERIMENT_ID
        or candidate.get("source_experiment_id")
        != COMMON_SPECIAL_SOURCE_EXPERIMENT_ID
        or candidate.get("game") != SUPER
        or candidate.get("fitted_through")
        != COMMON_SPECIAL_FITTED_THROUGH
        or candidate.get("source_candidate")
        != "development_top_one_special"
        or candidate.get("promotion_eligible") is not False
        or candidate.get("use") != "future_forward_shadow_only"
        or candidate.get("guarded_profit_proof") != GUARDED_PROOF
        or candidate.get("unconstrained_profit_proof")
        != UNCONSTRAINED_PROOF
        or candidate.get("selected_special") != COMMON_SPECIAL_SELECTED
        or candidate.get("candidate_hash")
        != COMMON_SPECIAL_CANDIDATE_HASH
        or candidate.get("candidate_hash") != canonical_hash(payload)
    ):
        raise ValueError("共同第二區 shadow 候選證明不符")
    return deepcopy(candidate)


def _common_special_shadow(
    *,
    candidate: dict,
    ranking: list[int],
    baseline_special: int,
) -> dict:
    verified = validate_common_special_candidate(candidate)
    selected_special = verified["selected_special"]
    guarded_tickets = _tickets_from_memberships(
        ranking,
        GUARDED_SHARED_MASKS,
        special=selected_special,
        source_agent=(
            "development_common_special_guarded_profit_synthesizer"
        ),
        source_prefix="common-special-guarded-profit",
        singleton_count=2,
    )
    unconstrained_tickets = _tickets_from_memberships(
        ranking,
        UNCONSTRAINED_MASKS,
        special=selected_special,
        source_agent=(
            "development_common_special_unconstrained_profit_synthesizer"
        ),
        source_prefix="common-special-unconstrained-profit",
    )
    payload = {
        "experiment_id": COMMON_SPECIAL_SHADOW_EXPERIMENT_ID,
        "candidate": verified,
        "candidate_hash": verified["candidate_hash"],
        "use": "future_forward_simulation_shadow_only",
        "promotion_eligible": False,
        "baseline_special": int(baseline_special),
        "selected_special": selected_special,
        "portfolios": {
            GUARDED_PROFIT: _portfolio_row(
                GUARDED_PROFIT, guarded_tickets, ranking[:20]
            ),
            UNCONSTRAINED_PROFIT: _portfolio_row(
                UNCONSTRAINED_PROFIT,
                unconstrained_tickets,
                ranking[:10],
            ),
        },
        "honesty_note": (
            "只把同一份開獎前主號排序的共同第二區改成 development "
            "top-1；不改主號結構、不回填已揭曉期數。"
        ),
    }
    return {
        **payload,
        "shadow_hash": canonical_hash(payload),
    }


def build_profit_portfolio_shadows(
    *,
    source_decision_hash: str,
    support_evidence_hash: str,
    ranked_main_numbers: list[int],
    selected_special: int,
    common_special_candidate: dict | None = None,
) -> dict:
    """用同一份開獎前辯論排序建立兩個獲利目標五注 shadow。"""
    if not isinstance(source_decision_hash, str) or len(
        source_decision_hash
    ) != 64:
        raise ValueError("獲利 shadow 缺少有效 decision hash")
    if not isinstance(support_evidence_hash, str) or len(
        support_evidence_hash
    ) != 64:
        raise ValueError("獲利 shadow 缺少有效辯論支持 hash")
    ranking = [int(number) for number in ranked_main_numbers]
    if len(ranking) != 30 or len(set(ranking)) != 30:
        raise ValueError("獲利 shadow 必須接收 coverage 的 30 號完整排序")

    guarded_tickets = _tickets_from_memberships(
        ranking,
        GUARDED_SHARED_MASKS,
        special=selected_special,
        source_agent="consensus_guarded_profit_synthesizer",
        source_prefix="guarded-profit",
        singleton_count=2,
    )
    unconstrained_tickets = _tickets_from_memberships(
        ranking,
        UNCONSTRAINED_MASKS,
        special=selected_special,
        source_agent="consensus_unconstrained_profit_synthesizer",
        source_prefix="unconstrained-profit",
    )
    payload = {
        "experiment_id": EXPERIMENT_ID,
        "game": SUPER,
        "use": "future_forward_simulation_shadow_only",
        "promotion_eligible": False,
        "source_decision_hash": source_decision_hash,
        "support_evidence_hash": support_evidence_hash,
        "ranked_main_numbers": ranking,
        "selected_special": int(selected_special),
        "five_ticket_cost_ntd": FIVE_TICKET_COST_NTD,
        "empirical_floor_snapshot": deepcopy(EMPIRICAL_FLOOR_SNAPSHOT),
        "portfolios": {
            GUARDED_PROFIT: _portfolio_row(
                GUARDED_PROFIT, guarded_tickets, ranking[:20]
            ),
            UNCONSTRAINED_PROFIT: _portfolio_row(
                UNCONSTRAINED_PROFIT,
                unconstrained_tickets,
                ranking[:10],
            ),
        },
        "honesty_note": (
            "號碼標籤來自開獎前 Agent 辯論排序；結構提高的是固定五注"
            "事件機率，不代表某個公平開獎號碼本身較可能出現。"
        ),
    }
    if common_special_candidate is not None:
        payload["common_special_shadow"] = _common_special_shadow(
            candidate=common_special_candidate,
            ranking=ranking,
            baseline_special=int(selected_special),
        )
    return {
        **payload,
        "shadow_hash": canonical_hash(payload),
    }


def verify_profit_portfolio_shadows(
    shadow: dict,
    *,
    expected_source_decision_hash: str,
    expected_support_evidence_hash: str,
    expected_ranked_main_numbers: list[int],
    expected_selected_special: int,
    expected_common_special_candidate: dict | None = None,
) -> dict:
    """重建整個 shadow，拒絕即使重算外層 hash 的語意竄改。"""
    if not isinstance(shadow, dict):
        raise ValueError("獲利 forward shadow 格式不符")
    expected = build_profit_portfolio_shadows(
        source_decision_hash=expected_source_decision_hash,
        support_evidence_hash=expected_support_evidence_hash,
        ranked_main_numbers=expected_ranked_main_numbers,
        selected_special=expected_selected_special,
        common_special_candidate=expected_common_special_candidate,
    )
    if shadow != expected:
        raise ValueError("獲利 forward shadow 結構、證明或排序來源不符")
    return deepcopy(expected)
