"""逐期多 agent 辯論模擬閉環。

流程：
1. 每個 agent 只看目標期以前的歷史，各提三組候選。
2. agent 交叉評議其他人的候選；裁決器依評議、既有可信度與組合分散度選五注。
3. 開獎揭曉後才計分、產生錯誤分析並更新 agent 可信度。
4. 更新後的狀態只供下一期使用。

這是可重現的純模擬，不把歷史關聯描述成開獎因果，也不寫入正式 v1 帳本。
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import random
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

from . import config
from .analysts import NAMES, PERSONAS
from .games import (
    DRAW_WEEKDAYS,
    GAME_NAMES,
    LOTTO649,
    POOL,
    SPECIAL_POOL,
    SUPER,
    Draw,
    match_tier,
    validate_pick,
)
from .seeds import seed_int
from .stats import gaps, main_freq

LOOP_EXPERIMENT_ID = "agent-loop-v1"
AGENT_IDS = tuple(sorted(PERSONAS))
PROPOSALS_PER_AGENT = 3
SELECTED_TICKETS = 5
LEARNING_RATE = 0.18
RATING_RANGE = (0.50, 1.50)


def canonical_hash(payload: dict) -> str:
    raw = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def target_from_draw(draw: Draw) -> dict:
    return {"date": draw.date, "period": draw.period}


def next_target(game: str, latest: Draw) -> dict:
    """依遊戲固定開獎日推進到資料庫最新一期之後的下一個目標日。"""
    current = date.fromisoformat(latest.date)
    for offset in range(1, 8):
        candidate = current + timedelta(days=offset)
        if candidate.weekday() in DRAW_WEEKDAYS[game]:
            roc_year = candidate.year - 1911
            latest_roc_year = latest.period // 1_000_000
            period = (
                latest.period + 1
                if latest_roc_year == roc_year
                else roc_year * 1_000_000 + 1
            )
            return {"date": candidate.isoformat(), "period": period}
    raise AssertionError("七日內找不到下一個固定開獎日")


def initial_state() -> dict:
    return {
        "experiment_id": LOOP_EXPERIMENT_ID,
        "draws_reviewed": 0,
        "agents": {
            agent: {
                "rating": 1.0,
                "reviews": 0,
                "cumulative_best_main_hits": 0,
                "cumulative_special_hits": 0,
            }
            for agent in AGENT_IDS
        },
    }


def _state_snapshot(state: dict) -> dict:
    return {
        "draws_reviewed": int(state["draws_reviewed"]),
        "agents": {
            agent: {
                "rating": float(state["agents"][agent]["rating"]),
                "reviews": int(state["agents"][agent]["reviews"]),
                "cumulative_best_main_hits": int(
                    state["agents"][agent]["cumulative_best_main_hits"]
                ),
                "cumulative_special_hits": int(
                    state["agents"][agent]["cumulative_special_hits"]
                ),
            }
            for agent in AGENT_IDS
        },
    }


def _validate_history(game: str, target: dict, history: list[Draw]) -> None:
    previous = None
    target_key = (target["date"], int(target["period"]))
    for draw in history:
        if draw.game != game:
            raise ValueError(f"歷史含其他遊戲：{draw.game}")
        key = (draw.date, draw.period)
        if previous is not None and key <= previous:
            raise ValueError("歷史必須依日期、期別嚴格遞增")
        if key >= target_key:
            raise ValueError("偵測到目標期或未來資料洩漏")
        previous = key


def _proposal_rng(
    game: str, target: dict, agent: str, variant: int, retry: int
) -> random.Random:
    seed = (
        f"lotto-lab-agent-loop|{LOOP_EXPERIMENT_ID}|{game}|"
        f"{target['date']}|period{target['period']}|proposal|{agent}|"
        f"variant{variant}|retry{retry}"
    )
    return random.Random(seed_int(seed))


def _structural_features(game: str, numbers: list[int]) -> dict:
    lo, hi = config.BALANCE["SUM_BAND"][game]
    odd = sum(number % 2 for number in numbers)
    pairs = sum(1 for left, right in zip(numbers, numbers[1:]) if right - left == 1)
    tails = len({number % 10 for number in numbers})
    number_range = numbers[-1] - numbers[0]
    return {
        "sum": sum(numbers),
        "sum_in_band": lo <= sum(numbers) <= hi,
        "odd": odd,
        "odd_in_band": config.BALANCE["ODD_RANGE"][0]
        <= odd
        <= config.BALANCE["ODD_RANGE"][1],
        "consecutive_pairs": pairs,
        "consecutive_ok": pairs <= config.BALANCE["MAX_CONSECUTIVE_PAIRS"],
        "tail_kinds": tails,
        "tails_ok": tails >= config.BALANCE["MIN_TAIL_KINDS"],
        "range": number_range,
        "range_ok": number_range >= config.BALANCE["MIN_RANGE"],
    }


def _argument(
    agent: str, game: str, history: list[Draw], ticket: dict
) -> tuple[str, dict]:
    numbers = ticket["numbers"]
    if agent == "random_monk":
        return (
            "均勻抽樣不假設歷史能改變下一期機率，作為辯論基準。",
            {"history_used": 0, "sampling": "uniform"},
        )
    if agent == "hot_hunter":
        window = config.HOT_HUNTER["W"]
        freq = main_freq(history, window)
        return (
            "檢視近期出現頻率是否能提供可重複的排序訊號。",
            {
                "window": min(window, len(history)),
                "selected_recent_counts": [
                    {"number": number, "count": freq[number]} for number in numbers
                ],
            },
        )
    if agent == "cold_keeper":
        gap_map = gaps(history, game)
        return (
            "檢視遺漏深度，但明確把它當待檢驗假設而非到期必出的因果。",
            {
                "selected_gaps": [
                    {"number": number, "gap": gap_map[number]} for number in numbers
                ]
            },
        )
    if agent == "balance_engineer":
        return (
            "偏好結構分散的候選，檢驗外觀約束是否只是在篩選組合。",
            _structural_features(game, numbers),
        )
    if agent == "antipop_taoist":
        above_31 = sum(number > 31 for number in numbers)
        return (
            "偏離常見生日選號帶；此依據只關乎可能分彩，不改變開出機率。",
            {
                "above_31": above_31,
                "all_in_birthday_band": all(number <= 31 for number in numbers),
            },
        )
    raise ValueError(agent)


def _build_proposals(game: str, target: dict, history: list[Draw]) -> list[dict]:
    proposals: list[dict] = []
    seen: set[frozenset[int]] = set()
    for agent in AGENT_IDS:
        for variant in range(1, PROPOSALS_PER_AGENT + 1):
            retry = 0
            while True:
                rng = _proposal_rng(game, target, agent, variant, retry)
                output = PERSONAS[agent](game, history, rng)
                validate_pick(game, output["numbers"], output["special"])
                key = frozenset(output["numbers"])
                if key not in seen or retry >= config.DEDUP_MAX_RETRY:
                    break
                retry += 1
            seen.add(key)
            thesis, evidence = _argument(agent, game, history, output)
            proposals.append(
                {
                    "proposal_id": f"{agent}:{variant}",
                    "agent": agent,
                    "agent_name": NAMES[agent],
                    "variant": variant,
                    "numbers": output["numbers"],
                    "special": output["special"],
                    "retry": retry,
                    "thesis": thesis,
                    "evidence": evidence,
                }
            )
    return proposals


def _percentile(value: float, population: Iterable[float]) -> float:
    values = list(population)
    if not values:
        return 0.5
    below = sum(item < value for item in values)
    equal = sum(item == value for item in values)
    return (below + 0.5 * equal) / len(values)


def _critique_score(
    critic: str, game: str, history: list[Draw], proposal: dict
) -> tuple[float, str]:
    numbers = proposal["numbers"]
    if critic == "random_monk":
        return 0.5, "歷史不能證明單一合法組合較可能；維持中立基準。"

    if critic == "hot_hunter":
        freq = main_freq(history, config.HOT_HUNTER["W"])
        population = [freq[number] for number in range(1, POOL[game] + 1)]
        score = sum(_percentile(freq[number], population) for number in numbers) / 6
        return score, f"近期頻率百分位平均 {score:.3f}。"

    if critic == "cold_keeper":
        gap_map = gaps(history, game)
        population = list(gap_map.values())
        score = sum(_percentile(gap_map[number], population) for number in numbers) / 6
        return score, f"遺漏深度百分位平均 {score:.3f}。"

    if critic == "balance_engineer":
        features = _structural_features(game, numbers)
        checks = (
            features["sum_in_band"],
            features["odd_in_band"],
            features["consecutive_ok"],
            features["tails_ok"],
            features["range_ok"],
        )
        score = sum(checks) / len(checks)
        return score, f"五項結構條件通過 {sum(checks)}/{len(checks)}。"

    if critic == "antipop_taoist":
        above_31 = sum(number > 31 for number in numbers)
        arithmetic = len(
            {right - left for left, right in zip(numbers, numbers[1:])}
        ) == 1
        score = min(1.0, 0.20 + 0.12 * above_31 + (0.08 if not arithmetic else 0))
        return score, f"31 以上號碼 {above_31} 個；等差序列={arithmetic}。"

    raise ValueError(critic)


def _build_critiques(
    game: str, history: list[Draw], proposals: list[dict]
) -> list[dict]:
    critiques = []
    for critic in AGENT_IDS:
        for proposal in proposals:
            if proposal["agent"] == critic:
                continue
            score, reason = _critique_score(critic, game, history, proposal)
            critiques.append(
                {
                    "critic": critic,
                    "critic_name": NAMES[critic],
                    "target": proposal["proposal_id"],
                    "score": round(score, 6),
                    "stance": (
                        "support" if score > 0.60 else "oppose" if score < 0.40 else "neutral"
                    ),
                    "reason": reason,
                }
            )
    return critiques


def _adjudicate(
    proposals: list[dict], critiques: list[dict], state: dict
) -> tuple[list[dict], list[dict]]:
    ratings = {
        agent: float(state["agents"][agent]["rating"]) for agent in AGENT_IDS
    }
    scored = []
    for proposal in proposals:
        relevant = [
            critique for critique in critiques if critique["target"] == proposal["proposal_id"]
        ]
        weight = sum(ratings[item["critic"]] for item in relevant)
        debate_score = (
            sum(item["score"] * ratings[item["critic"]] for item in relevant) / weight
        )
        debate_score += 0.05 * (ratings[proposal["agent"]] - 1.0)
        scored.append(
            {
                "proposal": proposal,
                "debate_score": round(debate_score, 8),
            }
        )

    selected: list[dict] = []
    ranking: list[dict] = []
    remaining = list(scored)
    while len(selected) < SELECTED_TICKETS:
        choices = []
        selected_agents = Counter(item["proposal"]["agent"] for item in selected)
        for item in remaining:
            proposal = item["proposal"]
            if selected:
                overlap = max(
                    len(set(proposal["numbers"]) & set(other["proposal"]["numbers"])) / 6
                    for other in selected
                )
            else:
                overlap = 0.0
            diversity_penalty = 0.12 * overlap
            voice_penalty = 0.04 * selected_agents[proposal["agent"]]
            final_score = item["debate_score"] - diversity_penalty - voice_penalty
            choices.append(
                (
                    -final_score,
                    -item["debate_score"],
                    proposal["proposal_id"],
                    item,
                    diversity_penalty,
                    voice_penalty,
                    final_score,
                )
            )
        choice = sorted(choices)[0]
        item = choice[3]
        selected.append(item)
        remaining.remove(item)
        ranking.append(
            {
                "rank": len(selected),
                "proposal_id": item["proposal"]["proposal_id"],
                "debate_score": item["debate_score"],
                "diversity_penalty": round(choice[4], 8),
                "same_agent_penalty": round(choice[5], 8),
                "final_score": round(choice[6], 8),
            }
        )

    tickets = [
        {
            "slot": rank,
            "source_agent": item["proposal"]["agent"],
            "source_proposal": item["proposal"]["proposal_id"],
            "numbers": item["proposal"]["numbers"],
            "special": item["proposal"]["special"],
        }
        for rank, item in enumerate(selected, 1)
    ]
    return tickets, ranking


def conduct_debate(
    game: str, target: dict, history: list[Draw], state: dict
) -> dict:
    """產生目標期決策；不接受、也不接觸目標期開獎號碼。"""
    if game not in (SUPER, LOTTO649):
        raise ValueError(game)
    _validate_history(game, target, history)
    proposals = _build_proposals(game, target, history)
    critiques = _build_critiques(game, history, proposals)
    selected, ranking = _adjudicate(proposals, critiques, state)
    decision = {
        "schema_version": "1",
        "experiment_id": LOOP_EXPERIMENT_ID,
        "phase": "decision",
        "game": game,
        "game_name": GAME_NAMES[game],
        "target": {"date": target["date"], "period": int(target["period"])},
        "history_count": len(history),
        "history_last": (
            {"date": history[-1].date, "period": history[-1].period}
            if history
            else None
        ),
        "state_before": _state_snapshot(state),
        "proposals": proposals,
        "critiques": critiques,
        "adjudication": {
            "selected_count": SELECTED_TICKETS,
            "method": "可信度加權交叉評議＋主號重疊與同 agent 集中懲罰",
            "ranking": ranking,
        },
        "selected_tickets": selected,
        "honesty_note": (
            "這是依歷史假設排序的純模擬候選；合法組合的理論開出機率相同。"
        ),
    }
    decision["decision_hash"] = canonical_hash(decision)
    return decision


def _ticket_result(game: str, ticket: dict, draw: Draw) -> dict:
    numbers = ticket["numbers"]
    main_hits = len(set(numbers) & set(draw.numbers))
    special_hit = (
        ticket["special"] == draw.special
        if game == SUPER
        else draw.special in set(numbers)
    )
    tier = match_tier(game, numbers, ticket["special"], draw)
    return {
        "main_hits": main_hits,
        "special_hit": special_hit,
        "hit_points": round(main_hits + (0.25 if special_hit else 0.0), 2),
        "tier": tier.label if tier else None,
    }


def _updated_state(state: dict, agent_results: dict[str, dict]) -> dict:
    qualities = {
        agent: result["best_hit_points"] for agent, result in agent_results.items()
    }
    mean_quality = sum(qualities.values()) / len(qualities)
    raw = {
        agent: float(state["agents"][agent]["rating"])
        * math.exp(LEARNING_RATE * (qualities[agent] - mean_quality))
        for agent in AGENT_IDS
    }
    mean_rating = sum(raw.values()) / len(raw)
    normalized = {
        agent: min(
            RATING_RANGE[1],
            max(RATING_RANGE[0], raw[agent] / mean_rating),
        )
        for agent in AGENT_IDS
    }
    next_state = {
        "experiment_id": LOOP_EXPERIMENT_ID,
        "draws_reviewed": int(state["draws_reviewed"]) + 1,
        "agents": {},
    }
    for agent in AGENT_IDS:
        before = state["agents"][agent]
        result = agent_results[agent]
        next_state["agents"][agent] = {
            "rating": round(normalized[agent], 8),
            "reviews": int(before["reviews"]) + 1,
            "cumulative_best_main_hits": int(before["cumulative_best_main_hits"])
            + result["best_main_hits"],
            "cumulative_special_hits": int(before["cumulative_special_hits"])
            + int(result["best_special_hit"]),
        }
    return next_state


def _lesson(agent: str, result: dict) -> str:
    outcome = (
        f"本期三個提案最佳主號命中 {result['best_main_hits']}/6，"
        f"特別號訊號命中={result['best_special_hit']}。"
    )
    notes = {
        "random_monk": "此結果是隨機基準的一次樣本，不外推成趨勢。",
        "hot_hunter": "近期頻率沒有因果保證；只把本期表現回饋到後續可信度。",
        "cold_keeper": "遺漏深不代表到期；本期只檢驗該排序是否碰巧貼近結果。",
        "balance_engineer": "組合外觀不改變理論機率；結構條件只作候選排序。",
        "antipop_taoist": "避開熱門選號不提高開出率；其原始動機僅是可能減少分彩。",
    }
    return outcome + notes[agent]


def review_after_reveal(
    decision: dict, draw: Draw, state: dict
) -> tuple[dict, dict]:
    """揭曉後檢討並回傳新狀態；呼叫前的 state 不會被原地修改。"""
    if decision["game"] != draw.game or decision["target"] != target_from_draw(draw):
        raise ValueError("揭曉期別與先前決策不一致")
    if decision["state_before"] != _state_snapshot(state):
        raise ValueError("檢討狀態與決策時快照不一致")

    proposal_results = {}
    by_agent: dict[str, list[dict]] = {agent: [] for agent in AGENT_IDS}
    for proposal in decision["proposals"]:
        result = _ticket_result(draw.game, proposal, draw)
        proposal_results[proposal["proposal_id"]] = result
        by_agent[proposal["agent"]].append(result)

    selected_results = []
    for ticket in decision["selected_tickets"]:
        selected_results.append(
            {
                "slot": ticket["slot"],
                "source_proposal": ticket["source_proposal"],
                **_ticket_result(draw.game, ticket, draw),
            }
        )

    agent_results = {}
    for agent, results in by_agent.items():
        best = sorted(
            results,
            key=lambda item: (
                -item["hit_points"],
                -item["main_hits"],
                not item["special_hit"],
            ),
        )[0]
        agent_results[agent] = {
            "best_main_hits": best["main_hits"],
            "best_special_hit": best["special_hit"],
            "best_hit_points": best["hit_points"],
        }

    next_state = _updated_state(state, agent_results)
    selected_ids = {ticket["source_proposal"] for ticket in decision["selected_tickets"]}
    unselected = [
        (proposal_id, result)
        for proposal_id, result in proposal_results.items()
        if proposal_id not in selected_ids
    ]
    best_unselected = sorted(
        unselected,
        key=lambda item: (-item[1]["hit_points"], item[0]),
    )[0]
    worst_selected = sorted(
        selected_results,
        key=lambda item: (item["hit_points"], item["source_proposal"]),
    )[0]
    selected_union = set().union(
        *(set(ticket["numbers"]) for ticket in decision["selected_tickets"])
    )
    selected_counts = Counter(
        number
        for ticket in decision["selected_tickets"]
        for number in ticket["numbers"]
    )
    repeated_misses = [
        {"number": number, "selected_count": count}
        for number, count in sorted(selected_counts.items(), key=lambda item: (-item[1], item[0]))
        if count > 1 and number not in draw.numbers
    ]
    review = {
        "schema_version": "1",
        "experiment_id": LOOP_EXPERIMENT_ID,
        "phase": "review",
        "game": draw.game,
        "target": target_from_draw(draw),
        "decision_hash": decision["decision_hash"],
        "actual": {
            "numbers": list(draw.numbers),
            "special": draw.special,
        },
        "selected_results": selected_results,
        "agent_results": agent_results,
        "error_analysis": {
            "fully_matched": any(
                item["main_hits"] == 6
                and (draw.game == LOTTO649 or item["special_hit"])
                for item in selected_results
            ),
            "best_selected_main_hits": max(
                item["main_hits"] for item in selected_results
            ),
            "missed_actual_numbers": sorted(set(draw.numbers) - selected_union),
            "repeated_but_missed": repeated_misses,
            "hindsight_best_unselected": {
                "proposal_id": best_unselected[0],
                **best_unselected[1],
            },
            "hindsight_selection_regret": round(
                max(0.0, best_unselected[1]["hit_points"] - worst_selected["hit_points"]),
                2,
            ),
            "interpretation": (
                "錯誤指候選與實際結果不一致；以下是可量化落差，不宣稱找到隨機開獎的因果。"
            ),
        },
        "lessons": [
            {"agent": agent, "text": _lesson(agent, agent_results[agent])}
            for agent in AGENT_IDS
        ],
        "state_before": _state_snapshot(state),
        "state_after": _state_snapshot(next_state),
    }
    review["review_hash"] = canonical_hash(review)
    return review, next_state


def _event_hash(event: dict) -> str:
    payload = {key: value for key, value in event.items() if key != "event_hash"}
    return canonical_hash(payload)


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def replay_game(
    game: str,
    draws: list[Draw],
    output_path: Path | None = None,
    *,
    collect_events: bool = False,
) -> dict:
    """逐期回放完整閉環；若給 output_path，以決定性 JSONL 原子替換輸出。"""
    ordered = sorted(draws, key=lambda draw: (draw.date, draw.period))
    if any(draw.game != game for draw in ordered):
        raise ValueError("回放資料含其他遊戲")
    if len({(draw.date, draw.period) for draw in ordered}) != len(ordered):
        raise ValueError("回放資料含重複期別")

    state = initial_state()
    history: list[Draw] = []
    previous_hash = None
    events = []
    temp_path = None
    handle = None
    if output_path is not None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = output_path.with_suffix(output_path.suffix + ".tmp")
        handle = temp_path.open("w", encoding="utf-8", newline="\n")
    try:
        for sequence, draw in enumerate(ordered, 1):
            decision = conduct_debate(game, target_from_draw(draw), history, state)
            review, state = review_after_reveal(decision, draw, state)
            event = {
                "sequence": sequence,
                "previous_event_hash": previous_hash,
                "decision": decision,
                "reveal": {
                    "date": draw.date,
                    "period": draw.period,
                    "numbers": list(draw.numbers),
                    "special": draw.special,
                },
                "review": review,
            }
            event["event_hash"] = _event_hash(event)
            previous_hash = event["event_hash"]
            if handle is not None:
                handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
            if collect_events:
                events.append(event)
            history.append(draw)
        if handle is not None:
            handle.flush()
            os.fsync(handle.fileno())
            handle.close()
            handle = None
            os.replace(temp_path, output_path)
    finally:
        if handle is not None:
            handle.close()
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()

    future_decision = (
        conduct_debate(game, next_target(game, ordered[-1]), history, state)
        if ordered
        else None
    )
    summary = {
        "experiment_id": LOOP_EXPERIMENT_ID,
        "game": game,
        "game_name": GAME_NAMES[game],
        "draws_replayed": len(ordered),
        "first_target": target_from_draw(ordered[0]) if ordered else None,
        "last_target": target_from_draw(ordered[-1]) if ordered else None,
        "last_event_hash": previous_hash,
        "final_state": _state_snapshot(state),
        "next_decision": future_decision,
        "ledger_sha256": _file_hash(output_path) if output_path is not None else None,
    }
    if collect_events:
        summary["events"] = events
    return summary


def verify_replay(path: Path, expected_draws: int | None = None) -> dict:
    """驗證 JSONL 雜湊鏈、逐期順序、決策/檢討雜湊及票券合法性。"""
    path = Path(path)
    previous_hash = None
    count = 0
    with path.open(encoding="utf-8") as handle:
        for count, line in enumerate(handle, 1):
            event = json.loads(line)
            if event["sequence"] != count:
                raise ValueError(f"第 {count} 行 sequence 不連續")
            if event["previous_event_hash"] != previous_hash:
                raise ValueError(f"第 {count} 行雜湊鏈中斷")
            if event["event_hash"] != _event_hash(event):
                raise ValueError(f"第 {count} 行 event_hash 不符")
            decision = event["decision"]
            review = event["review"]
            decision_payload = {
                key: value for key, value in decision.items() if key != "decision_hash"
            }
            review_payload = {
                key: value for key, value in review.items() if key != "review_hash"
            }
            if decision["decision_hash"] != canonical_hash(decision_payload):
                raise ValueError(f"第 {count} 行 decision_hash 不符")
            if review["review_hash"] != canonical_hash(review_payload):
                raise ValueError(f"第 {count} 行 review_hash 不符")
            if decision["history_count"] != count - 1:
                raise ValueError(f"第 {count} 行歷史期數不符")
            if decision["target"] != {
                "date": event["reveal"]["date"],
                "period": event["reveal"]["period"],
            }:
                raise ValueError(f"第 {count} 行決策與揭曉期別不符")
            tickets = decision["selected_tickets"]
            if len(tickets) != SELECTED_TICKETS:
                raise ValueError(f"第 {count} 行不是五注")
            if len({tuple(ticket["numbers"]) for ticket in tickets}) != len(tickets):
                raise ValueError(f"第 {count} 行主號票重複")
            for ticket in tickets:
                validate_pick(decision["game"], ticket["numbers"], ticket["special"])
            if review["decision_hash"] != decision["decision_hash"]:
                raise ValueError(f"第 {count} 行檢討未連回決策")
            previous_hash = event["event_hash"]
    if expected_draws is not None and count != expected_draws:
        raise ValueError(f"期數不符：{count} != {expected_draws}")
    return {
        "lines": count,
        "last_event_hash": previous_hash,
        "ledger_sha256": _file_hash(path),
    }


def run_all(store, output_dir: Path) -> dict:
    """兩遊戲完整回放並寫出總表；輸出與正式 records 完全隔離。"""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    games = {}
    for game in (SUPER, LOTTO649):
        path = output_dir / f"{game}.jsonl"
        summary = replay_game(game, store.draws(game), path)
        verified = verify_replay(path, len(store.draws(game)))
        games[game] = {
            **{key: value for key, value in summary.items() if key != "next_decision"},
            "next_decision": summary["next_decision"],
            "verification": verified,
            "ledger_file": path.name,
        }
    manifest = {
        "schema_version": "1",
        "experiment_id": LOOP_EXPERIMENT_ID,
        "games": games,
    }
    manifest["manifest_hash"] = canonical_hash(manifest)
    manifest_path = output_dir / "manifest.json"
    temp = manifest_path.with_suffix(".json.tmp")
    temp.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temp, manifest_path)
    return manifest
