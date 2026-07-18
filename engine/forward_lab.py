"""下一期終局裁判的前向 A/B 純模擬。

每個目標期在開獎前同時凍結三個固定五注臂：

- ``rule_five``：15 組提案經可重現規則裁決選出的五注。
- ``qwen_five``：同一批提案經本機 qwen3:8b 終局裁判改選的五注。
- ``random_five``：同一期固定種子的均勻隨機五注。

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
from .games import (
    GAME_NAMES,
    LOTTO649,
    PICK_N,
    POOL,
    SPECIAL_POOL,
    SUPER,
    Draw,
    match_tier,
    validate_pick,
)
from .ledger import Ledger, TAIPEI, now_iso
from .seeds import seed_int


FORWARD_EXPERIMENT_ID = "final-judge-forward-v1"
ARM_RULE = "rule_five"
ARM_QWEN = "qwen_five"
ARM_RANDOM = "random_five"
ARMS = (ARM_RULE, ARM_QWEN, ARM_RANDOM)
SELECTED_TICKETS = 5
DRAW_CUTOFF_TIME = "20:30:00"
MIN_PAIRED_DRAWS_PER_GAME = 52
BOOTSTRAP_BLOCK_DRAWS = 13
BOOTSTRAP_SAMPLES = 2_000


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
) -> dict:
    """凍結單一遊戲下一期三臂；同一期再次呼叫為冪等 no-op。"""
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
    judge = decision["adjudication"]["judge"]
    qwen_valid = (
        judge.get("source") == "ollama"
        and judge.get("model") == "qwen3:8b"
        and len(judge.get("selected_proposal_ids", [])) == SELECTED_TICKETS
    )
    common_eligible = not late
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
        "arms": arms,
        "honesty_note": (
            "三臂在開獎前同時凍結；若沒有本事件，開獎後不得補做該期比較。"
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
        arm_results = {
            arm_id: _portfolio_result(
                preregistered["game"],
                preregistered["arms"][arm_id]["tickets"],
                draw,
            )
            for arm_id in ARMS
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
            "interpretation": (
                "本期只量化已凍結三臂與實際開獎的落差；"
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
    differences: list[float], *, game: str
) -> tuple[float, float] | None:
    if len(differences) < 2:
        return None
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
            f"{FORWARD_EXPERIMENT_ID}|{game}|qwen-vs-rule|"
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
    return _quantile(means, 0.025), _quantile(means, 0.975)


def verify_registry(ledger: Ledger) -> dict:
    if not ledger.verify_chain():
        raise ValueError("前向實驗 JSONL 雜湊鏈中斷")
    registrations = {}
    settlements = set()
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
            for arm_id in ARMS:
                arm = content["arms"][arm_id]
                _validate_tickets(content["game"], arm["tickets"])
                if arm["selection_hash"] != _selection_hash(
                    content["game"], arm["tickets"]
                ):
                    raise ValueError("前向實驗 selection_hash 不符")
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
            settlements.add(registration_hash)
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
    all_games_ready = True
    all_games_positive = True
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
        interval = _block_bootstrap_ci(primary, game=game)
        enough = len(primary) >= MIN_PAIRED_DRAWS_PER_GAME
        positive = (
            enough
            and interval is not None
            and interval[0] > 0
            and statistics.fmean(total) >= 0
        )
        all_games_ready = all_games_ready and enough
        all_games_positive = all_games_positive and positive
        pending = [
            {
                "target": content["target"],
                "registered_at": content["registered_at"],
                "deadline": content["deadline"],
                "late": content["late"],
                "qwen_eligible": content["arms"][ARM_QWEN]["eligible"],
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
                "mean_best_main_hits_delta": (
                    statistics.fmean(primary) if primary else None
                ),
                "mean_total_main_hits_delta": (
                    statistics.fmean(total) if total else None
                ),
                "ci_low": interval[0] if interval else None,
                "ci_high": interval[1] if interval else None,
                "qwen_wins": verdicts["qwen_win"],
                "ties": verdicts["tie"],
                "rule_wins": verdicts["rule_win"],
                "minimum_pairs": MIN_PAIRED_DRAWS_PER_GAME,
                "enough_data": enough,
                "positive_gate": positive,
            },
        }

    if not all_games_ready:
        evidence_status = "collecting_forward_data"
        recommendation = "keep_rule_as_control"
    elif all_games_positive:
        evidence_status = "qwen_advantage_supported"
        recommendation = "qwen_supported_with_rule_shadow"
    else:
        evidence_status = "qwen_advantage_not_supported"
        recommendation = "keep_rule_as_control"
    return {
        "schema_version": "1",
        "experiment_id": FORWARD_EXPERIMENT_ID,
        "generated_at": now_iso(),
        "verification": verification,
        "methodology": {
            "arms": list(ARMS),
            "selection_budget": "每臂每期固定五注",
            "primary_metric": "best_main_hits",
            "minimum_paired_draws_per_game": MIN_PAIRED_DRAWS_PER_GAME,
            "bootstrap_block_draws": BOOTSTRAP_BLOCK_DRAWS,
            "bootstrap_samples": BOOTSTRAP_SAMPLES,
            "promotion_rule": (
                "兩款遊戲各至少 52 個合格前向配對，Qwen 相對規則的最佳主號"
                "命中差 95% 區間下界皆大於 0，且總主號命中差皆不為負。"
            ),
        },
        "evidence_status": evidence_status,
        "recommendation": recommendation,
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
    ledger = Ledger(forward_dir / "ledger.jsonl")
    verify_registry(ledger)
    settled = settle_ready(ledger, store)
    registrations = {}
    for game in (SUPER, LOTTO649):
        decision = manifest["games"][game]["next_decision"]
        registrations[game] = preregister_decision(
            ledger,
            decision,
            registered_at=registered_at,
        )
    summary = build_summary(ledger)
    _write_snapshot(forward_dir / "status.json", summary)
    return {
        "settlements_created": len(settled),
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
