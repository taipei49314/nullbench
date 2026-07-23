"""下一期終局裁判的前向 A/B 純模擬。

每個新目標期在開獎前同時凍結四個固定五注臂；歷史三臂登記仍可驗證：

- ``rule_five``：15 組提案經可重現規則裁決選出的五注。
- ``qwen_five``：同一批提案經本機 qwen3:8b 終局裁判改選的五注。
- ``random_five``：同一期固定種子的均勻隨機五注。
- ``coverage_five``：以同一批 15 組提案的辯論支持排序合成 30 個互斥
  主號；威力彩另用五個互異第二區，提高完整任一獎級聯集機率。

威力彩 coverage metadata 可另凍結相同主號、只替換第二區的配對子影子；
它不新增正式臂，也不替換 coverage 號碼。

coverage v3 另以同一期辯論支持排序建立 guarded／unconstrained 獲利
子影子；兩者只改五注重疊結構、只對新登記生效，也不新增正式臂。

coverage v4 在相同兩種主號結構內，另把 development 凍結的共同第二區
與當期辯論 baseline 作未來配對；不通過歷史門檻，因此仍只作 shadow。

coverage v5 另凍結逐期 proper-score 縮權後的機率 stacking 五注，與正式
coverage 作未來配對；歷史只初始化權重，不作升級證據。

coverage v6 再把當期 stacking 的完整主號／第二區機率質量於開獎前封存；
揭曉後用 log loss 對均勻基準計算 regret，讓號碼標籤與票券結構分層回饋。

coverage v7 同時封存 null-safe 安全分布、未開牌 stacking 證據分布與
prior e-process state；揭曉只更新下一期 gate，合法六號子集分數不得回填。

開獎後只允許結算已存在的 preregistration；缺少開獎前登記的期數不得回填。
帳本位於 ``simulation/forward/``，與正式 ``records/`` 完全隔離。
"""
from __future__ import annotations

import json
import math
import os
import random
import statistics
from collections import Counter
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from .agent_loop import AGENT_IDS, _adjudicate, canonical_hash
from .decision_observatory import (
    OPS_EXPERIMENT_ID,
    build_observatory,
)
from .forward_feedback import (
    FEEDBACK_EXPERIMENT_ID,
    build_feedback_context,
    build_feedback_context_from_settlements,
    build_postmortem,
    verify_feedback_context,
    verify_postmortem,
)
from .games import (
    GAME_NAMES,
    LOTTO649,
    PICK_N,
    POOL,
    SPECIAL_POOL,
    SUPER,
    Draw,
    match_tier,
    prize_value,
    validate_pick,
)
from .ledger import Ledger, TAIPEI, now_iso
from .seeds import seed_int
from research.max_coverage import (
    EXPERIMENT_ID as MAX_COVERAGE_RESEARCH_EXPERIMENT_ID,
    select_consensus_disjoint_portfolio,
)
from research.mechanism_signal import historical_special_portfolio
from research.portfolio_coverage import (
    EXPERIMENT_ID as COVERAGE_RESEARCH_EXPERIMENT_ID_V1,
    portfolio_structure,
)
from research.profit_portfolio_forward import (
    COMMON_SPECIAL_SHADOW_EXPERIMENT_ID,
    EMPIRICAL_FLOOR_NTD,
    EXPERIMENT_ID as PROFIT_SHADOW_EXPERIMENT_ID,
    FIVE_TICKET_COST_NTD,
    PORTFOLIO_IDS as PROFIT_PORTFOLIO_IDS,
    build_profit_portfolio_shadows,
    validate_common_special_candidate,
    verify_profit_portfolio_shadows,
)
from research.probability_stacking import (
    FORWARD_EXPERIMENT_ID as PROBABILITY_STACKING_EXPERIMENT_ID,
    LOOK_LOWER_TAIL_ALPHA as PROBABILITY_STACKING_LOOK_ALPHA,
    MONITORING_CHECKPOINTS as PROBABILITY_STACKING_CHECKPOINTS,
    PROTOCOL_HASH as PROBABILITY_STACKING_PROTOCOL_HASH,
    SCORE_CAPSULE_EXPERIMENT_ID,
    portfolio_from_distribution,
    select_probability_stacked_portfolio,
    settle_probability_score_capsule,
    validate_forward_candidate as validate_probability_stacking_candidate,
    validate_probability_score_capsule,
)
from research.null_safe_probability import (
    FORWARD_EXPERIMENT_ID as NULL_SAFE_PROBABILITY_EXPERIMENT_ID,
    PROTOCOL_HASH as NULL_SAFE_PROBABILITY_PROTOCOL_HASH,
    SCORE_CAPSULE_EXPERIMENT_ID as NULL_SAFE_SCORE_CAPSULE_EXPERIMENT_ID,
    build_null_safe_score_capsule,
    forecast_null_safe_distributions,
    select_null_safe_portfolio,
    settle_null_safe_score_capsule,
    validate_forward_candidate as validate_null_safe_probability_candidate,
    validate_forward_state_artifact as validate_null_safe_probability_forward_state,
    validate_null_safe_score_capsule,
    verify_null_safe_score_result,
)
from research.structural_optimum import structural_proof_reference


FORWARD_EXPERIMENT_ID = "final-judge-forward-v1"
ARM_RULE = "rule_five"
ARM_QWEN = "qwen_five"
ARM_RANDOM = "random_five"
ARM_COVERAGE = "coverage_five"
LEGACY_ARMS = (ARM_RULE, ARM_QWEN, ARM_RANDOM)
ARMS = LEGACY_ARMS + (ARM_COVERAGE,)
COVERAGE_FORWARD_EXPERIMENT_ID_V1 = "portfolio-coverage-forward-v1"
COVERAGE_FORWARD_EXPERIMENT_ID_V2 = (
    "max-coverage-consensus-forward-v2"
)
COVERAGE_FORWARD_EXPERIMENT_ID = (
    "profit-portfolio-consensus-forward-v3"
)
COVERAGE_FORWARD_EXPERIMENT_ID_V4 = (
    "profit-common-special-shadow-forward-v4"
)
COVERAGE_FORWARD_EXPERIMENT_ID_V5 = (
    "probability-stacking-shadow-forward-v5"
)
COVERAGE_FORWARD_EXPERIMENT_ID_V6 = (
    "probability-score-feedback-forward-v6"
)
COVERAGE_FORWARD_EXPERIMENT_ID_V7 = (
    "null-safe-probability-shadow-forward-v7"
)
COVERAGE_FORWARD_EXPERIMENT_IDS = (
    COVERAGE_FORWARD_EXPERIMENT_ID_V1,
    COVERAGE_FORWARD_EXPERIMENT_ID_V2,
    COVERAGE_FORWARD_EXPERIMENT_ID,
    COVERAGE_FORWARD_EXPERIMENT_ID_V4,
    COVERAGE_FORWARD_EXPERIMENT_ID_V5,
    COVERAGE_FORWARD_EXPERIMENT_ID_V6,
    COVERAGE_FORWARD_EXPERIMENT_ID_V7,
)
SELECTED_TICKETS = 5
DRAW_CUTOFF_TIME = "20:30:00"
MIN_PAIRED_DRAWS_PER_GAME = 52
BOOTSTRAP_BLOCK_DRAWS = 13
BOOTSTRAP_SAMPLES = 2_000
SPECIAL_SHADOW_EXPERIMENT_ID = "special-frequency-forward-shadow-v1"
MONITORING_CHECKPOINTS = (52, 104, 208, 416, 832)
MONITORING_PROTOCOL_ID = "forward-sequential-monitoring-v2"
MONITORING_FAMILY_LOWER_TAIL_ALPHA = 0.025
MONITORING_LOOK_LOWER_TAIL_ALPHA = (
    MONITORING_FAMILY_LOWER_TAIL_ALPHA
    / len(MONITORING_CHECKPOINTS)
)
PROBABILITY_STACKING_MONITORING_PROTOCOL_ID = (
    "probability-stacking-sequential-monitor-v1"
)
PROBABILITY_SCORE_MONITORING_PROTOCOL_ID = (
    "probability-score-sequential-monitor-v1"
)
PROBABILITY_STACKING_PROMOTION_GATE_ID = (
    "probability-stacking-promotion-gate-v2"
)
if (
    tuple(PROBABILITY_STACKING_CHECKPOINTS)
    != MONITORING_CHECKPOINTS
    or PROBABILITY_STACKING_LOOK_ALPHA
    != MONITORING_LOOK_LOWER_TAIL_ALPHA
):
    raise RuntimeError("機率 stacking 與前向監控 checkpoint 契約不一致")


def _event_content(event: dict) -> dict:
    content = event.get("content")
    if not isinstance(content, dict):
        raise ValueError("前向帳本事件缺少 content")
    if event.get("content_hash") != canonical_hash(content):
        raise ValueError("前向帳本事件 content_hash 不符")
    return content


def _append_content(ledger: Ledger, event_type: str, content: dict) -> dict:
    return ledger.append(
        event_type,
        {
            "content": content,
            "content_hash": canonical_hash(content),
        },
    )


def _target_key(game: str, target: dict) -> tuple[str, str, int]:
    return game, str(target["date"]), int(target["period"])


def _deadline(target: dict) -> str:
    return f"{target['date']}T{DRAW_CUTOFF_TIME}+08:00"


def _is_late(registered_at: str, target: dict) -> bool:
    return datetime.fromisoformat(registered_at) >= datetime.fromisoformat(
        _deadline(target)
    )


def _normalize_ticket(ticket: dict, slot: int) -> dict:
    return {
        "slot": slot,
        "source_agent": ticket.get("source_agent"),
        "source_proposal": ticket.get("source_proposal"),
        "numbers": [int(number) for number in ticket["numbers"]],
        "special": (
            int(ticket["special"])
            if ticket.get("special") is not None
            else None
        ),
    }


def _validate_tickets(game: str, tickets: list[dict]) -> None:
    if len(tickets) != SELECTED_TICKETS:
        raise ValueError("前向實驗每個臂必須剛好五注")
    numbers_seen = set()
    for slot, ticket in enumerate(tickets, 1):
        if int(ticket["slot"]) != slot:
            raise ValueError("前向實驗票券 slot 不連續")
        validate_pick(game, ticket["numbers"], ticket["special"])
        number_key = tuple(ticket["numbers"])
        if number_key in numbers_seen:
            raise ValueError("前向實驗同一臂出現重複主號組合")
        numbers_seen.add(number_key)


def _selection_hash(game: str, tickets: list[dict]) -> str:
    return canonical_hash({"game": game, "tickets": tickets})


def _validated_mechanism_candidate(
    candidate: dict | None,
) -> dict | None:
    if candidate is None:
        return None
    if not isinstance(candidate, dict):
        raise ValueError("第二區 forward shadow 候選格式不符")
    payload = {
        key: deepcopy(value)
        for key, value in candidate.items()
        if key != "candidate_hash"
    }
    if (
        candidate.get("experiment_id")
        != SPECIAL_SHADOW_EXPERIMENT_ID
        or candidate.get("source_experiment_id")
        != "draw-mechanism-signal-audit-v1"
        or candidate.get("game") != SUPER
        or candidate.get("promotion_eligible") is not False
        or candidate.get("use") != "future_forward_shadow_only"
        or candidate.get("structural_optimum_proof")
        != structural_proof_reference()
        or candidate.get("candidate_hash")
        != canonical_hash(payload)
        or not isinstance(candidate.get("selected_specials"), list)
        or len(candidate["selected_specials"]) != SELECTED_TICKETS
        or len(set(candidate["selected_specials"]))
        != SELECTED_TICKETS
        or any(
            not isinstance(value, int)
            or not 1 <= value <= SPECIAL_POOL[SUPER]
            for value in candidate["selected_specials"]
        )
    ):
        raise ValueError("第二區 forward shadow 候選證明不符")
    return deepcopy(candidate)


def _special_shadow_registration(
    decision: dict,
    coverage_tickets: list[dict],
    candidate: dict | None,
) -> dict | None:
    if decision["game"] != SUPER or candidate is None:
        return None
    verified = _validated_mechanism_candidate(candidate)
    if verified.get("fitted_through", "") >= decision["target"]["date"]:
        raise ValueError("第二區 shadow 候選含目標期或未來資料")
    tickets = [
        _normalize_ticket(ticket, slot)
        for slot, ticket in enumerate(
            historical_special_portfolio(
                decision,
                verified["selected_specials"],
            ),
            1,
        )
    ]
    _validate_tickets(SUPER, tickets)
    if any(
        ticket["numbers"] != control["numbers"]
        for ticket, control in zip(tickets, coverage_tickets)
    ):
        raise RuntimeError("第二區 shadow 不得改 coverage 主號")
    if portfolio_structure(SUPER, tickets) != portfolio_structure(
        SUPER, coverage_tickets
    ):
        raise RuntimeError("第二區 shadow 不得改精確結構機率")
    return {
        "experiment_id": SPECIAL_SHADOW_EXPERIMENT_ID,
        "candidate": verified,
        "candidate_hash": verified["candidate_hash"],
        "tickets": tickets,
        "selection_hash": _selection_hash(SUPER, tickets),
        "theoretical_structural_probability_unchanged": True,
        "honesty_note": (
            "只作未來配對 shadow；不替換 coverage_five，"
            "不回填已揭曉期數。"
        ),
    }


def _validate_probability_stacking_shadow(
    shadow: dict,
    *,
    game: str,
    target: dict,
    source_decision_hash: str,
) -> dict:
    if not isinstance(shadow, dict):
        raise ValueError("機率 stacking shadow 格式不符")
    expected_keys = {
        "experiment_id",
        "candidate_hash",
        "protocol_hash",
        "source_decision_hash",
        "candidate",
        "tickets",
        "selection_hash",
        "support_evidence_hash",
        "selected_main_numbers",
        "selected_specials",
        "ticket_main_probability_mass",
        "structure",
        "use",
    }
    has_score_capsule = "score_capsule" in shadow
    if has_score_capsule:
        expected_keys.add("score_capsule")
    if set(shadow) != expected_keys:
        raise ValueError("機率 stacking shadow 欄位不符")
    candidate = validate_probability_stacking_candidate(
        shadow["candidate"]
    )
    tickets = shadow["tickets"]
    _validate_tickets(game, tickets)
    structure = portfolio_structure(game, tickets)
    selected_main_numbers = shadow["selected_main_numbers"]
    selected_specials = shadow["selected_specials"]
    ticket_masses = shadow["ticket_main_probability_mass"]
    if (
        shadow["experiment_id"]
        != PROBABILITY_STACKING_EXPERIMENT_ID
        or shadow["candidate_hash"] != candidate["candidate_hash"]
        or shadow["protocol_hash"]
        != PROBABILITY_STACKING_PROTOCOL_HASH
        or shadow["source_decision_hash"] != source_decision_hash
        or shadow["selection_hash"] != _selection_hash(game, tickets)
        or shadow["structure"] != structure
        or shadow["use"] != "future_forward_shadow_only"
        or candidate["fitted_through"][game] >= target["date"]
        or not isinstance(selected_main_numbers, list)
        or len(selected_main_numbers) != 30
        or len(set(selected_main_numbers)) != 30
        or sorted(selected_main_numbers)
        != sorted(
            number
            for ticket in tickets
            for number in ticket["numbers"]
        )
        or not isinstance(ticket_masses, list)
        or len(ticket_masses) != SELECTED_TICKETS
        or any(
            not math.isfinite(float(value)) or float(value) <= 0
            for value in ticket_masses
        )
        or structure["main_union_size"] != 30
        or structure["maximum_pairwise_main_overlap"] != 0
    ):
        raise ValueError("機率 stacking shadow 證明不符")
    if game == SUPER:
        if (
            not isinstance(selected_specials, list)
            or len(selected_specials) != SELECTED_TICKETS
            or len(set(selected_specials)) != SELECTED_TICKETS
            or sorted(selected_specials)
            != sorted(ticket["special"] for ticket in tickets)
        ):
            raise ValueError("機率 stacking 第二區結構不符")
    elif game == LOTTO649:
        if selected_specials is not None:
            raise ValueError("大樂透機率 stacking 不得有第二區")
    else:
        raise ValueError("機率 stacking 遊戲不符")
    score_capsule = None
    if has_score_capsule:
        score_capsule = validate_probability_score_capsule(
            shadow["score_capsule"],
            game=game,
            target=target,
            candidate_hash=candidate["candidate_hash"],
            source_decision_hash=source_decision_hash,
        )
        main_distribution = {
            number: float(
                score_capsule["main_probability_mass"][number - 1]
            )
            for number in range(1, POOL[game] + 1)
        }
        special_distribution = (
            {
                number: float(
                    score_capsule["special_probability_mass"][
                        number - 1
                    ]
                )
                for number in range(
                    1, SPECIAL_POOL[SUPER] + 1
                )
            }
            if game == SUPER
            else None
        )
        expected_tickets, expected_selection = (
            portfolio_from_distribution(
                game,
                main_distribution,
                special_distribution,
            )
        )
        normalized_expected_tickets = [
            _normalize_ticket(ticket, slot)
            for slot, ticket in enumerate(expected_tickets, 1)
        ]
        if (
            tickets != normalized_expected_tickets
            or selected_main_numbers
            != expected_selection["selected_main_numbers"]
            or selected_specials
            != expected_selection["selected_specials"]
            or any(
                not math.isclose(
                    float(actual),
                    float(expected),
                    rel_tol=0.0,
                    abs_tol=1e-15,
                )
                for actual, expected in zip(
                    ticket_masses,
                    expected_selection[
                        "ticket_main_probability_mass"
                    ],
                )
            )
            or structure != expected_selection["structure"]
        ):
            raise ValueError(
                "機率評分膠囊與 stacking 票券重建不符"
            )
    evidence = {
        "candidate_hash": candidate["candidate_hash"],
        "protocol_hash": PROBABILITY_STACKING_PROTOCOL_HASH,
        "game": game,
        "target": target,
        "source_decision_hash": source_decision_hash,
        "selected_main_numbers": selected_main_numbers,
        "selected_specials": selected_specials,
        "ticket_main_probability_mass": ticket_masses,
        "structure": structure,
    }
    if score_capsule is not None:
        evidence["score_capsule_hash"] = score_capsule[
            "capsule_hash"
        ]
    if shadow["support_evidence_hash"] != canonical_hash(evidence):
        raise ValueError("機率 stacking 支持證據雜湊不符")
    return deepcopy(shadow)


def _probability_stacking_shadow_registration(
    decision: dict,
    candidate: dict,
) -> dict:
    game = decision["game"]
    target = {
        "date": decision["target"]["date"],
        "period": int(decision["target"]["period"]),
    }
    tickets, selection = select_probability_stacked_portfolio(
        game,
        decision,
        candidate,
    )
    tickets = [
        _normalize_ticket(ticket, slot)
        for slot, ticket in enumerate(tickets, 1)
    ]
    shadow = {
        "experiment_id": selection["experiment_id"],
        "candidate_hash": selection["candidate_hash"],
        "protocol_hash": selection["protocol_hash"],
        "source_decision_hash": decision["decision_hash"],
        "candidate": deepcopy(candidate),
        "tickets": tickets,
        "selection_hash": _selection_hash(game, tickets),
        "support_evidence_hash": selection[
            "support_evidence_hash"
        ],
        "selected_main_numbers": selection[
            "selected_main_numbers"
        ],
        "selected_specials": selection["selected_specials"],
        "ticket_main_probability_mass": selection[
            "ticket_main_probability_mass"
        ],
        "structure": selection["structure"],
        "score_capsule": selection["score_capsule"],
        "use": selection["use"],
    }
    return _validate_probability_stacking_shadow(
        shadow,
        game=game,
        target=target,
        source_decision_hash=decision["decision_hash"],
    )


def _null_safe_expected_tickets(
    *,
    game: str,
    coverage_tickets: list[dict],
    main_distribution: dict[int, float],
    special_distribution: dict[int, float] | None,
    main_gate_active: bool,
    special_gate_active: bool | None,
) -> list[dict]:
    if main_gate_active:
        tickets, _ = portfolio_from_distribution(
            game,
            main_distribution,
            special_distribution,
        )
    else:
        tickets = deepcopy(coverage_tickets)
    if game == SUPER:
        if special_gate_active:
            specials = sorted(
                special_distribution,
                key=lambda number: (
                    -special_distribution[number],
                    number,
                ),
            )[:SELECTED_TICKETS]
            masses = [
                math.fsum(
                    main_distribution[number]
                    for number in ticket["numbers"]
                )
                for ticket in tickets
            ]
            bin_order = sorted(
                range(SELECTED_TICKETS),
                key=lambda index: (-masses[index], index),
            )
            for rank, index in enumerate(bin_order):
                tickets[index]["special"] = specials[rank]
        else:
            baseline_specials = {
                int(ticket["slot"]): int(ticket["special"])
                for ticket in coverage_tickets
            }
            for ticket in tickets:
                ticket["special"] = baseline_specials[
                    int(ticket["slot"])
                ]
    normalized = []
    for slot, ticket in enumerate(tickets, 1):
        normalized.append(
            {
                "slot": slot,
                "source_agent": (
                    "null_safe_probability_synthesizer"
                ),
                "source_proposal": (
                    f"null-safe-probability:{slot}"
                ),
                "numbers": sorted(
                    int(number) for number in ticket["numbers"]
                ),
                "special": (
                    int(ticket["special"])
                    if ticket.get("special") is not None
                    else None
                ),
            }
        )
    return normalized


def _validate_null_safe_probability_shadow(
    shadow: dict,
    *,
    game: str,
    target: dict,
    source_decision_hash: str,
    coverage_tickets: list[dict],
    baseline_support_evidence_hash: str,
) -> dict:
    expected_fields = {
        "schema_version",
        "experiment_id",
        "candidate_hash",
        "protocol_hash",
        "source_decision_hash",
        "candidate",
        "tickets",
        "selection_hash",
        "support_evidence_hash",
        "main_gate_active",
        "special_gate_active",
        "ticket_label_source",
        "baseline_support_evidence_hash",
        "selected_main_numbers",
        "selected_specials",
        "ticket_main_probability_mass",
        "structure",
        "score_capsule",
        "use",
    }
    if not isinstance(shadow, dict) or set(shadow) != expected_fields:
        raise ValueError("null-safe probability shadow 欄位不符")
    candidate = validate_null_safe_probability_candidate(
        shadow["candidate"]
    )
    normalized_target = {
        "date": str(target["date"]),
        "period": int(target["period"]),
    }
    tickets = shadow["tickets"]
    _validate_tickets(game, tickets)
    structure = portfolio_structure(game, tickets)
    if (
        shadow.get("schema_version") != "1"
        or shadow.get("experiment_id")
        != NULL_SAFE_PROBABILITY_EXPERIMENT_ID
        or shadow.get("candidate_hash")
        != candidate["candidate_hash"]
        or shadow.get("protocol_hash")
        != NULL_SAFE_PROBABILITY_PROTOCOL_HASH
        or shadow.get("source_decision_hash")
        != source_decision_hash
        or shadow.get("selection_hash")
        != _selection_hash(game, tickets)
        or shadow.get("structure") != structure
        or shadow.get("use") != "future_forward_shadow_only"
        or candidate["fitted_through"][game]
        >= normalized_target["date"]
        or baseline_support_evidence_hash
        != shadow.get("baseline_support_evidence_hash")
        or not isinstance(baseline_support_evidence_hash, str)
        or len(baseline_support_evidence_hash) != 64
        or structure["main_union_size"] != 30
        or structure["maximum_pairwise_main_overlap"] != 0
    ):
        raise ValueError("null-safe probability shadow 證明不符")
    capsule = validate_null_safe_score_capsule(
        shadow["score_capsule"],
        game=game,
        target=normalized_target,
        candidate_hash=candidate["candidate_hash"],
        source_decision_hash=source_decision_hash,
    )
    model = candidate["models"][game]
    if (
        capsule["main_prior_e_process"]
        != model["main_e_process"]
        or capsule["main_gate_active"]
        is not model["main_gate_active"]
        or (
            game == SUPER
            and (
                capsule["special_prior_e_process"]
                != model["special_e_process"]
                or capsule["special_gate_active"]
                is not model["special_gate_active"]
            )
        )
    ):
        raise ValueError(
            "null-safe score capsule 與候選 prior state 不符"
        )
    main_distribution = {
        number: float(
            capsule["safe_main_probability_mass"][number - 1]
        )
        for number in range(1, POOL[game] + 1)
    }
    special_distribution = (
        {
            number: float(
                capsule["safe_special_probability_mass"][
                    number - 1
                ]
            )
            for number in range(1, SPECIAL_POOL[SUPER] + 1)
        }
        if game == SUPER
        else None
    )
    expected_tickets = _null_safe_expected_tickets(
        game=game,
        coverage_tickets=coverage_tickets,
        main_distribution=main_distribution,
        special_distribution=special_distribution,
        main_gate_active=capsule["main_gate_active"],
        special_gate_active=capsule["special_gate_active"],
    )
    expected_main = [
        number
        for ticket in expected_tickets
        for number in ticket["numbers"]
    ]
    expected_specials = (
        [int(ticket["special"]) for ticket in expected_tickets]
        if game == SUPER
        else None
    )
    expected_ticket_masses = [
        math.fsum(
            main_distribution[number]
            for number in ticket["numbers"]
        )
        for ticket in expected_tickets
    ]
    if (
        tickets != expected_tickets
        or shadow.get("main_gate_active")
        is not capsule["main_gate_active"]
        or shadow.get("special_gate_active")
        is not capsule["special_gate_active"]
        or shadow.get("ticket_label_source")
        != (
            "stacking_probability"
            if capsule["main_gate_active"]
            else "consensus_coverage"
        )
        or shadow.get("selected_main_numbers") != expected_main
        or shadow.get("selected_specials") != expected_specials
        or not isinstance(
            shadow.get("ticket_main_probability_mass"), list
        )
        or len(shadow["ticket_main_probability_mass"])
        != SELECTED_TICKETS
        or any(
            not math.isclose(
                float(actual),
                float(expected),
                rel_tol=0.0,
                abs_tol=1e-15,
            )
            for actual, expected in zip(
                shadow["ticket_main_probability_mass"],
                expected_ticket_masses,
            )
        )
    ):
        raise ValueError(
            "null-safe probability shadow 票券或 gate 不符"
        )
    evidence = {
        "candidate_hash": candidate["candidate_hash"],
        "protocol_hash": NULL_SAFE_PROBABILITY_PROTOCOL_HASH,
        "game": game,
        "target": normalized_target,
        "source_decision_hash": source_decision_hash,
        "main_gate_active": capsule["main_gate_active"],
        "special_gate_active": capsule["special_gate_active"],
        "ticket_label_source": shadow["ticket_label_source"],
        "baseline_support_evidence_hash": (
            baseline_support_evidence_hash
        ),
        "selected_main_numbers": expected_main,
        "selected_specials": expected_specials,
        "ticket_main_probability_mass": (
            shadow["ticket_main_probability_mass"]
        ),
        "structure": structure,
        "main_probability_mass": capsule[
            "safe_main_probability_mass"
        ],
        "special_probability_mass": capsule[
            "safe_special_probability_mass"
        ],
    }
    if shadow.get("support_evidence_hash") != canonical_hash(evidence):
        raise ValueError(
            "null-safe probability 支持證據雜湊不符"
        )
    return deepcopy(shadow)


def _null_safe_probability_shadow_registration(
    decision: dict,
    coverage_tickets: list[dict],
    baseline_support_evidence_hash: str,
    candidate: dict,
) -> dict:
    game = decision["game"]
    target = {
        "date": str(decision["target"]["date"]),
        "period": int(decision["target"]["period"]),
    }
    verified = validate_null_safe_probability_candidate(candidate)
    forecast = forecast_null_safe_distributions(
        game,
        decision,
        verified,
    )
    tickets, selection = select_null_safe_portfolio(
        game,
        decision,
        verified,
    )
    tickets = [
        _normalize_ticket(ticket, slot)
        for slot, ticket in enumerate(tickets, 1)
    ]
    model = verified["models"][game]
    capsule = build_null_safe_score_capsule(
        game=game,
        target=target,
        candidate_hash=verified["candidate_hash"],
        source_decision_hash=decision["decision_hash"],
        safe_main_distribution=forecast["main_distribution"],
        evidence_main_distribution=forecast[
            "main_mixture_distribution"
        ],
        main_e_process=model["main_e_process"],
        safe_special_distribution=forecast[
            "special_distribution"
        ],
        evidence_special_distribution=forecast[
            "special_mixture_distribution"
        ],
        special_e_process=(
            model["special_e_process"]
            if game == SUPER
            else None
        ),
    )
    shadow = {
        "schema_version": "1",
        "experiment_id": selection["experiment_id"],
        "candidate_hash": selection["candidate_hash"],
        "protocol_hash": selection["protocol_hash"],
        "source_decision_hash": decision["decision_hash"],
        "candidate": deepcopy(verified),
        "tickets": tickets,
        "selection_hash": _selection_hash(game, tickets),
        "support_evidence_hash": selection[
            "support_evidence_hash"
        ],
        "main_gate_active": selection["main_gate_active"],
        "special_gate_active": selection[
            "special_gate_active"
        ],
        "ticket_label_source": selection[
            "ticket_label_source"
        ],
        "baseline_support_evidence_hash": selection[
            "baseline_support_evidence_hash"
        ],
        "selected_main_numbers": selection[
            "selected_main_numbers"
        ],
        "selected_specials": selection["selected_specials"],
        "ticket_main_probability_mass": selection[
            "ticket_main_probability_mass"
        ],
        "structure": selection["structure"],
        "score_capsule": capsule,
        "use": selection["use"],
    }
    if (
        shadow["baseline_support_evidence_hash"]
        != baseline_support_evidence_hash
    ):
        raise ValueError(
            "null-safe probability coverage 支持來源不符"
        )
    return _validate_null_safe_probability_shadow(
        shadow,
        game=game,
        target=target,
        source_decision_hash=decision["decision_hash"],
        coverage_tickets=coverage_tickets,
        baseline_support_evidence_hash=(
            baseline_support_evidence_hash
        ),
    )


def _profit_shadow_selected_special(
    coverage_tickets: list[dict],
    ticket_debate_support: list[float],
) -> int:
    if (
        len(coverage_tickets) != SELECTED_TICKETS
        or len(ticket_debate_support) != SELECTED_TICKETS
    ):
        raise ValueError("獲利 shadow 缺少五注辯論支持值")
    top_ticket_index = min(
        range(SELECTED_TICKETS),
        key=lambda index: (
            -float(ticket_debate_support[index]),
            index,
        ),
    )
    special = coverage_tickets[top_ticket_index].get("special")
    if not isinstance(special, int):
        raise ValueError("獲利 shadow 缺少辯論最高支持第二區號碼")
    return special


def _registered_arms(content: dict) -> tuple[str, ...]:
    arms = content.get("arms")
    if not isinstance(arms, dict):
        raise ValueError("前向登記 arms 不完整")
    arm_ids = set(arms)
    coverage_id = content.get("coverage_experiment_id")
    if arm_ids == set(LEGACY_ARMS) and coverage_id is None:
        return LEGACY_ARMS
    if (
        arm_ids == set(ARMS)
        and coverage_id in COVERAGE_FORWARD_EXPERIMENT_IDS
    ):
        return ARMS
    raise ValueError("前向登記臂版本不符")


def _rule_tickets(decision: dict) -> list[dict]:
    """從 Qwen 已改選的 decision 重建同一期規則裁決，不接觸 reveal。"""
    tickets, _, _ = _adjudicate(
        decision["proposals"],
        decision["critiques"],
        {"agents": decision["state_before"]["agents"]},
    )
    return [
        _normalize_ticket(ticket, slot)
        for slot, ticket in enumerate(tickets, 1)
    ]


def _random_tickets(game: str, target: dict) -> list[dict]:
    rng = random.Random(
        seed_int(
            f"lotto-lab|{FORWARD_EXPERIMENT_ID}|{game}|"
            f"{target['date']}|period{target['period']}|uniform-null"
        )
    )
    tickets = []
    seen = set()
    while len(tickets) < SELECTED_TICKETS:
        numbers = tuple(
            sorted(rng.sample(range(1, POOL[game] + 1), PICK_N))
        )
        if numbers in seen:
            continue
        seen.add(numbers)
        slot = len(tickets) + 1
        tickets.append(
            {
                "slot": slot,
                "source_agent": "uniform_null",
                "source_proposal": f"uniform_null:{slot}",
                "numbers": list(numbers),
                "special": (
                    rng.randint(1, SPECIAL_POOL[SUPER])
                    if game == SUPER
                    else None
                ),
            }
        )
    return tickets


def _arm(
    *,
    arm_id: str,
    game: str,
    tickets: list[dict],
    eligible: bool,
    source: str,
    metadata: dict | None = None,
    ineligible_reason: str | None = None,
) -> dict:
    _validate_tickets(game, tickets)
    return {
        "arm_id": arm_id,
        "source": source,
        "eligible": bool(eligible),
        "ineligible_reason": ineligible_reason,
        "selection_hash": _selection_hash(game, tickets),
        "tickets": tickets,
        "metadata": metadata or {},
    }


def preregister_decision(
    ledger: Ledger,
    decision: dict,
    *,
    registered_at: str | None = None,
    mechanism_candidate: dict | None = None,
    profit_common_special_candidate: dict | None = None,
    probability_stacking_candidate: dict | None = None,
    null_safe_probability_candidate: dict | None = None,
) -> dict:
    """凍結單一遊戲下一期四臂；同一期再次呼叫為冪等 no-op。"""
    game = decision["game"]
    target = {
        "date": decision["target"]["date"],
        "period": int(decision["target"]["period"]),
    }
    key = _target_key(game, target)
    for event in ledger.events_of("forward_preregister"):
        content = _event_content(event)
        if _target_key(content["game"], content["target"]) == key:
            return {
                "status": "existing",
                "event": event,
                "registration_hash": event["content_hash"],
            }

    if decision.get("history_last") is not None:
        history_last_key = (
            decision["history_last"]["date"],
            int(decision["history_last"]["period"]),
        )
        target_order_key = (target["date"], target["period"])
        if history_last_key >= target_order_key:
            raise ValueError("前向登記偵測到目標期資料洩漏")

    registered_at = registered_at or now_iso()
    late = _is_late(registered_at, target)
    rule_tickets = _rule_tickets(decision)
    qwen_tickets = [
        _normalize_ticket(ticket, slot)
        for slot, ticket in enumerate(decision["selected_tickets"], 1)
    ]
    random_tickets = _random_tickets(game, target)
    coverage_error = None
    try:
        raw_coverage_tickets, consensus_selection = (
            select_consensus_disjoint_portfolio(game, decision)
        )
        coverage_tickets = [
            _normalize_ticket(ticket, slot)
            for slot, ticket in enumerate(raw_coverage_tickets, 1)
        ]
        baseline_structure = portfolio_structure(game, rule_tickets)
        selected_structure = consensus_selection["structure"]
        coverage_selection = {
            "experiment_id": MAX_COVERAGE_RESEARCH_EXPERIMENT_ID,
            "fallback_to_current": False,
            "baseline": baseline_structure,
            "candidate": selected_structure,
            "selected": selected_structure,
            "exact_probability_delta": (
                selected_structure["exact_at_least_three_main"]
                - baseline_structure["exact_at_least_three_main"]
            ),
            "exact_any_prize_probability_delta": (
                selected_structure["exact_any_prize"]
                - baseline_structure["exact_any_prize"]
            ),
            "support_evidence_hash": consensus_selection[
                "support_evidence_hash"
            ],
            "structural_optimum_proof": consensus_selection[
                "structural_optimum_proof"
            ],
            "selected_main_numbers": consensus_selection[
                "selected_main_numbers"
            ],
            "selected_specials": consensus_selection[
                "selected_specials"
            ],
            "ticket_debate_support": consensus_selection[
                "ticket_debate_support"
            ],
            "construction": consensus_selection["construction"],
        }
    except (KeyError, RuntimeError, TypeError, ValueError) as exc:
        coverage_error = type(exc).__name__
        coverage_tickets = deepcopy(rule_tickets)
        baseline_structure = portfolio_structure(game, rule_tickets)
        coverage_selection = {
            "experiment_id": MAX_COVERAGE_RESEARCH_EXPERIMENT_ID,
            "fallback_to_current": True,
            "baseline": baseline_structure,
            "candidate": baseline_structure,
            "selected": baseline_structure,
            "exact_probability_delta": 0.0,
            "exact_any_prize_probability_delta": 0.0,
            "support_evidence_hash": None,
            "structural_optimum_proof": None,
            "selected_main_numbers": sorted(
                {
                    number
                    for ticket in rule_tickets
                    for number in ticket["numbers"]
                }
            ),
            "selected_specials": (
                sorted(
                    {
                        ticket["special"]
                        for ticket in rule_tickets
                    }
                )
                if game == SUPER
                else None
            ),
            "ticket_debate_support": [],
            "construction": None,
        }
    judge = decision["adjudication"]["judge"]
    feedback_provenance = judge.get("feedback_provenance")
    feedback_context = judge.get("feedback_context")
    expected_feedback_context = build_feedback_context(
        ledger,
        game,
        before_target=target,
    )
    feedback_context_verified = (
        isinstance(feedback_context, dict)
        and feedback_context == expected_feedback_context
    )
    expected_feedback_provenance = {
        "experiment_id": FEEDBACK_EXPERIMENT_ID,
        "status": (
            "verified"
            if expected_feedback_context["settlement_count"] > 0
            else "verified_empty"
        ),
        "feedback_hash": expected_feedback_context["feedback_hash"],
        "settlement_count": expected_feedback_context[
            "settlement_count"
        ],
        "as_of_target": expected_feedback_context["as_of_target"],
        "source_postmortem_hashes": expected_feedback_context[
            "source_postmortem_hashes"
        ],
    }
    feedback_verified = (
        feedback_context_verified
        and feedback_provenance == expected_feedback_provenance
    )
    qwen_valid = (
        judge.get("source") == "ollama"
        and judge.get("model") == "qwen3:8b"
        and len(judge.get("selected_proposal_ids", [])) == SELECTED_TICKETS
        and feedback_verified
    )
    telemetry = judge.get("telemetry")
    ops_instrumented = (
        isinstance(telemetry, dict)
        and telemetry.get("schema_version") == "1"
    )
    common_eligible = not late
    coverage_valid = (
        coverage_error is None
        and coverage_selection.get("experiment_id")
        == MAX_COVERAGE_RESEARCH_EXPERIMENT_ID
        and isinstance(
            coverage_selection.get("support_evidence_hash"), str
        )
        and len(coverage_selection["support_evidence_hash"]) == 64
        and coverage_selection.get("structural_optimum_proof")
        == structural_proof_reference()
        and coverage_selection["selected"].get("main_union_size") == 30
        and coverage_selection["selected"].get(
            "maximum_pairwise_main_overlap"
        )
        == 0
        and (
            game != SUPER
            or coverage_selection["selected"].get(
                "special_coverage_probability"
            )
            == SELECTED_TICKETS / SPECIAL_POOL[SUPER]
        )
        and float(
            coverage_selection.get("exact_probability_delta", -1.0)
        )
        >= -1e-15
        and float(
            coverage_selection.get(
                "exact_any_prize_probability_delta", -1.0
            )
        )
        >= -1e-15
    )
    special_shadow = None
    if coverage_valid and game == SUPER and mechanism_candidate is not None:
        special_shadow = _special_shadow_registration(
            decision,
            coverage_tickets,
            mechanism_candidate,
        )
    verified_profit_common_special_candidate = None
    if (
        coverage_valid
        and game == SUPER
        and profit_common_special_candidate is not None
    ):
        verified_profit_common_special_candidate = (
            validate_common_special_candidate(
                profit_common_special_candidate
            )
        )
        if (
            verified_profit_common_special_candidate[
                "fitted_through"
            ]
            >= target["date"]
        ):
            raise ValueError(
                "共同第二區 shadow 候選含目標期或未來資料"
            )
    probability_stacking_shadow = None
    probability_stacking_error = None
    if coverage_valid and probability_stacking_candidate is not None:
        try:
            probability_stacking_shadow = (
                _probability_stacking_shadow_registration(
                    decision,
                    probability_stacking_candidate,
                )
            )
        except (KeyError, RuntimeError, TypeError, ValueError) as exc:
            probability_stacking_error = type(exc).__name__
    null_safe_probability_shadow = None
    null_safe_probability_error = None
    if (
        coverage_valid
        and probability_stacking_shadow is not None
        and null_safe_probability_candidate is not None
    ):
        try:
            null_safe_probability_shadow = (
                _null_safe_probability_shadow_registration(
                    decision,
                    coverage_tickets,
                    coverage_selection["support_evidence_hash"],
                    null_safe_probability_candidate,
                )
            )
        except (KeyError, RuntimeError, TypeError, ValueError) as exc:
            null_safe_probability_error = type(exc).__name__
    elif (
        coverage_valid
        and null_safe_probability_candidate is not None
        and probability_stacking_shadow is None
    ):
        null_safe_probability_error = (
            "ProbabilityStackingUnavailable"
        )
    coverage_forward_experiment_id = (
        COVERAGE_FORWARD_EXPERIMENT_ID_V7
        if null_safe_probability_shadow is not None
        else COVERAGE_FORWARD_EXPERIMENT_ID_V6
        if probability_stacking_shadow is not None
        else COVERAGE_FORWARD_EXPERIMENT_ID_V4
        if verified_profit_common_special_candidate is not None
        else COVERAGE_FORWARD_EXPERIMENT_ID
    )
    profit_shadows = None
    profit_shadows_error = None
    if coverage_valid and game == SUPER:
        try:
            profit_shadows = build_profit_portfolio_shadows(
                source_decision_hash=decision["decision_hash"],
                support_evidence_hash=coverage_selection[
                    "support_evidence_hash"
                ],
                ranked_main_numbers=coverage_selection[
                    "selected_main_numbers"
                ],
                selected_special=_profit_shadow_selected_special(
                    coverage_tickets,
                    coverage_selection["ticket_debate_support"],
                ),
                common_special_candidate=(
                    verified_profit_common_special_candidate
                ),
            )
        except (KeyError, RuntimeError, TypeError, ValueError) as exc:
            profit_shadows_error = type(exc).__name__
    arms = {
        ARM_RULE: _arm(
            arm_id=ARM_RULE,
            game=game,
            tickets=rule_tickets,
            eligible=common_eligible,
            source="deterministic_rule",
            metadata={
                "source_decision_hash": decision["decision_hash"],
                "agents": list(AGENT_IDS),
            },
            ineligible_reason="late_registration" if late else None,
        ),
        ARM_QWEN: _arm(
            arm_id=ARM_QWEN,
            game=game,
            tickets=qwen_tickets,
            eligible=common_eligible and qwen_valid,
            source=judge.get("source") or "unknown",
            metadata={
                "model": judge.get("model"),
                "requested_model": judge.get("requested_model"),
                "prompt_hash": judge.get("prompt_hash"),
                "response_hash": judge.get("response_hash"),
                "selected_proposal_ids": judge.get(
                    "selected_proposal_ids", []
                ),
                "telemetry": deepcopy(telemetry),
                "selection_diagnostics": deepcopy(
                    judge.get("selection_diagnostics")
                ),
                "feedback_provenance": deepcopy(
                    judge.get("feedback_provenance")
                ),
                "feedback_context": deepcopy(
                    judge.get("feedback_context")
                ),
                "fallback_reason": judge.get("fallback_reason"),
            },
            ineligible_reason=(
                "late_registration"
                if late
                else None
                if qwen_valid
                else "qwen_not_verified"
            ),
        ),
        ARM_RANDOM: _arm(
            arm_id=ARM_RANDOM,
            game=game,
            tickets=random_tickets,
            eligible=common_eligible,
            source="uniform_null",
            metadata={
                "seed_contract": (
                    f"{FORWARD_EXPERIMENT_ID}|{game}|"
                    f"period{target['period']}|uniform-null"
                )
            },
            ineligible_reason="late_registration" if late else None,
        ),
        ARM_COVERAGE: _arm(
            arm_id=ARM_COVERAGE,
            game=game,
            tickets=coverage_tickets,
            eligible=common_eligible and coverage_valid,
            source="deterministic_consensus_disjoint_selector",
            metadata={
                "experiment_id": coverage_forward_experiment_id,
                "source_research_experiment_id": (
                    MAX_COVERAGE_RESEARCH_EXPERIMENT_ID
                ),
                "source_decision_hash": decision["decision_hash"],
                "candidate_pool_hash": canonical_hash(
                    {
                        "game": game,
                        "target": target,
                        "proposals": decision["proposals"],
                    }
                ),
                "support_evidence_hash": coverage_selection[
                    "support_evidence_hash"
                ],
                "structural_optimum_proof": coverage_selection[
                    "structural_optimum_proof"
                ],
                "selected_main_numbers": coverage_selection[
                    "selected_main_numbers"
                ],
                "selected_specials": coverage_selection[
                    "selected_specials"
                ],
                "ticket_debate_support": coverage_selection[
                    "ticket_debate_support"
                ],
                "construction": coverage_selection[
                    "construction"
                ],
                "fallback_to_current": coverage_selection[
                    "fallback_to_current"
                ],
                "baseline_structure": coverage_selection["baseline"],
                "candidate_structure": coverage_selection["candidate"],
                "selected_structure": coverage_selection["selected"],
                "exact_probability_delta": coverage_selection[
                    "exact_probability_delta"
                ],
                "exact_any_prize_probability_delta": (
                    coverage_selection[
                        "exact_any_prize_probability_delta"
                    ]
                ),
                "error_type": coverage_error,
                "special_frequency_shadow": special_shadow,
                "profit_portfolio_shadows": profit_shadows,
                "profit_portfolio_shadows_error_type": (
                    profit_shadows_error
                ),
                "probability_stacking_shadow": (
                    probability_stacking_shadow
                ),
                "probability_stacking_shadow_error_type": (
                    probability_stacking_error
                ),
                "null_safe_probability_shadow": (
                    null_safe_probability_shadow
                ),
                "null_safe_probability_shadow_error_type": (
                    null_safe_probability_error
                ),
            },
            ineligible_reason=(
                "late_registration"
                if late
                else None
                if coverage_valid
                else "coverage_not_verified"
            ),
        ),
    }
    content = {
        "schema_version": "1",
        "experiment_id": FORWARD_EXPERIMENT_ID,
        "phase": "preregister",
        "game": game,
        "game_name": GAME_NAMES[game],
        "target": target,
        "registered_at": registered_at,
        "deadline": _deadline(target),
        "late": late,
        "history_count": int(decision["history_count"]),
        "history_last": deepcopy(decision.get("history_last")),
        "source_decision_hash": decision["decision_hash"],
        "coverage_experiment_id": coverage_forward_experiment_id,
        "ops_experiment_id": (
            OPS_EXPERIMENT_ID if ops_instrumented else None
        ),
        "arms": arms,
        "honesty_note": (
            "四臂在開獎前同時凍結；若沒有本事件，開獎後不得補做該期比較。"
        ),
    }
    event = _append_content(ledger, "forward_preregister", content)
    return {
        "status": "created",
        "event": event,
        "registration_hash": event["content_hash"],
    }


def _ticket_result(game: str, ticket: dict, draw: Draw) -> dict:
    main_hits = len(set(ticket["numbers"]) & set(draw.numbers))
    special_hit = (
        ticket["special"] == draw.special
        if game == SUPER
        else draw.special in set(ticket["numbers"])
    )
    tier = match_tier(game, ticket["numbers"], ticket["special"], draw)
    return {
        "slot": int(ticket["slot"]),
        "main_hits": main_hits,
        "special_hit": special_hit,
        "hit_points": round(main_hits + (0.25 if special_hit else 0.0), 2),
        "tier": tier.label if tier else None,
    }


def _portfolio_result(game: str, tickets: list[dict], draw: Draw) -> dict:
    results = [_ticket_result(game, ticket, draw) for ticket in tickets]
    selected_union = set().union(
        *(set(ticket["numbers"]) for ticket in tickets)
    )
    counts = Counter(
        number for ticket in tickets for number in ticket["numbers"]
    )
    repeated_misses = [
        {"number": number, "selected_count": count}
        for number, count in sorted(
            counts.items(), key=lambda item: (-item[1], item[0])
        )
        if count > 1 and number not in draw.numbers
    ]
    winning_tickets = sum(item["tier"] is not None for item in results)
    return {
        "best_main_hits": max(item["main_hits"] for item in results),
        "total_main_hits": sum(item["main_hits"] for item in results),
        "any_three_plus": any(item["main_hits"] >= 3 for item in results),
        "special_hit_tickets": sum(
            item["special_hit"] for item in results
        ),
        "winning_tickets": winning_tickets,
        "any_prize": winning_tickets > 0,
        "union_main_hits": len(selected_union & set(draw.numbers)),
        "union_size": len(selected_union),
        "missed_actual_numbers": sorted(
            set(draw.numbers) - selected_union
        ),
        "repeated_but_missed": repeated_misses,
        "ticket_results": results,
    }


def _profit_portfolio_result(
    tickets: list[dict],
    draw: Draw,
) -> dict:
    """以同一個凍結歷史 floor 結算威力彩五注獲利 shadow。"""
    rows = []
    conservative_payout = 0
    empirical_floor_payout = 0
    basis_counts: Counter[str] = Counter()
    for ticket in tickets:
        tier = match_tier(
            SUPER,
            ticket["numbers"],
            ticket["special"],
            draw,
        )
        if tier is None:
            rows.append(
                {
                    "slot": int(ticket["slot"]),
                    "tier": None,
                    "tier_api_key": None,
                    "conservative_counterfactual_payout_ntd": 0,
                    "empirical_floor_stress_payout_ntd": 0,
                    "payout_basis": "none",
                    "payout_upper_ntd": 0,
                }
            )
            basis_counts["none"] += 1
            continue
        value, basis, upper = prize_value(
            tier,
            draw,
            floor_table=EMPIRICAL_FLOOR_NTD,
        )
        stress_value = EMPIRICAL_FLOOR_NTD[tier.api_key]
        conservative_payout += value
        empirical_floor_payout += stress_value
        basis_counts[basis] += 1
        rows.append(
            {
                "slot": int(ticket["slot"]),
                "tier": tier.label,
                "tier_api_key": tier.api_key,
                "conservative_counterfactual_payout_ntd": value,
                "empirical_floor_stress_payout_ntd": stress_value,
                "payout_basis": basis,
                "payout_upper_ntd": upper,
            }
        )
    return {
        "five_ticket_cost_ntd": FIVE_TICKET_COST_NTD,
        "winning_tickets": sum(row["tier"] is not None for row in rows),
        "conservative_counterfactual_payout_ntd": conservative_payout,
        "conservative_counterfactual_net_ntd": (
            conservative_payout - FIVE_TICKET_COST_NTD
        ),
        "conservative_counterfactual_strict_profit": (
            conservative_payout > FIVE_TICKET_COST_NTD
        ),
        "empirical_floor_stress_payout_ntd": empirical_floor_payout,
        "empirical_floor_stress_net_ntd": (
            empirical_floor_payout - FIVE_TICKET_COST_NTD
        ),
        "empirical_floor_stress_strict_profit": (
            empirical_floor_payout > FIVE_TICKET_COST_NTD
        ),
        "payout_basis_counts": dict(sorted(basis_counts.items())),
        "ticket_results": rows,
    }


def _profit_shadow_settlement(
    registered_shadow: dict,
    coverage_tickets: list[dict],
    *,
    eligible: bool,
    draw: Draw,
) -> dict:
    coverage_result = _profit_portfolio_result(
        coverage_tickets, draw
    )
    portfolios = {}
    for portfolio_id in PROFIT_PORTFOLIO_IDS:
        registered = registered_shadow["portfolios"][portfolio_id]
        result = _profit_portfolio_result(
            registered["tickets"], draw
        )
        profit_delta = int(
            result["empirical_floor_stress_strict_profit"]
        ) - int(
            coverage_result["empirical_floor_stress_strict_profit"]
        )
        portfolios[portfolio_id] = {
            "portfolio_id": portfolio_id,
            "selection_hash": registered["selection_hash"],
            "eligible": bool(eligible),
            "result": result,
            "shadow_minus_coverage_empirical_floor_strict_profit": (
                profit_delta
            ),
            "shadow_minus_coverage_empirical_floor_payout_ntd": (
                result["empirical_floor_stress_payout_ntd"]
                - coverage_result[
                    "empirical_floor_stress_payout_ntd"
                ]
            ),
            "shadow_minus_coverage_conservative_payout_ntd": (
                result["conservative_counterfactual_payout_ntd"]
                - coverage_result[
                    "conservative_counterfactual_payout_ntd"
                ]
            ),
            "verdict": (
                "shadow_win"
                if profit_delta > 0
                else "coverage_win"
                if profit_delta < 0
                else "tie"
            ),
        }
    payload = {
        "experiment_id": PROFIT_SHADOW_EXPERIMENT_ID,
        "shadow_hash": registered_shadow["shadow_hash"],
        "eligible": bool(eligible),
        "coverage_result": coverage_result,
        "portfolios": portfolios,
        "interpretation": (
            "單期結果只累積前向樣本；精確結構機率來自開獎前已凍結"
            "的有限枚舉證明，不用本期結果回改該期票券。"
        ),
    }
    registered_common = registered_shadow.get(
        "common_special_shadow"
    )
    if registered_common is not None:
        common_portfolios = {}
        for portfolio_id in PROFIT_PORTFOLIO_IDS:
            baseline_result = portfolios[portfolio_id]["result"]
            registered = registered_common["portfolios"][
                portfolio_id
            ]
            result = _profit_portfolio_result(
                registered["tickets"], draw
            )
            strict_delta = int(
                result["empirical_floor_stress_strict_profit"]
            ) - int(
                baseline_result[
                    "empirical_floor_stress_strict_profit"
                ]
            )
            common_portfolios[portfolio_id] = {
                "portfolio_id": portfolio_id,
                "selection_hash": registered["selection_hash"],
                "eligible": bool(eligible),
                "result": result,
                (
                    "common_special_minus_baseline_"
                    "empirical_floor_strict_profit"
                ): strict_delta,
                (
                    "common_special_minus_baseline_"
                    "empirical_floor_payout_ntd"
                ): (
                    result["empirical_floor_stress_payout_ntd"]
                    - baseline_result[
                        "empirical_floor_stress_payout_ntd"
                    ]
                ),
                (
                    "common_special_minus_baseline_"
                    "empirical_floor_net_ntd"
                ): (
                    result["empirical_floor_stress_net_ntd"]
                    - baseline_result[
                        "empirical_floor_stress_net_ntd"
                    ]
                ),
                "verdict": (
                    "common_special_win"
                    if strict_delta > 0
                    else "baseline_special_win"
                    if strict_delta < 0
                    else "tie"
                ),
            }
        payload["common_special_shadow"] = {
            "experiment_id": COMMON_SPECIAL_SHADOW_EXPERIMENT_ID,
            "candidate_hash": registered_common["candidate_hash"],
            "shadow_hash": registered_common["shadow_hash"],
            "eligible": bool(eligible),
            "baseline_special": registered_common[
                "baseline_special"
            ],
            "selected_special": registered_common[
                "selected_special"
            ],
            "portfolios": common_portfolios,
            "interpretation": (
                "共同第二區只與同一主號結構、同一期辯論選出的"
                " baseline 第二區作前向配對；單期不回改策略。"
            ),
        }
    return payload


def _probability_stacking_shadow_settlement(
    registered_shadow: dict,
    coverage_tickets: list[dict],
    *,
    eligible: bool,
    game: str,
    draw: Draw,
) -> dict:
    shadow_result = _portfolio_result(
        game,
        registered_shadow["tickets"],
        draw,
    )
    coverage_result = _portfolio_result(
        game,
        coverage_tickets,
        draw,
    )
    union_delta = (
        shadow_result["union_main_hits"]
        - coverage_result["union_main_hits"]
    )
    proper_score = None
    if registered_shadow.get("score_capsule") is not None:
        proper_score = settle_probability_score_capsule(
            registered_shadow["score_capsule"],
            game=game,
            target=registered_shadow["score_capsule"]["target"],
            candidate_hash=registered_shadow["candidate_hash"],
            source_decision_hash=registered_shadow[
                "source_decision_hash"
            ],
            actual_main=list(draw.numbers),
            actual_special=draw.special if game == SUPER else None,
            eligible=eligible,
        )
    payload = {
        "experiment_id": registered_shadow["experiment_id"],
        "candidate_hash": registered_shadow["candidate_hash"],
        "protocol_hash": registered_shadow["protocol_hash"],
        "selection_hash": registered_shadow["selection_hash"],
        "support_evidence_hash": registered_shadow[
            "support_evidence_hash"
        ],
        "eligible": bool(eligible),
        "result": shadow_result,
        "coverage_result": coverage_result,
        "stacking_minus_coverage_union_main_hits": union_delta,
        "stacking_minus_coverage_best_main_hits": (
            shadow_result["best_main_hits"]
            - coverage_result["best_main_hits"]
        ),
        "stacking_minus_coverage_any_three_plus": (
            int(shadow_result["any_three_plus"])
            - int(coverage_result["any_three_plus"])
        ),
        "stacking_minus_coverage_any_prize": (
            int(shadow_result["any_prize"])
            - int(coverage_result["any_prize"])
        ),
        "verdict": (
            "stacking_win"
            if union_delta > 0
            else "coverage_win"
            if union_delta < 0
            else "tie"
        ),
    }
    if proper_score is not None:
        payload["proper_score"] = proper_score
    return payload


def _null_safe_probability_shadow_settlement(
    registered_shadow: dict,
    coverage_tickets: list[dict],
    *,
    eligible: bool,
    game: str,
    draw: Draw,
) -> dict:
    safe_result = _portfolio_result(
        game,
        registered_shadow["tickets"],
        draw,
    )
    coverage_result = _portfolio_result(
        game,
        coverage_tickets,
        draw,
    )
    union_delta = (
        safe_result["union_main_hits"]
        - coverage_result["union_main_hits"]
    )
    proper_score = settle_null_safe_score_capsule(
        registered_shadow["score_capsule"],
        game=game,
        target=registered_shadow["score_capsule"]["target"],
        candidate_hash=registered_shadow["candidate_hash"],
        source_decision_hash=registered_shadow[
            "source_decision_hash"
        ],
        actual_main=list(draw.numbers),
        actual_special=draw.special if game == SUPER else None,
        eligible=eligible,
    )
    return {
        "experiment_id": registered_shadow["experiment_id"],
        "candidate_hash": registered_shadow["candidate_hash"],
        "protocol_hash": registered_shadow["protocol_hash"],
        "selection_hash": registered_shadow["selection_hash"],
        "support_evidence_hash": registered_shadow[
            "support_evidence_hash"
        ],
        "eligible": bool(eligible),
        "main_gate_active_for_scored_target": registered_shadow[
            "main_gate_active"
        ],
        "special_gate_active_for_scored_target": registered_shadow[
            "special_gate_active"
        ],
        "result": safe_result,
        "coverage_result": coverage_result,
        "null_safe_minus_coverage_union_main_hits": union_delta,
        "null_safe_minus_coverage_best_main_hits": (
            safe_result["best_main_hits"]
            - coverage_result["best_main_hits"]
        ),
        "null_safe_minus_coverage_any_three_plus": (
            int(safe_result["any_three_plus"])
            - int(coverage_result["any_three_plus"])
        ),
        "null_safe_minus_coverage_any_prize": (
            int(safe_result["any_prize"])
            - int(coverage_result["any_prize"])
        ),
        "verdict": (
            "null_safe_win"
            if union_delta > 0
            else "coverage_win"
            if union_delta < 0
            else "tie"
        ),
        "proper_score": proper_score,
    }


def _find_draw(store, game: str, target: dict) -> Draw | None:
    for draw in store.draws(game):
        if (
            draw.date == target["date"]
            and draw.period == int(target["period"])
        ):
            return draw
    return None


def settle_ready(ledger: Ledger, store) -> list[dict]:
    """結算所有已有揭曉且尚未結算的開獎前登記。"""
    registrations = ledger.events_of("forward_preregister")
    settled_hashes = {
        _event_content(event)["registration_hash"]
        for event in ledger.events_of("forward_settlement")
    }
    created = []
    for registration in registrations:
        registration_hash = registration["content_hash"]
        if registration_hash in settled_hashes:
            continue
        preregistered = _event_content(registration)
        draw = _find_draw(
            store, preregistered["game"], preregistered["target"]
        )
        if draw is None:
            continue
        registered_arms = _registered_arms(preregistered)
        arm_results = {
            arm_id: _portfolio_result(
                preregistered["game"],
                preregistered["arms"][arm_id]["tickets"],
                draw,
            )
            for arm_id in registered_arms
        }
        qwen_rule_eligible = (
            preregistered["arms"][ARM_QWEN]["eligible"]
            and preregistered["arms"][ARM_RULE]["eligible"]
        )
        primary_delta = (
            arm_results[ARM_QWEN]["best_main_hits"]
            - arm_results[ARM_RULE]["best_main_hits"]
        )
        comparison = {
            "eligible": qwen_rule_eligible,
            "qwen_minus_rule_best_main_hits": primary_delta,
            "qwen_minus_rule_total_main_hits": (
                arm_results[ARM_QWEN]["total_main_hits"]
                - arm_results[ARM_RULE]["total_main_hits"]
            ),
            "qwen_minus_rule_union_main_hits": (
                arm_results[ARM_QWEN]["union_main_hits"]
                - arm_results[ARM_RULE]["union_main_hits"]
            ),
            "verdict": (
                "qwen_win"
                if primary_delta > 0
                else "rule_win"
                if primary_delta < 0
                else "tie"
            ),
        }
        coverage_comparison = None
        special_shadow_settlement = None
        profit_shadow_settlement = None
        probability_stacking_settlement = None
        null_safe_probability_settlement = None
        if ARM_COVERAGE in registered_arms:
            coverage_rule_eligible = (
                preregistered["arms"][ARM_COVERAGE]["eligible"]
                and preregistered["arms"][ARM_RULE]["eligible"]
            )
            coverage_delta = (
                arm_results[ARM_COVERAGE]["best_main_hits"]
                - arm_results[ARM_RULE]["best_main_hits"]
            )
            coverage_comparison = {
                "eligible": coverage_rule_eligible,
                "coverage_minus_rule_best_main_hits": coverage_delta,
                "coverage_minus_rule_total_main_hits": (
                    arm_results[ARM_COVERAGE]["total_main_hits"]
                    - arm_results[ARM_RULE]["total_main_hits"]
                ),
                "coverage_minus_rule_any_three_plus": (
                    int(arm_results[ARM_COVERAGE]["any_three_plus"])
                    - int(arm_results[ARM_RULE]["any_three_plus"])
                ),
                "coverage_minus_rule_union_main_hits": (
                    arm_results[ARM_COVERAGE]["union_main_hits"]
                    - arm_results[ARM_RULE]["union_main_hits"]
                ),
                "preregistered_exact_probability_delta": (
                    preregistered["arms"][ARM_COVERAGE]["metadata"][
                        "exact_probability_delta"
                    ]
                ),
                "preregistered_any_prize_probability_delta": (
                    preregistered["arms"][ARM_COVERAGE]["metadata"][
                        "exact_any_prize_probability_delta"
                    ]
                ),
                "verdict": (
                    "coverage_win"
                    if coverage_delta > 0
                    else "rule_win"
                    if coverage_delta < 0
                    else "tie"
                ),
            }
            shadow = preregistered["arms"][ARM_COVERAGE][
                "metadata"
            ].get("special_frequency_shadow")
            if shadow is not None:
                shadow_result = _portfolio_result(
                    preregistered["game"],
                    shadow["tickets"],
                    draw,
                )
                coverage_result = arm_results[ARM_COVERAGE]
                prize_delta = (
                    int(shadow_result["any_prize"])
                    - int(coverage_result["any_prize"])
                )
                special_shadow_settlement = {
                    "experiment_id": shadow["experiment_id"],
                    "candidate_hash": shadow["candidate_hash"],
                    "selection_hash": shadow["selection_hash"],
                    "eligible": preregistered["arms"][
                        ARM_COVERAGE
                    ]["eligible"],
                    "result": shadow_result,
                    "shadow_minus_coverage_any_prize": prize_delta,
                    "shadow_minus_coverage_winning_tickets": (
                        shadow_result["winning_tickets"]
                        - coverage_result["winning_tickets"]
                    ),
                    "shadow_minus_coverage_special_hit_tickets": (
                        shadow_result["special_hit_tickets"]
                        - coverage_result["special_hit_tickets"]
                    ),
                    "verdict": (
                        "shadow_win"
                        if prize_delta > 0
                        else "coverage_win"
                        if prize_delta < 0
                        else "tie"
                    ),
                }
            registered_profit_shadows = preregistered["arms"][
                ARM_COVERAGE
            ]["metadata"].get("profit_portfolio_shadows")
            if registered_profit_shadows is not None:
                profit_shadow_settlement = _profit_shadow_settlement(
                    registered_profit_shadows,
                    preregistered["arms"][ARM_COVERAGE]["tickets"],
                    eligible=preregistered["arms"][ARM_COVERAGE][
                        "eligible"
                    ],
                    draw=draw,
                )
            registered_probability_stacking = preregistered["arms"][
                ARM_COVERAGE
            ]["metadata"].get("probability_stacking_shadow")
            if registered_probability_stacking is not None:
                probability_stacking_settlement = (
                    _probability_stacking_shadow_settlement(
                        registered_probability_stacking,
                        preregistered["arms"][ARM_COVERAGE][
                            "tickets"
                        ],
                        eligible=preregistered["arms"][
                            ARM_COVERAGE
                        ]["eligible"],
                        game=preregistered["game"],
                        draw=draw,
                    )
                )
            registered_null_safe_probability = preregistered[
                "arms"
            ][ARM_COVERAGE]["metadata"].get(
                "null_safe_probability_shadow"
            )
            if registered_null_safe_probability is not None:
                null_safe_probability_settlement = (
                    _null_safe_probability_shadow_settlement(
                        registered_null_safe_probability,
                        preregistered["arms"][ARM_COVERAGE][
                            "tickets"
                        ],
                        eligible=preregistered["arms"][
                            ARM_COVERAGE
                        ]["eligible"],
                        game=preregistered["game"],
                        draw=draw,
                    )
                )
        content = {
            "schema_version": "1",
            "experiment_id": FORWARD_EXPERIMENT_ID,
            "phase": "settlement",
            "registration_hash": registration_hash,
            "game": preregistered["game"],
            "game_name": preregistered["game_name"],
            "target": preregistered["target"],
            "actual": {
                "numbers": list(draw.numbers),
                "special": draw.special,
            },
            "arm_results": arm_results,
            "qwen_vs_rule": comparison,
            **(
                {"coverage_vs_rule": coverage_comparison}
                if coverage_comparison is not None
                else {}
            ),
            **(
                {
                    "special_frequency_shadow": (
                        special_shadow_settlement
                    )
                }
                if special_shadow_settlement is not None
                else {}
            ),
            **(
                {
                    "profit_portfolio_shadows": (
                        profit_shadow_settlement
                    )
                }
                if profit_shadow_settlement is not None
                else {}
            ),
            **(
                {
                    "probability_stacking_shadow": (
                        probability_stacking_settlement
                    )
                }
                if probability_stacking_settlement is not None
                else {}
            ),
            **(
                {
                    "null_safe_probability_shadow": (
                        null_safe_probability_settlement
                    )
                }
                if null_safe_probability_settlement is not None
                else {}
            ),
            "postmortem": build_postmortem(
                {
                    **preregistered,
                    "registration_hash": registration_hash,
                },
                arm_results,
                comparison,
                profit_shadow_settlement,
                probability_stacking_settlement,
            ),
            "interpretation": (
                f"本期只量化已凍結{len(registered_arms)}臂與實際開獎的落差；"
                "不把事後命中或漏號解釋為隨機開獎的因果。"
            ),
        }
        created.append(
            _append_content(ledger, "forward_settlement", content)
        )
    return created


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


def _block_bootstrap_ci(
    differences: list[float],
    *,
    game: str,
    tail_probability: float = 0.025,
    comparison_id: str = "qwen-vs-rule",
) -> tuple[float, float] | None:
    if len(differences) < 2:
        return None
    if not 0 < tail_probability < 0.5:
        raise ValueError("bootstrap tail_probability 必須介於 0 與 0.5")
    n = len(differences)
    block = min(BOOTSTRAP_BLOCK_DRAWS, n)
    blocks_needed = math.ceil(n / block)
    final_block = n - block * (blocks_needed - 1)
    full_sums = [
        sum(differences[(start + offset) % n] for offset in range(block))
        for start in range(n)
    ]
    final_sums = [
        sum(
            differences[(start + offset) % n]
            for offset in range(final_block)
        )
        for start in range(n)
    ]
    rng = random.Random(
        seed_int(
            f"{FORWARD_EXPERIMENT_ID}|{game}|{comparison_id}|"
            f"block{BOOTSTRAP_BLOCK_DRAWS}|samples{BOOTSTRAP_SAMPLES}"
        )
    )
    means = []
    for _ in range(BOOTSTRAP_SAMPLES):
        total = sum(
            full_sums[rng.randrange(n)]
            for _ in range(blocks_needed - 1)
        )
        total += final_sums[rng.randrange(n)]
        means.append(total / n)
    return (
        _quantile(means, tail_probability),
        _quantile(means, 1 - tail_probability),
    )


def _sequential_monitor(
    differences: list[float],
    *,
    game: str,
    comparison_family_size: int = 1,
) -> dict:
    """只在預註冊 checkpoint 看資料，以 alpha spending 防重複偷看。"""
    if (
        not isinstance(comparison_family_size, int)
        or comparison_family_size < 1
    ):
        raise ValueError("comparison_family_size 必須為正整數")
    if any(not math.isfinite(float(value)) for value in differences):
        raise ValueError("sequential monitor 差值必須為有限值")
    look_alpha = (
        MONITORING_FAMILY_LOWER_TAIL_ALPHA
        / len(MONITORING_CHECKPOINTS)
        / comparison_family_size
    )
    stream_family_alpha = (
        MONITORING_FAMILY_LOWER_TAIL_ALPHA
        / comparison_family_size
    )
    observed = len(differences)
    completed = [
        checkpoint
        for checkpoint in MONITORING_CHECKPOINTS
        if checkpoint <= observed
    ]
    if not completed:
        return {
            "observed_pairs": observed,
            "evaluated_pairs": 0,
            "checkpoint_index": None,
            "next_checkpoint": MONITORING_CHECKPOINTS[0],
            "protocol_id": MONITORING_PROTOCOL_ID,
            "comparison_family_size": comparison_family_size,
            "look_lower_tail_alpha": look_alpha,
            "stream_family_lower_tail_alpha": (
                stream_family_alpha
            ),
            "family_lower_tail_alpha": (
                MONITORING_FAMILY_LOWER_TAIL_ALPHA
            ),
            "ci_low": None,
            "ci_high": None,
            "mean_delta": None,
            "supported": False,
            "final": False,
            "stopped_early": False,
            "completed_looks": [],
            "status": "collecting_forward_data",
        }
    evaluations = []
    supported_evaluation = None
    for checkpoint in completed:
        values = differences[:checkpoint]
        interval = _block_bootstrap_ci(
            values,
            game=f"{game}|checkpoint{checkpoint}",
            tail_probability=look_alpha,
        )
        evaluation = {
            "checkpoint": checkpoint,
            "checkpoint_index": MONITORING_CHECKPOINTS.index(
                checkpoint
            ),
            "ci_low": interval[0] if interval else None,
            "ci_high": interval[1] if interval else None,
            "mean_delta": statistics.fmean(values),
            "supported": bool(interval and interval[0] > 0),
        }
        evaluations.append(evaluation)
        if evaluation["supported"]:
            supported_evaluation = evaluation
            break
    selected = supported_evaluation or evaluations[-1]
    evaluated = selected["checkpoint"]
    checkpoint_index = selected["checkpoint_index"]
    supported = selected["supported"]
    final = (
        supported
        or completed[-1] == MONITORING_CHECKPOINTS[-1]
    )
    return {
        "observed_pairs": observed,
        "evaluated_pairs": evaluated,
        "checkpoint_index": checkpoint_index,
        "protocol_id": MONITORING_PROTOCOL_ID,
        "comparison_family_size": comparison_family_size,
        "next_checkpoint": (
            None
            if final
            else MONITORING_CHECKPOINTS[checkpoint_index + 1]
        ),
        "look_lower_tail_alpha": look_alpha,
        "stream_family_lower_tail_alpha": stream_family_alpha,
        "family_lower_tail_alpha": (
            MONITORING_FAMILY_LOWER_TAIL_ALPHA
        ),
        "ci_low": selected["ci_low"],
        "ci_high": selected["ci_high"],
        "mean_delta": selected["mean_delta"],
        "supported": supported,
        "final": final,
        "stopped_early": bool(
            supported
            and evaluated != MONITORING_CHECKPOINTS[-1]
        ),
        "completed_looks": evaluations,
        "status": (
            "supported"
            if supported
            else "not_supported_final"
            if final
            else "collecting_forward_data"
        ),
    }


def _joint_qwen_monitor(
    streams: dict[str, dict[str, list[float]]],
) -> dict:
    """只允許兩款遊戲在同一共同 checkpoint 聯合通過。"""
    expected_games = {SUPER, LOTTO649}
    if set(streams) != expected_games:
        raise ValueError("Qwen joint monitor 必須同時包含兩款遊戲")
    observed_pairs = {}
    normalized_streams = {}
    for game in (SUPER, LOTTO649):
        stream = streams[game]
        if set(stream) != {"primary", "total"}:
            raise ValueError("Qwen joint monitor stream 欄位不完整")
        primary = [float(value) for value in stream["primary"]]
        total = [float(value) for value in stream["total"]]
        if len(primary) != len(total):
            raise ValueError("Qwen joint monitor 指標分母不一致")
        if any(
            not math.isfinite(value) for value in primary + total
        ):
            raise ValueError("Qwen joint monitor 差值必須為有限值")
        observed_pairs[game] = len(primary)
        normalized_streams[game] = {
            "primary": primary,
            "total": total,
        }
    common_observed = min(observed_pairs.values())
    completed = [
        checkpoint
        for checkpoint in MONITORING_CHECKPOINTS
        if checkpoint <= common_observed
    ]
    if not completed:
        return {
            "protocol_id": MONITORING_PROTOCOL_ID,
            "observed_pairs_by_game": observed_pairs,
            "common_observed_pairs": common_observed,
            "evaluated_pairs_per_game": 0,
            "checkpoint_index": None,
            "next_checkpoint": MONITORING_CHECKPOINTS[0],
            "look_lower_tail_alpha": (
                MONITORING_LOOK_LOWER_TAIL_ALPHA
            ),
            "family_lower_tail_alpha": (
                MONITORING_FAMILY_LOWER_TAIL_ALPHA
            ),
            "intersection_union_test": True,
            "games": {},
            "supported": False,
            "final": False,
            "stopped_early": False,
            "completed_looks": [],
            "status": "collecting_forward_data",
        }

    evaluations = []
    supported_evaluation = None
    for checkpoint in completed:
        game_evaluations = {}
        for game in (SUPER, LOTTO649):
            primary = normalized_streams[game][
                "primary"
            ][:checkpoint]
            total = normalized_streams[game]["total"][:checkpoint]
            interval = _block_bootstrap_ci(
                primary,
                game=f"{game}|joint-checkpoint{checkpoint}",
                tail_probability=MONITORING_LOOK_LOWER_TAIL_ALPHA,
            )
            primary_supported = bool(
                interval and interval[0] > 0
            )
            total_mean = statistics.fmean(total)
            game_evaluations[game] = {
                "observed_prefix_pairs": checkpoint,
                "mean_best_main_hits_delta": statistics.fmean(
                    primary
                ),
                "ci_low": interval[0] if interval else None,
                "ci_high": interval[1] if interval else None,
                "primary_supported": primary_supported,
                "mean_total_main_hits_delta": total_mean,
                "total_guardrail_passed": total_mean >= 0,
            }
        supported = all(
            row["primary_supported"]
            and row["total_guardrail_passed"]
            for row in game_evaluations.values()
        )
        evaluation = {
            "checkpoint": checkpoint,
            "checkpoint_index": MONITORING_CHECKPOINTS.index(
                checkpoint
            ),
            "games": game_evaluations,
            "supported": supported,
        }
        evaluations.append(evaluation)
        if supported:
            supported_evaluation = evaluation
            break

    selected = supported_evaluation or evaluations[-1]
    checkpoint = selected["checkpoint"]
    checkpoint_index = selected["checkpoint_index"]
    supported = selected["supported"]
    final = (
        supported
        or completed[-1] == MONITORING_CHECKPOINTS[-1]
    )
    return {
        "protocol_id": MONITORING_PROTOCOL_ID,
        "observed_pairs_by_game": observed_pairs,
        "common_observed_pairs": common_observed,
        "evaluated_pairs_per_game": checkpoint,
        "checkpoint_index": checkpoint_index,
        "next_checkpoint": (
            None
            if final
            else MONITORING_CHECKPOINTS[checkpoint_index + 1]
        ),
        "look_lower_tail_alpha": (
            MONITORING_LOOK_LOWER_TAIL_ALPHA
        ),
        "family_lower_tail_alpha": (
            MONITORING_FAMILY_LOWER_TAIL_ALPHA
        ),
        "intersection_union_test": True,
        "games": selected["games"],
        "supported": supported,
        "final": final,
        "stopped_early": bool(
            supported
            and checkpoint != MONITORING_CHECKPOINTS[-1]
        ),
        "completed_looks": evaluations,
        "status": (
            "supported"
            if supported
            else "not_supported_final"
            if final
            else "collecting_forward_data"
        ),
    }


def _joint_probability_stacking_monitor(
    streams: dict[str, dict[str, list[float]]],
) -> dict:
    """兩款遊戲只在同一 checkpoint 共同檢查 stacking 主要指標與護欄。"""
    metric_names = (
        "union_main_hits",
        "best_main_hits",
        "any_three_plus",
        "any_prize",
    )
    if set(streams) != {SUPER, LOTTO649}:
        raise ValueError("stacking joint monitor 必須包含兩款遊戲")
    observed_pairs = {}
    normalized = {}
    for game in (SUPER, LOTTO649):
        stream = streams[game]
        if set(stream) != set(metric_names):
            raise ValueError("stacking joint monitor 指標欄位不完整")
        lengths = {len(stream[metric]) for metric in metric_names}
        values = {
            metric: [float(value) for value in stream[metric]]
            for metric in metric_names
        }
        if (
            len(lengths) != 1
            or any(
                not math.isfinite(value)
                for metric in metric_names
                for value in values[metric]
            )
        ):
            raise ValueError("stacking joint monitor 指標分母或數值不符")
        observed_pairs[game] = lengths.pop()
        normalized[game] = values
    common_observed = min(observed_pairs.values())
    completed = [
        checkpoint
        for checkpoint in PROBABILITY_STACKING_CHECKPOINTS
        if checkpoint <= common_observed
    ]
    base = {
        "protocol_id": (
            PROBABILITY_STACKING_MONITORING_PROTOCOL_ID
        ),
        "experiment_id": PROBABILITY_STACKING_EXPERIMENT_ID,
        "observed_pairs_by_game": observed_pairs,
        "common_observed_pairs": common_observed,
        "look_lower_tail_alpha": (
            PROBABILITY_STACKING_LOOK_ALPHA
        ),
        "intersection_union_test": True,
    }
    if not completed:
        return {
            **base,
            "evaluated_pairs_per_game": 0,
            "checkpoint_index": None,
            "next_checkpoint": PROBABILITY_STACKING_CHECKPOINTS[0],
            "games": {},
            "supported": False,
            "final": False,
            "stopped_early": False,
            "completed_looks": [],
            "status": "collecting_forward_data",
        }

    evaluations = []
    supported_evaluation = None
    for checkpoint in completed:
        game_evaluations = {}
        for game in (SUPER, LOTTO649):
            primary = normalized[game]["union_main_hits"][
                :checkpoint
            ]
            interval = _block_bootstrap_ci(
                primary,
                game=(
                    f"{game}|probability-stacking|"
                    f"checkpoint{checkpoint}"
                ),
                tail_probability=PROBABILITY_STACKING_LOOK_ALPHA,
                comparison_id=(
                    PROBABILITY_STACKING_EXPERIMENT_ID
                ),
            )
            guardrails = {
                metric: statistics.fmean(
                    normalized[game][metric][:checkpoint]
                )
                for metric in metric_names[1:]
            }
            game_evaluations[game] = {
                "observed_prefix_pairs": checkpoint,
                "mean_union_main_hits_delta": statistics.fmean(
                    primary
                ),
                "ci_low": interval[0] if interval else None,
                "ci_high": interval[1] if interval else None,
                "primary_supported": bool(
                    interval and interval[0] > 0
                ),
                "mean_best_main_hits_delta": guardrails[
                    "best_main_hits"
                ],
                "mean_any_three_plus_delta": guardrails[
                    "any_three_plus"
                ],
                "mean_any_prize_delta": guardrails["any_prize"],
                "guardrails_passed": all(
                    value >= 0 for value in guardrails.values()
                ),
            }
        supported = all(
            row["primary_supported"]
            and row["guardrails_passed"]
            for row in game_evaluations.values()
        )
        evaluation = {
            "checkpoint": checkpoint,
            "checkpoint_index": (
                PROBABILITY_STACKING_CHECKPOINTS.index(
                    checkpoint
                )
            ),
            "games": game_evaluations,
            "supported": supported,
        }
        evaluations.append(evaluation)
        if supported:
            supported_evaluation = evaluation
            break
    selected = supported_evaluation or evaluations[-1]
    checkpoint = selected["checkpoint"]
    checkpoint_index = selected["checkpoint_index"]
    supported = selected["supported"]
    final = (
        supported
        or completed[-1] == PROBABILITY_STACKING_CHECKPOINTS[-1]
    )
    return {
        **base,
        "evaluated_pairs_per_game": checkpoint,
        "checkpoint_index": checkpoint_index,
        "next_checkpoint": (
            None
            if final
            else PROBABILITY_STACKING_CHECKPOINTS[
                checkpoint_index + 1
            ]
        ),
        "games": selected["games"],
        "supported": supported,
        "final": final,
        "stopped_early": bool(
            supported
            and checkpoint
            != PROBABILITY_STACKING_CHECKPOINTS[-1]
        ),
        "completed_looks": evaluations,
        "status": (
            "supported"
            if supported
            else "not_supported_final"
            if final
            else "collecting_forward_data"
        ),
    }


def _joint_probability_score_monitor(
    streams: dict[str, dict[str, list[float]]],
) -> dict:
    """以 v6 future-only proper score 檢查兩遊戲的校準資訊增益。"""
    if set(streams) != {SUPER, LOTTO649}:
        raise ValueError("probability score joint monitor 必須包含兩款遊戲")
    expected_fields = {
        SUPER: {
            "main_information_gain",
            "special_information_gain",
        },
        LOTTO649: {"main_information_gain"},
    }
    observed_scores = {}
    normalized = {}
    for game in (SUPER, LOTTO649):
        stream = streams[game]
        if set(stream) != expected_fields[game]:
            raise ValueError(
                "probability score joint monitor 指標欄位不完整"
            )
        values = {
            metric: [float(value) for value in rows]
            for metric, rows in stream.items()
        }
        main = values["main_information_gain"]
        if game == SUPER and len(
            values["special_information_gain"]
        ) != len(main):
            raise ValueError(
                "probability score joint monitor 第二區分母不一致"
            )
        if any(
            not math.isfinite(value)
            for rows in values.values()
            for value in rows
        ):
            raise ValueError(
                "probability score joint monitor 分數必須為有限值"
            )
        observed_scores[game] = len(main)
        normalized[game] = values

    common_observed = min(observed_scores.values())
    completed = [
        checkpoint
        for checkpoint in PROBABILITY_STACKING_CHECKPOINTS
        if checkpoint <= common_observed
    ]
    base = {
        "protocol_id": PROBABILITY_SCORE_MONITORING_PROTOCOL_ID,
        "experiment_id": SCORE_CAPSULE_EXPERIMENT_ID,
        "observed_scores_by_game": observed_scores,
        "common_observed_scores": common_observed,
        "look_lower_tail_alpha": PROBABILITY_STACKING_LOOK_ALPHA,
        "intersection_union_test": True,
        "historical_backfill_allowed": False,
    }
    if not completed:
        return {
            **base,
            "evaluated_scores_per_game": 0,
            "checkpoint_index": None,
            "next_checkpoint": PROBABILITY_STACKING_CHECKPOINTS[0],
            "games": {},
            "supported": False,
            "final": False,
            "stopped_early": False,
            "completed_looks": [],
            "status": "collecting_forward_data",
        }

    evaluations = []
    supported_evaluation = None
    for checkpoint in completed:
        game_evaluations = {}
        for game in (SUPER, LOTTO649):
            main = normalized[game]["main_information_gain"][
                :checkpoint
            ]
            interval = _block_bootstrap_ci(
                main,
                game=(
                    f"{game}|probability-score|"
                    f"checkpoint{checkpoint}"
                ),
                tail_probability=PROBABILITY_STACKING_LOOK_ALPHA,
                comparison_id=SCORE_CAPSULE_EXPERIMENT_ID,
            )
            special_applicable = game == SUPER
            special_mean = (
                statistics.fmean(
                    normalized[game][
                        "special_information_gain"
                    ][:checkpoint]
                )
                if special_applicable
                else None
            )
            game_evaluations[game] = {
                "observed_prefix_scores": checkpoint,
                "mean_main_information_gain_vs_uniform": (
                    statistics.fmean(main)
                ),
                "ci_low": interval[0] if interval else None,
                "ci_high": interval[1] if interval else None,
                "main_supported": bool(
                    interval and interval[0] > 0
                ),
                "special_applicable": special_applicable,
                "mean_special_information_gain_vs_uniform": (
                    special_mean
                ),
                "special_guardrail_passed": (
                    special_mean >= 0
                    if special_applicable
                    else True
                ),
            }
        supported = all(
            row["main_supported"]
            and row["special_guardrail_passed"]
            for row in game_evaluations.values()
        )
        evaluation = {
            "checkpoint": checkpoint,
            "checkpoint_index": (
                PROBABILITY_STACKING_CHECKPOINTS.index(
                    checkpoint
                )
            ),
            "games": game_evaluations,
            "supported": supported,
        }
        evaluations.append(evaluation)
        if supported:
            supported_evaluation = evaluation
            break

    selected = supported_evaluation or evaluations[-1]
    checkpoint = selected["checkpoint"]
    checkpoint_index = selected["checkpoint_index"]
    supported = selected["supported"]
    final = (
        supported
        or completed[-1] == PROBABILITY_STACKING_CHECKPOINTS[-1]
    )
    return {
        **base,
        "evaluated_scores_per_game": checkpoint,
        "checkpoint_index": checkpoint_index,
        "next_checkpoint": (
            None
            if final
            else PROBABILITY_STACKING_CHECKPOINTS[
                checkpoint_index + 1
            ]
        ),
        "games": selected["games"],
        "supported": supported,
        "final": final,
        "stopped_early": bool(
            supported
            and checkpoint
            != PROBABILITY_STACKING_CHECKPOINTS[-1]
        ),
        "completed_looks": evaluations,
        "status": (
            "supported"
            if supported
            else "not_supported_final"
            if final
            else "collecting_forward_data"
        ),
    }


def _probability_stacking_promotion_gate(
    outcome_monitor: dict,
    score_monitor: dict,
) -> dict:
    outcome_supported = outcome_monitor.get("supported") is True
    score_supported = score_monitor.get("supported") is True
    supported = outcome_supported and score_supported
    rejected_final = (
        outcome_monitor.get("final") is True
        and not outcome_supported
    ) or (
        score_monitor.get("final") is True
        and not score_supported
    )
    if supported:
        status = "supported"
        reason = "outcome_and_probability_calibration_supported"
    elif rejected_final:
        status = "not_supported_final"
        if (
            outcome_monitor.get("final") is True
            and not outcome_supported
        ):
            reason = "outcome_evidence_not_supported_final"
        else:
            reason = "probability_calibration_not_supported_final"
    else:
        status = "collecting_forward_data"
        if outcome_supported:
            reason = "waiting_for_probability_calibration"
        elif score_supported:
            reason = "waiting_for_outcome_evidence"
        else:
            reason = "waiting_for_outcome_and_probability_calibration"
    return {
        "protocol_id": PROBABILITY_STACKING_PROMOTION_GATE_ID,
        "outcome_monitor_protocol_id": (
            PROBABILITY_STACKING_MONITORING_PROTOCOL_ID
        ),
        "probability_score_monitor_protocol_id": (
            PROBABILITY_SCORE_MONITORING_PROTOCOL_ID
        ),
        "outcome_supported": outcome_supported,
        "probability_score_supported": score_supported,
        "requires_both": True,
        "supported": supported,
        "final": supported or rejected_final,
        "status": status,
        "reason": reason,
    }


def verify_registry(ledger: Ledger) -> dict:
    if not ledger.verify_chain():
        raise ValueError("前向實驗 JSONL 雜湊鏈中斷")
    registrations = {}
    settlements = set()
    settlement_contents_seen: list[dict] = []
    previous_target: dict[str, tuple[str, int]] = {}
    for event in ledger.read_all():
        content = _event_content(event)
        if content.get("experiment_id") != FORWARD_EXPERIMENT_ID:
            raise ValueError("前向實驗版本不符")
        if event["type"] == "forward_preregister":
            key = _target_key(content["game"], content["target"])
            if key in registrations:
                raise ValueError("前向帳本重複登記同一期")
            order_key = (content["target"]["date"], content["target"]["period"])
            if (
                content["game"] in previous_target
                and order_key <= previous_target[content["game"]]
            ):
                raise ValueError("前向登記期別未嚴格遞增")
            previous_target[content["game"]] = order_key
            registered_arms = _registered_arms(content)
            for arm_id in registered_arms:
                arm = content["arms"][arm_id]
                _validate_tickets(content["game"], arm["tickets"])
                if arm["selection_hash"] != _selection_hash(
                    content["game"], arm["tickets"]
                ):
                    raise ValueError("前向實驗 selection_hash 不符")
            if ARM_COVERAGE in registered_arms:
                coverage = content["arms"][ARM_COVERAGE]
                metadata = coverage.get("metadata") or {}
                baseline_structure = portfolio_structure(
                    content["game"],
                    content["arms"][ARM_RULE]["tickets"],
                )
                selected_structure = portfolio_structure(
                    content["game"],
                    coverage["tickets"],
                )
                expected_delta = (
                    selected_structure["exact_at_least_three_main"]
                    - baseline_structure["exact_at_least_three_main"]
                )
                expected_any_prize_delta = (
                    selected_structure["exact_any_prize"]
                    - baseline_structure["exact_any_prize"]
                )
                coverage_id = content["coverage_experiment_id"]
                common_invalid = (
                    metadata.get("experiment_id") != coverage_id
                    or metadata.get("source_decision_hash")
                    != content["source_decision_hash"]
                    or not isinstance(
                        metadata.get("candidate_pool_hash"), str
                    )
                    or len(metadata["candidate_pool_hash"]) != 64
                    or metadata.get("baseline_structure")
                    != baseline_structure
                    or metadata.get("selected_structure")
                    != selected_structure
                    or abs(
                        float(
                            metadata.get(
                                "exact_probability_delta",
                                float("inf"),
                            )
                        )
                        - expected_delta
                    )
                    > 1e-15
                    or abs(
                        float(
                            metadata.get(
                                "exact_any_prize_probability_delta",
                                float("inf"),
                            )
                        )
                        - expected_any_prize_delta
                    )
                    > 1e-15
                    or not isinstance(
                        metadata.get("fallback_to_current"), bool
                    )
                    or not isinstance(
                        metadata.get("candidate_structure"), dict
                    )
                )
                if coverage_id == COVERAGE_FORWARD_EXPERIMENT_ID_V1:
                    selected_ids = metadata.get(
                        "selected_proposal_ids"
                    )
                    version_invalid = (
                        coverage.get("source")
                        != "deterministic_coverage_selector"
                        or metadata.get(
                            "source_research_experiment_id"
                        )
                        != COVERAGE_RESEARCH_EXPERIMENT_ID_V1
                        or not isinstance(selected_ids, list)
                        or len(selected_ids) != SELECTED_TICKETS
                        or len(set(selected_ids)) != SELECTED_TICKETS
                        or selected_ids
                        != [
                            ticket["source_proposal"]
                            for ticket in coverage["tickets"]
                        ]
                    )
                    eligible_invalid = (
                        metadata.get("error_type") is not None
                        or metadata.get("combinations_evaluated")
                        != 3_003
                    )
                else:
                    selector_succeeded = (
                        metadata.get("error_type") is None
                    )
                    selected_main_numbers = metadata.get(
                        "selected_main_numbers"
                    )
                    selected_specials = metadata.get(
                        "selected_specials"
                    )
                    flattened_numbers = sorted(
                        number
                        for ticket in coverage["tickets"]
                        for number in ticket["numbers"]
                    )
                    successful_contract_invalid = (
                        not isinstance(
                            metadata.get("support_evidence_hash"),
                            str,
                        )
                        or len(metadata["support_evidence_hash"]) != 64
                        or metadata.get("structural_optimum_proof")
                        != structural_proof_reference()
                        or not isinstance(
                            selected_main_numbers, list
                        )
                        or len(selected_main_numbers) != 30
                        or len(set(selected_main_numbers)) != 30
                        or sorted(selected_main_numbers)
                        != flattened_numbers
                        or selected_structure["main_union_size"] != 30
                        or selected_structure[
                            "maximum_pairwise_main_overlap"
                        ]
                        != 0
                        or metadata.get("fallback_to_current") is not False
                        or metadata.get("candidate_structure")
                        != selected_structure
                        or not isinstance(
                            metadata.get("ticket_debate_support"),
                            list,
                        )
                        or len(metadata["ticket_debate_support"])
                        != SELECTED_TICKETS
                        or not isinstance(
                            metadata.get("construction"), str
                        )
                        or [
                            ticket["source_proposal"]
                            for ticket in coverage["tickets"]
                        ]
                        != [
                            f"consensus-disjoint:{slot}"
                            for slot in range(
                                1, SELECTED_TICKETS + 1
                            )
                        ]
                        or any(
                            ticket["source_agent"]
                            != "consensus_coverage_synthesizer"
                            for ticket in coverage["tickets"]
                        )
                        or (
                            content["game"] == SUPER
                            and (
                                not isinstance(
                                    selected_specials, list
                                )
                                or len(selected_specials)
                                != SELECTED_TICKETS
                                or len(set(selected_specials))
                                != SELECTED_TICKETS
                                or selected_specials
                                != sorted(
                                    ticket["special"]
                                    for ticket in coverage["tickets"]
                                )
                            )
                        )
                        or (
                            content["game"] == LOTTO649
                            and selected_specials is not None
                        )
                    )
                    failed_contract_invalid = (
                        metadata.get("fallback_to_current") is not True
                        or metadata.get("support_evidence_hash")
                        is not None
                        or metadata.get("structural_optimum_proof")
                        is not None
                        or coverage["tickets"]
                        != content["arms"][ARM_RULE]["tickets"]
                    )
                    version_invalid = (
                        coverage.get("source")
                        != "deterministic_consensus_disjoint_selector"
                        or metadata.get(
                            "source_research_experiment_id"
                        )
                        != MAX_COVERAGE_RESEARCH_EXPERIMENT_ID
                        or (
                            selector_succeeded
                            and successful_contract_invalid
                        )
                        or (
                            not selector_succeeded
                            and failed_contract_invalid
                        )
                    )
                    eligible_invalid = not selector_succeeded
                if common_invalid or version_invalid:
                    raise ValueError(
                        "coverage 前向來源或精確機率證明不符"
                    )
                if coverage.get("eligible") and (
                    content.get("late") is not False
                    or eligible_invalid
                    or expected_delta < -1e-15
                    or expected_any_prize_delta < -1e-15
                ):
                    raise ValueError("coverage 前向合格狀態不符")
                if not coverage.get("eligible") and (
                    coverage.get("ineligible_reason")
                    not in {
                        "late_registration",
                        "coverage_not_verified",
                    }
                ):
                    raise ValueError("coverage 前向不合格原因不符")
                shadow = metadata.get("special_frequency_shadow")
                if shadow is not None:
                    shadow_tickets = shadow.get("tickets")
                    candidate = shadow.get("candidate")
                    if (
                        not isinstance(candidate, dict)
                        or
                        content["game"] != SUPER
                        or coverage_id
                        not in {
                            COVERAGE_FORWARD_EXPERIMENT_ID_V2,
                            COVERAGE_FORWARD_EXPERIMENT_ID,
                            COVERAGE_FORWARD_EXPERIMENT_ID_V4,
                            COVERAGE_FORWARD_EXPERIMENT_ID_V5,
                            COVERAGE_FORWARD_EXPERIMENT_ID_V6,
                            COVERAGE_FORWARD_EXPERIMENT_ID_V7,
                        }
                        or not selector_succeeded
                        or shadow.get("experiment_id")
                        != SPECIAL_SHADOW_EXPERIMENT_ID
                        or shadow.get("candidate_hash")
                        != candidate.get("candidate_hash")
                    ):
                        raise ValueError(
                            "第二區 forward shadow 來源不符"
                        )
                    try:
                        verified_candidate = (
                            _validated_mechanism_candidate(candidate)
                        )
                        _validate_tickets(SUPER, shadow_tickets)
                    except (TypeError, ValueError) as exc:
                        raise ValueError(
                            "第二區 forward shadow 票券不符"
                        ) from exc
                    if (
                        verified_candidate != candidate
                        or shadow.get("selection_hash")
                        != _selection_hash(SUPER, shadow_tickets)
                        or shadow.get(
                            "theoretical_structural_probability_unchanged"
                        )
                        is not True
                        or any(
                            ticket["numbers"] != control["numbers"]
                            for ticket, control in zip(
                                shadow_tickets,
                                coverage["tickets"],
                            )
                        )
                        or sorted(
                            ticket["special"]
                            for ticket in shadow_tickets
                        )
                        != sorted(candidate["selected_specials"])
                        or portfolio_structure(
                            SUPER, shadow_tickets
                        )
                        != selected_structure
                    ):
                        raise ValueError(
                            "第二區 forward shadow 結構不符"
                        )
                profit_shadows = metadata.get(
                    "profit_portfolio_shadows"
                )
                profit_error = metadata.get(
                    "profit_portfolio_shadows_error_type"
                )
                if coverage_id in {
                    COVERAGE_FORWARD_EXPERIMENT_ID,
                    COVERAGE_FORWARD_EXPERIMENT_ID_V4,
                    COVERAGE_FORWARD_EXPERIMENT_ID_V5,
                    COVERAGE_FORWARD_EXPERIMENT_ID_V6,
                    COVERAGE_FORWARD_EXPERIMENT_ID_V7,
                }:
                    profit_expected = (
                        content["game"] == SUPER
                        and selector_succeeded
                    )
                    if profit_expected and profit_shadows is not None:
                        if profit_error is not None:
                            raise ValueError(
                                "獲利 forward shadow 不得同時標記錯誤"
                            )
                        try:
                            common_shadow = profit_shadows.get(
                                "common_special_shadow"
                            )
                            common_candidate = (
                                common_shadow.get("candidate")
                                if isinstance(common_shadow, dict)
                                else None
                            )
                            if (
                                coverage_id
                                == COVERAGE_FORWARD_EXPERIMENT_ID_V4
                                and common_candidate is None
                            ):
                                raise ValueError(
                                    "v4 缺少共同第二區 shadow"
                                )
                            if (
                                coverage_id
                                == COVERAGE_FORWARD_EXPERIMENT_ID
                                and common_candidate is not None
                            ):
                                raise ValueError(
                                    "v3 不得含共同第二區 shadow"
                                )
                            verified_profit_shadows = (
                                verify_profit_portfolio_shadows(
                                    profit_shadows,
                                    expected_source_decision_hash=(
                                        content[
                                            "source_decision_hash"
                                        ]
                                    ),
                                    expected_support_evidence_hash=(
                                        metadata[
                                            "support_evidence_hash"
                                        ]
                                    ),
                                    expected_ranked_main_numbers=(
                                        selected_main_numbers
                                    ),
                                    expected_selected_special=(
                                        _profit_shadow_selected_special(
                                            coverage["tickets"],
                                            metadata[
                                                "ticket_debate_support"
                                            ],
                                        )
                                    ),
                                    expected_common_special_candidate=(
                                        common_candidate
                                    ),
                                )
                            )
                        except (KeyError, TypeError, ValueError) as exc:
                            raise ValueError(
                                "獲利 forward shadow 登記不符"
                            ) from exc
                        if verified_profit_shadows != profit_shadows:
                            raise ValueError(
                                "獲利 forward shadow 重建不符"
                            )
                    elif profit_expected:
                        if profit_error not in {
                            "KeyError",
                            "RuntimeError",
                            "TypeError",
                            "ValueError",
                        }:
                            raise ValueError(
                                "獲利 forward shadow 缺失且無明確錯誤"
                            )
                    elif (
                        profit_shadows is not None
                        or profit_error is not None
                    ):
                        raise ValueError(
                            "非合格威力彩不得登記獲利 forward shadow"
                        )
                elif (
                    profit_shadows is not None
                    or profit_error is not None
                ):
                    raise ValueError(
                        "舊 coverage 版本不得事後加入獲利 shadow"
                    )
                probability_shadow = metadata.get(
                    "probability_stacking_shadow"
                )
                probability_error = metadata.get(
                    "probability_stacking_shadow_error_type"
                )
                if coverage_id in {
                    COVERAGE_FORWARD_EXPERIMENT_ID_V5,
                    COVERAGE_FORWARD_EXPERIMENT_ID_V6,
                    COVERAGE_FORWARD_EXPERIMENT_ID_V7,
                }:
                    if probability_shadow is None:
                        raise ValueError(
                            "v5/v6/v7 缺少機率 stacking shadow"
                        )
                    if probability_error is not None:
                        raise ValueError(
                            "機率 stacking shadow 不得同時標記錯誤"
                        )
                    try:
                        verified_probability_shadow = (
                            _validate_probability_stacking_shadow(
                                probability_shadow,
                                game=content["game"],
                                target=content["target"],
                                source_decision_hash=content[
                                    "source_decision_hash"
                                ],
                            )
                        )
                    except (KeyError, TypeError, ValueError) as exc:
                        raise ValueError(
                            "機率 stacking shadow 登記不符"
                        ) from exc
                    if (
                        verified_probability_shadow
                        != probability_shadow
                    ):
                        raise ValueError(
                            "機率 stacking shadow 重建不符"
                        )
                    has_score_capsule = (
                        probability_shadow.get("score_capsule")
                        is not None
                    )
                    if (
                        coverage_id
                        in {
                            COVERAGE_FORWARD_EXPERIMENT_ID_V6,
                            COVERAGE_FORWARD_EXPERIMENT_ID_V7,
                        }
                    ) != has_score_capsule:
                        raise ValueError(
                            "機率 proper-score 版本契約不符"
                        )
                elif probability_shadow is not None:
                    raise ValueError(
                        "舊 coverage 版本不得含機率 stacking shadow"
                    )
                elif probability_error not in {
                    None,
                    "KeyError",
                    "RuntimeError",
                    "TypeError",
                    "ValueError",
                }:
                    raise ValueError(
                        "機率 stacking shadow 錯誤類型不符"
                    )
                null_safe_shadow = metadata.get(
                    "null_safe_probability_shadow"
                )
                null_safe_error = metadata.get(
                    "null_safe_probability_shadow_error_type"
                )
                if coverage_id == COVERAGE_FORWARD_EXPERIMENT_ID_V7:
                    if null_safe_shadow is None:
                        raise ValueError(
                            "v7 缺少 null-safe probability shadow"
                        )
                    if null_safe_error is not None:
                        raise ValueError(
                            "null-safe shadow 不得同時標記錯誤"
                        )
                    try:
                        verified_null_safe_shadow = (
                            _validate_null_safe_probability_shadow(
                                null_safe_shadow,
                                game=content["game"],
                                target=content["target"],
                                source_decision_hash=content[
                                    "source_decision_hash"
                                ],
                                coverage_tickets=coverage["tickets"],
                                baseline_support_evidence_hash=metadata[
                                    "support_evidence_hash"
                                ],
                            )
                        )
                    except (KeyError, TypeError, ValueError) as exc:
                        raise ValueError(
                            "null-safe probability shadow 登記不符"
                        ) from exc
                    if verified_null_safe_shadow != null_safe_shadow:
                        raise ValueError(
                            "null-safe probability shadow 重建不符"
                        )
                elif null_safe_shadow is not None:
                    raise ValueError(
                        "v7 以前不得含 null-safe probability shadow"
                    )
                elif null_safe_error not in {
                    None,
                    "KeyError",
                    "ProbabilityStackingUnavailable",
                    "RuntimeError",
                    "TypeError",
                    "ValueError",
                }:
                    raise ValueError(
                        "null-safe probability shadow 錯誤類型不符"
                    )
            ops_id = content.get("ops_experiment_id")
            qwen = content["arms"][ARM_QWEN]
            metadata = qwen.get("metadata") or {}
            if (
                metadata.get("feedback_provenance") is not None
                and ops_id is None
            ):
                raise ValueError("Qwen 回饋登記缺少運作遙測版本")
            if ops_id is not None:
                if ops_id != OPS_EXPERIMENT_ID:
                    raise ValueError("終局裁判遙測實驗版本不符")
                telemetry = metadata.get("telemetry")
                if (
                    not isinstance(telemetry, dict)
                    or telemetry.get("schema_version") != "1"
                    or telemetry.get("outcome")
                    not in {"success", "error"}
                ):
                    raise ValueError("終局裁判遙測契約不完整")
                if (
                    qwen.get("source") == "ollama"
                    and telemetry.get("outcome") != "success"
                ):
                    raise ValueError("Qwen 成功來源與遙測結果矛盾")
                if (
                    qwen.get("source") != "ollama"
                    and telemetry.get("outcome") != "error"
                ):
                    raise ValueError("Qwen 降級來源與遙測結果矛盾")
                if qwen.get("source") == "ollama":
                    diagnostics = metadata.get("selection_diagnostics")
                    if (
                        not isinstance(diagnostics, dict)
                        or diagnostics.get("schema_version") != "1"
                        or diagnostics.get("selected_count")
                        != SELECTED_TICKETS
                    ):
                        raise ValueError("Qwen 選擇診斷契約不完整")
                feedback_provenance = metadata.get(
                    "feedback_provenance"
                )
                feedback_context = metadata.get("feedback_context")
                if feedback_provenance is not None:
                    if (
                        not isinstance(feedback_provenance, dict)
                        or feedback_provenance.get("experiment_id")
                        != FEEDBACK_EXPERIMENT_ID
                        or feedback_provenance.get("status")
                        not in {
                            "verified",
                            "verified_empty",
                            "not_supplied",
                        }
                    ):
                        raise ValueError("Qwen 回饋來源證明不完整")
                    feedback_status = feedback_provenance["status"]
                    feedback_count = feedback_provenance.get(
                        "settlement_count"
                    )
                    feedback_hash = feedback_provenance.get(
                        "feedback_hash"
                    )
                    source_hashes = feedback_provenance.get(
                        "source_postmortem_hashes"
                    )
                    if (
                        not isinstance(feedback_count, int)
                        or feedback_count < 0
                        or not isinstance(source_hashes, list)
                        or len(source_hashes) != feedback_count
                        or (
                            feedback_status == "verified"
                            and (
                                feedback_count < 1
                                or not isinstance(feedback_hash, str)
                                or len(feedback_hash) != 64
                            )
                        )
                        or (
                            feedback_status == "verified_empty"
                            and (
                                feedback_count != 0
                                or not isinstance(feedback_hash, str)
                                or len(feedback_hash) != 64
                            )
                        )
                        or (
                            feedback_status == "not_supplied"
                            and (
                                feedback_count != 0
                                or feedback_hash is not None
                            )
                        )
                    ):
                        raise ValueError("Qwen 回饋來源證明內容不符")
                    as_of = feedback_provenance.get("as_of_target")
                    if (
                        as_of is not None
                        and (
                            as_of["date"],
                            int(as_of["period"]),
                        )
                        >= (
                            content["target"]["date"],
                            int(content["target"]["period"]),
                        )
                    ):
                        raise ValueError("Qwen 回饋來源含目標期或未來資料")
                    if not isinstance(feedback_context, dict):
                        raise ValueError("Qwen 回饋完整 context 缺失")
                    verify_feedback_context(
                        feedback_context,
                        game=content["game"],
                        target=content["target"],
                    )
                    expected_feedback_context = (
                        build_feedback_context_from_settlements(
                            settlement_contents_seen,
                            content["game"],
                            before_target=content["target"],
                        )
                    )
                    expected_provenance = {
                        "experiment_id": FEEDBACK_EXPERIMENT_ID,
                        "status": (
                            "verified"
                            if expected_feedback_context[
                                "settlement_count"
                            ]
                            > 0
                            else "verified_empty"
                        ),
                        "feedback_hash": expected_feedback_context[
                            "feedback_hash"
                        ],
                        "settlement_count": expected_feedback_context[
                            "settlement_count"
                        ],
                        "as_of_target": expected_feedback_context[
                            "as_of_target"
                        ],
                        "source_postmortem_hashes": (
                            expected_feedback_context[
                                "source_postmortem_hashes"
                            ]
                        ),
                    }
                    if (
                        feedback_context != expected_feedback_context
                        or feedback_provenance != expected_provenance
                    ) and qwen.get("eligible"):
                        raise ValueError(
                            "Qwen 回饋與當時已結算帳本不符"
                        )
                elif feedback_context is not None:
                    raise ValueError("Qwen 回饋 context 缺少來源證明")
            registrations[event["content_hash"]] = content
        elif event["type"] == "forward_settlement":
            registration_hash = content["registration_hash"]
            if registration_hash not in registrations:
                raise ValueError("前向結算找不到先前登記")
            if registration_hash in settlements:
                raise ValueError("前向帳本重複結算同一登記")
            registered = registrations[registration_hash]
            if (
                content["game"] != registered["game"]
                or content["target"] != registered["target"]
            ):
                raise ValueError("前向結算與登記目標不符")
            registered_arms = _registered_arms(registered)
            if set(content.get("arm_results", {})) != set(
                registered_arms
            ):
                raise ValueError("前向結算臂結果與登記不符")
            if ARM_COVERAGE in registered_arms:
                comparison = content.get("coverage_vs_rule")
                coverage_result = content["arm_results"][ARM_COVERAGE]
                rule_result = content["arm_results"][ARM_RULE]
                expected_coverage = {
                    "eligible": (
                        registered["arms"][ARM_COVERAGE]["eligible"]
                        and registered["arms"][ARM_RULE]["eligible"]
                    ),
                    "coverage_minus_rule_best_main_hits": (
                        coverage_result["best_main_hits"]
                        - rule_result["best_main_hits"]
                    ),
                    "coverage_minus_rule_total_main_hits": (
                        coverage_result["total_main_hits"]
                        - rule_result["total_main_hits"]
                    ),
                    "coverage_minus_rule_any_three_plus": (
                        int(coverage_result["any_three_plus"])
                        - int(rule_result["any_three_plus"])
                    ),
                    "coverage_minus_rule_union_main_hits": (
                        coverage_result["union_main_hits"]
                        - rule_result["union_main_hits"]
                    ),
                    "preregistered_exact_probability_delta": (
                        registered["arms"][ARM_COVERAGE]["metadata"][
                            "exact_probability_delta"
                        ]
                    ),
                    "preregistered_any_prize_probability_delta": (
                        registered["arms"][ARM_COVERAGE]["metadata"][
                            "exact_any_prize_probability_delta"
                        ]
                    ),
                    "verdict": (
                        "coverage_win"
                        if coverage_result["best_main_hits"]
                        > rule_result["best_main_hits"]
                        else "rule_win"
                        if coverage_result["best_main_hits"]
                        < rule_result["best_main_hits"]
                        else "tie"
                    ),
                }
                if comparison != expected_coverage:
                    raise ValueError("coverage 前向結算比較不符")
                registered_shadow = registered["arms"][
                    ARM_COVERAGE
                ]["metadata"].get("special_frequency_shadow")
                actual_shadow = content.get(
                    "special_frequency_shadow"
                )
                if registered_shadow is not None:
                    actual = content["actual"]
                    draw = Draw(
                        game=content["game"],
                        period=int(content["target"]["period"]),
                        date=content["target"]["date"],
                        numbers=tuple(actual["numbers"]),
                        special=int(actual["special"]),
                    )
                    shadow_result = _portfolio_result(
                        content["game"],
                        registered_shadow["tickets"],
                        draw,
                    )
                    prize_delta = (
                        int(shadow_result["any_prize"])
                        - int(coverage_result["any_prize"])
                    )
                    expected_shadow = {
                        "experiment_id": registered_shadow[
                            "experiment_id"
                        ],
                        "candidate_hash": registered_shadow[
                            "candidate_hash"
                        ],
                        "selection_hash": registered_shadow[
                            "selection_hash"
                        ],
                        "eligible": registered["arms"][
                            ARM_COVERAGE
                        ]["eligible"],
                        "result": shadow_result,
                        "shadow_minus_coverage_any_prize": (
                            prize_delta
                        ),
                        "shadow_minus_coverage_winning_tickets": (
                            shadow_result["winning_tickets"]
                            - coverage_result["winning_tickets"]
                        ),
                        (
                            "shadow_minus_coverage_"
                            "special_hit_tickets"
                        ): (
                            shadow_result["special_hit_tickets"]
                            - coverage_result["special_hit_tickets"]
                        ),
                        "verdict": (
                            "shadow_win"
                            if prize_delta > 0
                            else "coverage_win"
                            if prize_delta < 0
                            else "tie"
                        ),
                    }
                    if actual_shadow != expected_shadow:
                        raise ValueError(
                            "第二區 forward shadow 結算不符"
                        )
                elif actual_shadow is not None:
                    raise ValueError(
                        "未預註冊第二區 shadow 不得事後結算"
                    )
                registered_profit_shadows = registered["arms"][
                    ARM_COVERAGE
                ]["metadata"].get("profit_portfolio_shadows")
                actual_profit_shadows = content.get(
                    "profit_portfolio_shadows"
                )
                if registered_profit_shadows is not None:
                    actual = content["actual"]
                    draw = Draw(
                        game=content["game"],
                        period=int(content["target"]["period"]),
                        date=content["target"]["date"],
                        numbers=tuple(actual["numbers"]),
                        special=int(actual["special"]),
                    )
                    expected_profit_shadows = (
                        _profit_shadow_settlement(
                            registered_profit_shadows,
                            registered["arms"][ARM_COVERAGE][
                                "tickets"
                            ],
                            eligible=registered["arms"][
                                ARM_COVERAGE
                            ]["eligible"],
                            draw=draw,
                        )
                    )
                    if actual_profit_shadows != expected_profit_shadows:
                        raise ValueError(
                            "獲利 forward shadow 結算不符"
                        )
                elif actual_profit_shadows is not None:
                    raise ValueError(
                        "未預註冊獲利 shadow 不得事後結算"
                    )
                registered_probability_stacking = registered[
                    "arms"
                ][ARM_COVERAGE]["metadata"].get(
                    "probability_stacking_shadow"
                )
                actual_probability_stacking = content.get(
                    "probability_stacking_shadow"
                )
                if registered_probability_stacking is not None:
                    actual = content["actual"]
                    draw = Draw(
                        game=content["game"],
                        period=int(content["target"]["period"]),
                        date=content["target"]["date"],
                        numbers=tuple(actual["numbers"]),
                        special=int(actual["special"]),
                    )
                    expected_probability_stacking = (
                        _probability_stacking_shadow_settlement(
                            registered_probability_stacking,
                            registered["arms"][ARM_COVERAGE][
                                "tickets"
                            ],
                            eligible=registered["arms"][
                                ARM_COVERAGE
                            ]["eligible"],
                            game=content["game"],
                            draw=draw,
                        )
                    )
                    if (
                        actual_probability_stacking
                        != expected_probability_stacking
                    ):
                        raise ValueError(
                            "機率 stacking shadow 結算不符"
                        )
                elif actual_probability_stacking is not None:
                    raise ValueError(
                        "未預註冊機率 stacking shadow 不得事後結算"
                    )
                registered_null_safe = registered["arms"][
                    ARM_COVERAGE
                ]["metadata"].get("null_safe_probability_shadow")
                actual_null_safe = content.get(
                    "null_safe_probability_shadow"
                )
                if registered_null_safe is not None:
                    actual = content["actual"]
                    draw = Draw(
                        game=content["game"],
                        period=int(content["target"]["period"]),
                        date=content["target"]["date"],
                        numbers=tuple(actual["numbers"]),
                        special=int(actual["special"]),
                    )
                    expected_null_safe = (
                        _null_safe_probability_shadow_settlement(
                            registered_null_safe,
                            registered["arms"][ARM_COVERAGE][
                                "tickets"
                            ],
                            eligible=registered["arms"][
                                ARM_COVERAGE
                            ]["eligible"],
                            game=content["game"],
                            draw=draw,
                        )
                    )
                    if actual_null_safe != expected_null_safe:
                        raise ValueError(
                            "null-safe probability shadow 結算不符"
                        )
                    verify_null_safe_score_result(
                        actual_null_safe["proper_score"],
                        game=content["game"],
                    )
                elif actual_null_safe is not None:
                    raise ValueError(
                        "未預註冊 null-safe shadow 不得事後結算"
                    )
            elif "coverage_vs_rule" in content:
                raise ValueError("舊三臂結算不得含 coverage 比較")
            elif "special_frequency_shadow" in content:
                raise ValueError("舊三臂結算不得含第二區 shadow")
            elif "profit_portfolio_shadows" in content:
                raise ValueError("舊三臂結算不得含獲利 shadow")
            elif "probability_stacking_shadow" in content:
                raise ValueError(
                    "舊三臂結算不得含機率 stacking shadow"
                )
            elif "null_safe_probability_shadow" in content:
                raise ValueError(
                    "舊三臂結算不得含 null-safe shadow"
                )
            postmortem = content.get("postmortem")
            if isinstance(postmortem, dict):
                verify_postmortem(postmortem)
                expected_postmortem = build_postmortem(
                    {
                        **registered,
                        "registration_hash": registration_hash,
                    },
                    content["arm_results"],
                    content["qwen_vs_rule"],
                    content.get("profit_portfolio_shadows"),
                    content.get("probability_stacking_shadow"),
                )
                if (
                    postmortem["registration_hash"] != registration_hash
                    or postmortem["game"] != content["game"]
                    or postmortem["target"] != content["target"]
                    or postmortem != expected_postmortem
                ):
                    raise ValueError("前向錯誤診斷與結算來源不符")
            settlements.add(registration_hash)
            settlement_contents_seen.append(content)
        else:
            raise ValueError(f"未知前向帳本事件：{event['type']}")
    return {
        "chain_valid": True,
        "events": len(ledger.read_all()),
        "registrations": len(registrations),
        "settlements": len(settlements),
        "pending": len(registrations) - len(settlements),
    }


def build_summary(ledger: Ledger) -> dict:
    verification = verify_registry(ledger)
    registration_events = ledger.events_of("forward_preregister")
    registrations = {
        event["content_hash"]: _event_content(event)
        for event in registration_events
    }
    settlement_events = ledger.events_of("forward_settlement")
    settlements = [_event_content(event) for event in settlement_events]
    settled_hashes = {
        settlement["registration_hash"] for settlement in settlements
    }

    games = {}
    qwen_streams = {}
    probability_stacking_streams = {}
    probability_score_streams = {}
    for game in (SUPER, LOTTO649):
        game_regs = [
            (registration_hash, content)
            for registration_hash, content in registrations.items()
            if content["game"] == game
        ]
        game_settlements = [
            settlement
            for settlement in settlements
            if settlement["game"] == game
        ]
        eligible = [
            settlement
            for settlement in game_settlements
            if settlement["qwen_vs_rule"]["eligible"]
        ]
        primary = [
            float(
                settlement["qwen_vs_rule"][
                    "qwen_minus_rule_best_main_hits"
                ]
            )
            for settlement in eligible
        ]
        total = [
            float(
                settlement["qwen_vs_rule"][
                    "qwen_minus_rule_total_main_hits"
                ]
            )
            for settlement in eligible
        ]
        qwen_streams[game] = {
            "primary": primary,
            "total": total,
        }
        coverage_eligible = [
            settlement
            for settlement in game_settlements
            if settlement.get("coverage_vs_rule", {}).get("eligible")
        ]
        coverage_primary = [
            float(
                settlement["coverage_vs_rule"][
                    "coverage_minus_rule_best_main_hits"
                ]
            )
            for settlement in coverage_eligible
        ]
        coverage_any_three = [
            float(
                settlement["coverage_vs_rule"][
                    "coverage_minus_rule_any_three_plus"
                ]
            )
            for settlement in coverage_eligible
        ]
        coverage_monitor = _sequential_monitor(
            coverage_primary,
            game=f"{game}|coverage",
        )
        special_shadow_eligible = [
            settlement["special_frequency_shadow"]
            for settlement in game_settlements
            if settlement.get("special_frequency_shadow", {}).get(
                "eligible"
            )
        ]
        special_shadow_prize = [
            float(row["shadow_minus_coverage_any_prize"])
            for row in special_shadow_eligible
        ]
        special_shadow_monitor = _sequential_monitor(
            special_shadow_prize,
            game=f"{game}|special-frequency-shadow",
        )
        special_shadow_verdicts = Counter(
            row["verdict"] for row in special_shadow_eligible
        )
        profit_registrations = [
            content["arms"][ARM_COVERAGE]["metadata"][
                "profit_portfolio_shadows"
            ]
            for _, content in game_regs
            if content["arms"].get(ARM_COVERAGE, {}).get(
                "metadata", {}
            ).get("profit_portfolio_shadows")
            is not None
        ]
        profit_settlements = [
            settlement["profit_portfolio_shadows"]
            for settlement in game_settlements
            if settlement.get("profit_portfolio_shadows", {}).get(
                "eligible"
            )
        ]
        common_special_registrations = [
            shadow["common_special_shadow"]
            for shadow in profit_registrations
            if shadow.get("common_special_shadow") is not None
        ]
        common_special_settlements = [
            shadow["common_special_shadow"]
            for shadow in profit_settlements
            if shadow.get("common_special_shadow", {}).get(
                "eligible"
            )
        ]
        profit_portfolio_summary = {}
        for portfolio_id in PROFIT_PORTFOLIO_IDS:
            rows = [
                settlement["portfolios"][portfolio_id]
                for settlement in profit_settlements
            ]
            profit_deltas = [
                float(
                    row[
                        "shadow_minus_coverage_"
                        "empirical_floor_strict_profit"
                    ]
                )
                for row in rows
            ]
            payout_deltas = [
                float(
                    row[
                        "shadow_minus_coverage_"
                        "empirical_floor_payout_ntd"
                    ]
                )
                for row in rows
            ]
            profit_monitor = _sequential_monitor(
                profit_deltas,
                game=f"{game}|{portfolio_id}",
                comparison_family_size=len(PROFIT_PORTFOLIO_IDS),
            )
            profit_verdicts = Counter(row["verdict"] for row in rows)
            exact_metrics = (
                profit_registrations[-1]["portfolios"][
                    portfolio_id
                ]["exact_metrics"]
                if profit_registrations
                else None
            )
            profit_portfolio_summary[portfolio_id] = {
                "registered_shadows": len(profit_registrations),
                "eligible_pairs": len(rows),
                "exact_metrics": exact_metrics,
                "shadow_strict_profit_count": sum(
                    row["result"][
                        "empirical_floor_stress_strict_profit"
                    ]
                    for row in rows
                ),
                "coverage_strict_profit_count": sum(
                    settlement["coverage_result"][
                        "empirical_floor_stress_strict_profit"
                    ]
                    for settlement in profit_settlements
                ),
                "observed_shadow_strict_profit_rate": (
                    statistics.fmean(
                        int(
                            row["result"][
                                "empirical_floor_stress_strict_profit"
                            ]
                        )
                        for row in rows
                    )
                    if rows
                    else None
                ),
                "observed_coverage_strict_profit_rate": (
                    statistics.fmean(
                        int(
                            settlement["coverage_result"][
                                "empirical_floor_stress_strict_profit"
                            ]
                        )
                        for settlement in profit_settlements
                    )
                    if profit_settlements
                    else None
                ),
                "mean_strict_profit_delta": profit_monitor[
                    "mean_delta"
                ],
                "mean_empirical_floor_payout_delta_ntd": (
                    statistics.fmean(payout_deltas)
                    if payout_deltas
                    else None
                ),
                "shadow_wins": profit_verdicts["shadow_win"],
                "ties": profit_verdicts["tie"],
                "coverage_wins": profit_verdicts[
                    "coverage_win"
                ],
                "minimum_pairs": MIN_PAIRED_DRAWS_PER_GAME,
                "status": (
                    "not_applicable"
                    if game != SUPER
                    else profit_monitor["status"]
                ),
                "sequential_monitor": profit_monitor,
            }
        profit_statuses = {
            row["status"]
            for row in profit_portfolio_summary.values()
        }
        profit_shadow_status = (
            "not_applicable"
            if game != SUPER
            else "supported"
            if "supported" in profit_statuses
            else "not_supported_final"
            if profit_statuses == {"not_supported_final"}
            else "collecting_forward_data"
        )
        common_special_portfolio_summary = {}
        for portfolio_id in PROFIT_PORTFOLIO_IDS:
            rows = [
                settlement["portfolios"][portfolio_id]
                for settlement in common_special_settlements
            ]
            strict_profit_deltas = [
                float(
                    row[
                        "common_special_minus_baseline_"
                        "empirical_floor_strict_profit"
                    ]
                )
                for row in rows
            ]
            net_deltas = [
                float(
                    row[
                        "common_special_minus_baseline_"
                        "empirical_floor_net_ntd"
                    ]
                )
                for row in rows
            ]
            monitor = _sequential_monitor(
                strict_profit_deltas,
                game=(
                    f"{game}|profit-common-special|"
                    f"{portfolio_id}"
                ),
                comparison_family_size=len(PROFIT_PORTFOLIO_IDS),
            )
            verdicts = Counter(row["verdict"] for row in rows)
            common_special_portfolio_summary[portfolio_id] = {
                "registered_shadows": len(
                    common_special_registrations
                ),
                "eligible_pairs": len(rows),
                "common_special_strict_profit_count": sum(
                    int(
                        row["result"][
                            "empirical_floor_stress_strict_profit"
                        ]
                    )
                    for row in rows
                ),
                "baseline_special_strict_profit_count": sum(
                    int(
                        settlement["portfolios"][portfolio_id][
                            "result"
                        ][
                            "empirical_floor_stress_strict_profit"
                        ]
                    )
                    for settlement in profit_settlements
                    if settlement.get(
                        "common_special_shadow", {}
                    ).get("eligible")
                ),
                "mean_strict_profit_delta": monitor["mean_delta"],
                "mean_empirical_floor_net_delta_ntd": (
                    statistics.fmean(net_deltas)
                    if net_deltas
                    else None
                ),
                "common_special_wins": verdicts[
                    "common_special_win"
                ],
                "ties": verdicts["tie"],
                "baseline_special_wins": verdicts[
                    "baseline_special_win"
                ],
                "minimum_pairs": MIN_PAIRED_DRAWS_PER_GAME,
                "status": (
                    "not_applicable"
                    if game != SUPER
                    else monitor["status"]
                ),
                "sequential_monitor": monitor,
            }
        common_special_statuses = {
            row["status"]
            for row in common_special_portfolio_summary.values()
        }
        common_special_status = (
            "not_applicable"
            if game != SUPER
            else "not_registered"
            if not common_special_registrations
            else "supported"
            if "supported" in common_special_statuses
            else "not_supported_final"
            if common_special_statuses == {"not_supported_final"}
            else "collecting_forward_data"
        )
        probability_stacking_registrations = [
            content["arms"][ARM_COVERAGE]["metadata"][
                "probability_stacking_shadow"
            ]
            for _, content in game_regs
            if content["arms"].get(ARM_COVERAGE, {}).get(
                "metadata", {}
            ).get("probability_stacking_shadow")
            is not None
        ]
        probability_stacking_settlements = [
            settlement["probability_stacking_shadow"]
            for settlement in game_settlements
            if settlement.get(
                "probability_stacking_shadow", {}
            ).get("eligible")
        ]
        probability_score_registrations = [
            row
            for row in probability_stacking_registrations
            if row.get("score_capsule") is not None
        ]
        probability_score_settlements = [
            row["proper_score"]
            for row in probability_stacking_settlements
            if row.get("proper_score", {}).get("eligible")
        ]
        null_safe_registrations = [
            content["arms"][ARM_COVERAGE]["metadata"][
                "null_safe_probability_shadow"
            ]
            for _, content in game_regs
            if content["arms"].get(ARM_COVERAGE, {}).get(
                "metadata", {}
            ).get("null_safe_probability_shadow")
            is not None
        ]
        null_safe_settlements = [
            settlement["null_safe_probability_shadow"]
            for settlement in game_settlements
            if settlement.get(
                "null_safe_probability_shadow", {}
            ).get("eligible")
        ]
        null_safe_scores = [
            row["proper_score"]
            for row in null_safe_settlements
            if row.get("proper_score", {}).get("eligible")
        ]
        probability_stacking_streams[game] = {
            "union_main_hits": [
                float(
                    row[
                        "stacking_minus_coverage_"
                        "union_main_hits"
                    ]
                )
                for row in probability_stacking_settlements
            ],
            "best_main_hits": [
                float(
                    row[
                        "stacking_minus_coverage_"
                        "best_main_hits"
                    ]
                )
                for row in probability_stacking_settlements
            ],
            "any_three_plus": [
                float(
                    row[
                        "stacking_minus_coverage_"
                        "any_three_plus"
                    ]
                )
                for row in probability_stacking_settlements
            ],
            "any_prize": [
                float(
                    row[
                        "stacking_minus_coverage_any_prize"
                    ]
                )
                for row in probability_stacking_settlements
            ],
        }
        probability_score_streams[game] = {
            "main_information_gain": [
                -float(row["main_regret_vs_uniform"])
                for row in probability_score_settlements
            ],
            **(
                {
                    "special_information_gain": [
                        -float(row["special_regret_vs_uniform"])
                        for row in probability_score_settlements
                    ]
                }
                if game == SUPER
                else {}
            ),
        }
        probability_stacking_verdicts = Counter(
            row["verdict"]
            for row in probability_stacking_settlements
        )
        probability_score_main_verdicts = Counter(
            row["main_verdict"]
            for row in probability_score_settlements
        )
        probability_score_special_verdicts = Counter(
            row["special_verdict"]
            for row in probability_score_settlements
            if row["special_regret_vs_uniform"] is not None
        )
        null_safe_verdicts = Counter(
            row["verdict"] for row in null_safe_settlements
        )
        null_safe_main_score_verdicts = Counter(
            row["main_safe_verdict"] for row in null_safe_scores
        )
        null_safe_special_score_verdicts = Counter(
            row["special_safe_verdict"]
            for row in null_safe_scores
            if row["special_safe_regret_vs_uniform"] is not None
        )
        qwen_monitor = _sequential_monitor(primary, game=game)
        pending = [
            {
                "target": content["target"],
                "registered_at": content["registered_at"],
                "deadline": content["deadline"],
                "late": content["late"],
                "qwen_eligible": content["arms"][ARM_QWEN]["eligible"],
                "coverage_eligible": content["arms"]
                .get(ARM_COVERAGE, {})
                .get("eligible"),
                "profit_shadows_registered": (
                    content["arms"]
                    .get(ARM_COVERAGE, {})
                    .get("metadata", {})
                    .get("profit_portfolio_shadows")
                    is not None
                ),
                "profit_common_special_shadow_registered": (
                    (
                        content["arms"]
                        .get(ARM_COVERAGE, {})
                        .get("metadata", {})
                        .get("profit_portfolio_shadows")
                        or {}
                    )
                    .get("common_special_shadow")
                    is not None
                ),
                "probability_stacking_shadow_registered": (
                    content["arms"]
                    .get(ARM_COVERAGE, {})
                    .get("metadata", {})
                    .get("probability_stacking_shadow")
                    is not None
                ),
                "null_safe_probability_shadow_registered": (
                    content["arms"]
                    .get(ARM_COVERAGE, {})
                    .get("metadata", {})
                    .get("null_safe_probability_shadow")
                    is not None
                ),
            }
            for registration_hash, content in game_regs
            if registration_hash not in settled_hashes
        ]
        verdicts = Counter(
            settlement["qwen_vs_rule"]["verdict"]
            for settlement in eligible
        )
        games[game] = {
            "game_name": GAME_NAMES[game],
            "registrations": len(game_regs),
            "settlements": len(game_settlements),
            "eligible_qwen_rule_pairs": len(eligible),
            "late_registrations": sum(
                content["late"] for _, content in game_regs
            ),
            "qwen_invalid_registrations": sum(
                not content["arms"][ARM_QWEN]["eligible"]
                and not content["late"]
                for _, content in game_regs
            ),
            "pending": pending,
            "qwen_vs_rule": {
                "mean_best_main_hits_delta": None,
                "mean_total_main_hits_delta": None,
                "observed_mean_best_main_hits_delta": (
                    statistics.fmean(primary) if primary else None
                ),
                "ci_low": None,
                "ci_high": None,
                "qwen_wins": verdicts["qwen_win"],
                "ties": verdicts["tie"],
                "rule_wins": verdicts["rule_win"],
                "minimum_pairs": MIN_PAIRED_DRAWS_PER_GAME,
                "enough_data": False,
                "positive_gate": False,
                "sequential_monitor": qwen_monitor,
            },
            "coverage_vs_rule": {
                "eligible_pairs": len(coverage_eligible),
                "mean_best_main_hits_delta": (
                    coverage_monitor["mean_delta"]
                ),
                "mean_any_three_plus_delta": (
                    statistics.fmean(coverage_any_three)
                    if coverage_any_three
                    else None
                ),
                "ci_low": (
                    coverage_monitor["ci_low"]
                ),
                "ci_high": (
                    coverage_monitor["ci_high"]
                ),
                "minimum_pairs": MIN_PAIRED_DRAWS_PER_GAME,
                "enough_data": (
                    coverage_monitor["evaluated_pairs"] > 0
                ),
                "status": coverage_monitor["status"],
                "sequential_monitor": coverage_monitor,
            },
            "special_frequency_shadow_vs_coverage": {
                "eligible_pairs": len(special_shadow_eligible),
                "mean_any_prize_delta": (
                    special_shadow_monitor["mean_delta"]
                ),
                "ci_low": (
                    special_shadow_monitor["ci_low"]
                ),
                "ci_high": (
                    special_shadow_monitor["ci_high"]
                ),
                "shadow_wins": special_shadow_verdicts[
                    "shadow_win"
                ],
                "ties": special_shadow_verdicts["tie"],
                "coverage_wins": special_shadow_verdicts[
                    "coverage_win"
                ],
                "minimum_pairs": MIN_PAIRED_DRAWS_PER_GAME,
                "enough_data": (
                    special_shadow_monitor["evaluated_pairs"] > 0
                ),
                "status": (
                    "not_applicable"
                    if game != SUPER
                    else special_shadow_monitor["status"]
                ),
                "sequential_monitor": special_shadow_monitor,
            },
            "profit_portfolio_shadows_vs_coverage": {
                "experiment_id": PROFIT_SHADOW_EXPERIMENT_ID,
                "status": profit_shadow_status,
                "portfolios": profit_portfolio_summary,
            },
            "profit_common_special_shadow_vs_baseline": {
                "experiment_id": (
                    COMMON_SPECIAL_SHADOW_EXPERIMENT_ID
                ),
                "status": common_special_status,
                "registered_shadows": len(
                    common_special_registrations
                ),
                "selected_special": (
                    common_special_registrations[-1][
                        "selected_special"
                    ]
                    if common_special_registrations
                    else None
                ),
                "portfolios": common_special_portfolio_summary,
            },
            "probability_stacking_shadow_vs_coverage": {
                "experiment_id": (
                    PROBABILITY_STACKING_EXPERIMENT_ID
                ),
                "registered_shadows": len(
                    probability_stacking_registrations
                ),
                "eligible_pairs": len(
                    probability_stacking_settlements
                ),
                "candidate_hash": (
                    probability_stacking_registrations[-1][
                        "candidate_hash"
                    ]
                    if probability_stacking_registrations
                    else None
                ),
                "stacking_wins": probability_stacking_verdicts[
                    "stacking_win"
                ],
                "ties": probability_stacking_verdicts["tie"],
                "coverage_wins": probability_stacking_verdicts[
                    "coverage_win"
                ],
                "minimum_pairs": MIN_PAIRED_DRAWS_PER_GAME,
                "status": "collecting_forward_data",
                "joint_checkpoint_evaluation": None,
                "probability_score_vs_uniform": {
                    "experiment_id": SCORE_CAPSULE_EXPERIMENT_ID,
                    "registered_capsules": len(
                        probability_score_registrations
                    ),
                    "eligible_scores": len(
                        probability_score_settlements
                    ),
                    "mean_main_log_loss": (
                        statistics.fmean(
                            float(row["main_log_loss"])
                            for row in probability_score_settlements
                        )
                        if probability_score_settlements
                        else None
                    ),
                    "mean_uniform_main_log_loss": (
                        statistics.fmean(
                            float(row["uniform_main_log_loss"])
                            for row in probability_score_settlements
                        )
                        if probability_score_settlements
                        else None
                    ),
                    "mean_main_regret_vs_uniform": (
                        statistics.fmean(
                            float(row["main_regret_vs_uniform"])
                            for row in probability_score_settlements
                        )
                        if probability_score_settlements
                        else None
                    ),
                    "mean_main_information_gain_vs_uniform": (
                        statistics.fmean(
                            -float(row["main_regret_vs_uniform"])
                            for row in probability_score_settlements
                        )
                        if probability_score_settlements
                        else None
                    ),
                    "main_verdict_counts": dict(
                        sorted(
                            probability_score_main_verdicts.items()
                        )
                    ),
                    "special_applicable": game == SUPER,
                    "mean_special_regret_vs_uniform": (
                        statistics.fmean(
                            float(row["special_regret_vs_uniform"])
                            for row in probability_score_settlements
                        )
                        if game == SUPER
                        and probability_score_settlements
                        else None
                    ),
                    "mean_special_information_gain_vs_uniform": (
                        statistics.fmean(
                            -float(row["special_regret_vs_uniform"])
                            for row in probability_score_settlements
                        )
                        if game == SUPER
                        and probability_score_settlements
                        else None
                    ),
                    "special_verdict_counts": dict(
                        sorted(
                            probability_score_special_verdicts.items()
                        )
                    ),
                    "status": "collecting_forward_data",
                    "joint_checkpoint_evaluation": None,
                },
            },
            "null_safe_probability_shadow": {
                "experiment_id": (
                    NULL_SAFE_PROBABILITY_EXPERIMENT_ID
                ),
                "score_capsule_experiment_id": (
                    NULL_SAFE_SCORE_CAPSULE_EXPERIMENT_ID
                ),
                "registered_shadows": len(null_safe_registrations),
                "eligible_scores": len(null_safe_scores),
                "candidate_hash": (
                    null_safe_registrations[-1]["candidate_hash"]
                    if null_safe_registrations
                    else None
                ),
                "historical_backfill_allowed": False,
                "main_gate_activations_at_registration": sum(
                    bool(row["main_gate_active"])
                    for row in null_safe_registrations
                ),
                "special_gate_activations_at_registration": (
                    sum(
                        bool(row["special_gate_active"])
                        for row in null_safe_registrations
                    )
                    if game == SUPER
                    else None
                ),
                "mean_main_safe_log_loss": (
                    statistics.fmean(
                        float(row["main_safe_log_loss"])
                        for row in null_safe_scores
                    )
                    if null_safe_scores
                    else None
                ),
                "mean_uniform_main_log_loss": (
                    statistics.fmean(
                        float(row["uniform_main_log_loss"])
                        for row in null_safe_scores
                    )
                    if null_safe_scores
                    else None
                ),
                "mean_main_safe_regret_vs_uniform": (
                    statistics.fmean(
                        float(
                            row[
                                "main_safe_regret_vs_uniform"
                            ]
                        )
                        for row in null_safe_scores
                    )
                    if null_safe_scores
                    else None
                ),
                "main_safe_verdict_counts": dict(
                    sorted(null_safe_main_score_verdicts.items())
                ),
                "mean_special_safe_regret_vs_uniform": (
                    statistics.fmean(
                        float(
                            row[
                                "special_safe_regret_vs_uniform"
                            ]
                        )
                        for row in null_safe_scores
                    )
                    if game == SUPER and null_safe_scores
                    else None
                ),
                "special_safe_verdict_counts": dict(
                    sorted(
                        null_safe_special_score_verdicts.items()
                    )
                ),
                "latest_main_updated_e_process": (
                    null_safe_scores[-1][
                        "main_updated_e_process"
                    ]
                    if null_safe_scores
                    else null_safe_registrations[-1][
                        "score_capsule"
                    ]["main_prior_e_process"]
                    if null_safe_registrations
                    else None
                ),
                "latest_special_updated_e_process": (
                    null_safe_scores[-1][
                        "special_updated_e_process"
                    ]
                    if game == SUPER and null_safe_scores
                    else null_safe_registrations[-1][
                        "score_capsule"
                    ]["special_prior_e_process"]
                    if game == SUPER and null_safe_registrations
                    else None
                ),
                "null_safe_wins": null_safe_verdicts[
                    "null_safe_win"
                ],
                "ties": null_safe_verdicts["tie"],
                "coverage_wins": null_safe_verdicts[
                    "coverage_win"
                ],
                "status": "collecting_forward_data",
            },
        }

    qwen_joint_monitor = _joint_qwen_monitor(qwen_streams)
    probability_stacking_joint_monitor = (
        _joint_probability_stacking_monitor(
            probability_stacking_streams
        )
    )
    probability_score_joint_monitor = (
        _joint_probability_score_monitor(
            probability_score_streams
        )
    )
    probability_stacking_promotion_gate = (
        _probability_stacking_promotion_gate(
            probability_stacking_joint_monitor,
            probability_score_joint_monitor,
        )
    )
    for game in (SUPER, LOTTO649):
        joint_game = qwen_joint_monitor["games"].get(game)
        qwen_summary = games[game]["qwen_vs_rule"]
        qwen_summary["joint_checkpoint_evaluation"] = joint_game
        qwen_summary["mean_best_main_hits_delta"] = (
            joint_game["mean_best_main_hits_delta"]
            if joint_game
            else None
        )
        qwen_summary["mean_total_main_hits_delta"] = (
            joint_game["mean_total_main_hits_delta"]
            if joint_game
            else None
        )
        qwen_summary["ci_low"] = (
            joint_game["ci_low"] if joint_game else None
        )
        qwen_summary["ci_high"] = (
            joint_game["ci_high"] if joint_game else None
        )
        qwen_summary["enough_data"] = joint_game is not None
        qwen_summary["positive_gate"] = bool(
            qwen_joint_monitor["supported"]
            and joint_game
            and joint_game["primary_supported"]
            and joint_game["total_guardrail_passed"]
        )
        stacking_joint_game = (
            probability_stacking_joint_monitor["games"].get(game)
        )
        stacking_summary = games[game][
            "probability_stacking_shadow_vs_coverage"
        ]
        stacking_summary["status"] = (
            probability_stacking_joint_monitor["status"]
        )
        stacking_summary["joint_checkpoint_evaluation"] = (
            stacking_joint_game
        )
        probability_score_joint_game = (
            probability_score_joint_monitor["games"].get(game)
        )
        probability_score_summary = stacking_summary[
            "probability_score_vs_uniform"
        ]
        probability_score_summary["status"] = (
            probability_score_joint_monitor["status"]
        )
        probability_score_summary[
            "joint_checkpoint_evaluation"
        ] = probability_score_joint_game
    if qwen_joint_monitor["supported"]:
        evidence_status = "qwen_advantage_supported"
        recommendation = "qwen_supported_with_rule_shadow"
    elif qwen_joint_monitor["final"]:
        evidence_status = "qwen_advantage_not_supported"
        recommendation = "keep_rule_as_control"
    else:
        evidence_status = "collecting_forward_data"
        recommendation = "keep_rule_as_control"
    operations = build_observatory(
        registrations,
        settlements,
        performance_status=evidence_status,
    )
    feedback_memory = {}
    for game in (SUPER, LOTTO649):
        pending = games[game]["pending"]
        before_target = (
            pending[-1]["target"]
            if pending
            else {"date": "9999-12-31", "period": 9_999_999_999}
        )
        feedback_memory[game] = build_feedback_context(
            ledger,
            game,
            before_target=before_target,
        )
    return {
        "schema_version": "1",
        "experiment_id": FORWARD_EXPERIMENT_ID,
        "generated_at": now_iso(),
        "verification": verification,
        "methodology": {
            "arms": list(ARMS),
            "selection_budget": "每臂每期固定五注",
            "primary_metric": "best_main_hits",
            "monitoring_protocol_id": MONITORING_PROTOCOL_ID,
            "probability_score_monitoring_protocol_id": (
                PROBABILITY_SCORE_MONITORING_PROTOCOL_ID
            ),
            "probability_stacking_promotion_gate_id": (
                PROBABILITY_STACKING_PROMOTION_GATE_ID
            ),
            "minimum_paired_draws_per_game": MIN_PAIRED_DRAWS_PER_GAME,
            "monitoring_checkpoints": list(MONITORING_CHECKPOINTS),
            "monitoring_family_lower_tail_alpha": (
                MONITORING_FAMILY_LOWER_TAIL_ALPHA
            ),
            "monitoring_look_lower_tail_alpha": (
                MONITORING_LOOK_LOWER_TAIL_ALPHA
            ),
            "bootstrap_block_draws": BOOTSTRAP_BLOCK_DRAWS,
            "bootstrap_samples": BOOTSTRAP_SAMPLES,
            "promotion_rule": (
                "只在 52/104/208/416/832 個合格配對 checkpoint "
                "檢查；五次 look 各花 lower-tail alpha=0.005，"
                "合計不超過 0.025。只評估兩款遊戲都完成的共同"
                " checkpoint；同一 checkpoint 的 Qwen 相對規則"
                "最佳主號命中差區間下界皆大於 0，且總主號命中"
                "差皆不為負。不得拼接不同 checkpoint。"
            ),
            "coverage_shadow_rule": (
                "coverage v2 只作新前向 shadow；依 Agent 辯論支持合成"
                "30 個互斥主號；有限整數證明確認此結構全域最大，且"
                "每期開獎前完整任一獎級與三主號的精確機率都不得低於"
                "規則臂；只在共同預註冊 checkpoint 檢查"
                "最佳主號命中差區間。"
            ),
            "special_frequency_shadow_rule": (
                "威力彩在 coverage 四臂之外保留相同 30 主號與分組，"
                "只凍結歷史第二區候選作配對子影子；不替換 coverage"
                " 號碼，只在共同預註冊 checkpoint 檢查；任一獎"
                "差區間下界大於 0 才可重新審查。"
            ),
            "profit_portfolio_shadow_rule": (
                "coverage v3 對威力彩另凍結兩個純模擬子影子：guarded "
                "取辯論前 20 名映射到每對票共享一碼的 K5 結構；"
                "unconstrained 取前 10 名映射到十個三票 membership。"
                "兩者只對新登記生效，使用同一個開獎前辯論排序與同一"
                "五注成本；未達共同 checkpoint 不宣告前向勝負。"
                "兩結構共用 comparison family，每個結構每次 look "
                "lower-tail alpha=0.0025，十次檢查合計不超過 0.025。"
            ),
            "profit_common_special_shadow_rule": (
                "coverage v4 保留 guarded／unconstrained 主號結構，"
                "只把 development 凍結的共同第二區與當期辯論 "
                "baseline 作新期數 paired shadow；兩種結構分別在"
                "固定 checkpoint 檢查嚴格獲利事件差，不回填；"
                "同樣以兩比較 family 將每次 look alpha 固定為 0.0025。"
            ),
            "probability_stacking_shadow_rule": (
                "coverage v5 只對新登記凍結七專家 proper-score 線上縮權後的"
                "五注，與正式 coverage 作同一期配對；既有完整歷史只初始化"
                "權重，不作升級證據。兩款遊戲只在共同 "
                "52/104/208/416/832 checkpoint 檢查：30 號聯集主號命中"
                "差的 13 期 circular moving-block bootstrap 下界都須大於 "
                "0，且最佳單注主號、三中以上與任一獎平均差皆不得為負。"
                "每遊戲每次 look lower-tail alpha=0.005。coverage v6 再於"
                "開獎前封存完整機率質量，揭曉後以 log loss 對均勻基準"
                "計算 regret，並以無號碼摘要回饋；兩版本都不得回填。"
            ),
            "probability_score_promotion_rule": (
                "v6 proper score 只累積開獎前已封存且 eligible 的新樣本；"
                "主號資訊增益定義為 uniform log loss 減 model log loss。"
                "兩款遊戲必須在同一個 52/104/208/416/832 checkpoint "
                "都有 bootstrap 下界大於 0，且威力彩第二區平均資訊增益不得為負。"
                "stacking 的命中結果 monitor 與 probability-score monitor "
                "必須都 supported，promotion gate 才能通過；禁止歷史回填。"
            ),
            "null_safe_probability_rule": (
                "coverage v7 同時封存安全預測分布、未開牌 stacking "
                "證據分布與 reveal 前 e-process state。當 prior e-value "
                "未達 family-wise 門檻 60，安全分布必須精確均勻且票券"
                "沿用 consensus coverage；揭曉後以完整合法六號子集 "
                 "log loss 計分，只有證據分布的 likelihood ratio 能更新"
                 "下一期 gate。當期 gate 不得讀取當期 reveal，既有 v6 "
                 "登記不得回填 v7 capsule，也不得推進 e-process。"
                 "operational state 每次由凍結基線加上完整 v7 結算"
                 "帳本決定性重建，重跑或晚到結算不得重複或漏算。"
             ),
        },
        "evidence_status": evidence_status,
        "recommendation": recommendation,
        "qwen_joint_sequential_monitor": qwen_joint_monitor,
        "probability_stacking_joint_sequential_monitor": (
            probability_stacking_joint_monitor
        ),
        "probability_score_joint_sequential_monitor": (
            probability_score_joint_monitor
        ),
        "probability_stacking_promotion_gate": (
            probability_stacking_promotion_gate
        ),
        "operations": operations,
        "feedback_memory": feedback_memory,
        "games": games,
        "honesty_note": (
            "只統計開獎前已存在且未逾截止時間的 Qwen/規則配對；"
            "漏登、晚登與 Qwen 降級期不補做、不冒充有效樣本。"
        ),
    }


def _write_snapshot(path: Path, summary: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temp, path)


def forward_ledger(base: Path) -> Ledger:
    return Ledger(
        Path(base) / "simulation" / "forward" / "ledger.jsonl"
    )


def _mechanism_candidate_from_artifact(base: Path) -> dict | None:
    path = (
        Path(base)
        / "research"
        / "results"
        / "mechanism_signal.json"
    )
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
        candidate = result["future_forward_shadow_candidate"]
        return _validated_mechanism_candidate(candidate)
    except (
        KeyError,
        OSError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ):
        return None


def _profit_common_special_candidate_from_artifact(
    base: Path,
) -> dict | None:
    path = (
        Path(base)
        / "research"
        / "results"
        / "mechanism_signal.json"
    )
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
        candidate = result[
            "future_profit_common_special_shadow_candidate"
        ]
        return validate_common_special_candidate(candidate)
    except (
        KeyError,
        OSError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ):
        return None


def _probability_stacking_candidate_from_artifact(
    base: Path,
) -> dict | None:
    path = (
        Path(base)
        / "research"
        / "results"
        / "probability_stacking.json"
    )
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
        candidate = result["future_forward_shadow_candidate"]
        return validate_probability_stacking_candidate(candidate)
    except (
        KeyError,
        OSError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ):
        return None


def _null_safe_probability_candidate_from_artifact(
    base: Path,
) -> dict | None:
    results_dir = (
        Path(base)
        / "research"
        / "results"
    )
    forward_path = results_dir / "null_safe_probability_forward.json"
    if forward_path.exists():
        try:
            result = validate_null_safe_probability_forward_state(
                json.loads(forward_path.read_text(encoding="utf-8"))
            )
            return validate_null_safe_probability_candidate(
                result["future_forward_shadow_candidate"]
            )
        except (
            KeyError,
            OSError,
            json.JSONDecodeError,
            TypeError,
            ValueError,
        ):
            return None
    formal_path = results_dir / "null_safe_probability.json"
    try:
        result = json.loads(formal_path.read_text(encoding="utf-8"))
        return validate_null_safe_probability_candidate(
            result["future_forward_shadow_candidate"]
        )
    except (
        KeyError,
        OSError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ):
        return None


def feedback_for_target(
    base: Path,
    game: str,
    target: dict,
) -> dict:
    ledger = forward_ledger(base)
    verify_registry(ledger)
    return build_feedback_context(
        ledger,
        game,
        before_target=target,
    )


def settle_forward_registry(
    base: Path,
    store,
) -> dict:
    """只結算已揭曉舊登記，供下一輪裁決前先建立回饋記憶。"""
    base = Path(base)
    forward_dir = base / "simulation" / "forward"
    ledger = forward_ledger(base)
    verify_registry(ledger)
    settled = settle_ready(ledger, store)
    summary = build_summary(ledger)
    _write_snapshot(forward_dir / "status.json", summary)
    return {
        "settlements_created": len(settled),
        "summary": summary,
        "ledger_path": str(ledger.path),
        "status_path": str(forward_dir / "status.json"),
    }


def reconcile_forward_registry(
    base: Path,
    store,
    manifest: dict,
    *,
    registered_at: str | None = None,
) -> dict:
    """先結算已有揭曉，再凍結 manifest 的兩款下一期決策。"""
    base = Path(base)
    forward_dir = base / "simulation" / "forward"
    settled_result = settle_forward_registry(base, store)
    ledger = forward_ledger(base)
    mechanism_candidate = _mechanism_candidate_from_artifact(base)
    profit_common_special_candidate = (
        _profit_common_special_candidate_from_artifact(base)
    )
    probability_stacking_candidate = (
        _probability_stacking_candidate_from_artifact(base)
    )
    null_safe_probability_candidate = (
        _null_safe_probability_candidate_from_artifact(base)
    )
    registrations = {}
    for game in (SUPER, LOTTO649):
        decision = manifest["games"][game]["next_decision"]
        registrations[game] = preregister_decision(
            ledger,
            decision,
            registered_at=registered_at,
            mechanism_candidate=(
                mechanism_candidate if game == SUPER else None
            ),
            profit_common_special_candidate=(
                profit_common_special_candidate
                if game == SUPER
                else None
            ),
            probability_stacking_candidate=(
                probability_stacking_candidate
            ),
            null_safe_probability_candidate=(
                null_safe_probability_candidate
            ),
        )
    summary = build_summary(ledger)
    _write_snapshot(forward_dir / "status.json", summary)
    return {
        "settlements_created": settled_result["settlements_created"],
        "registrations": {
            game: {
                "status": result["status"],
                "registration_hash": result["registration_hash"],
            }
            for game, result in registrations.items()
        },
        "summary": summary,
        "ledger_path": str(ledger.path),
        "status_path": str(forward_dir / "status.json"),
    }
