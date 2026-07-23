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
from typing import Callable, Iterable

from . import config
from .mechanism_agents import (
    HYPOTHESES,
    HYPOTHESIS_IDS,
    NAMES,
    build_hypothesis_context,
    propose,
    public_hypothesis_snapshots,
)
from .games import (
    DRAW_WEEKDAYS,
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
from .seeds import seed_int

LOOP_EXPERIMENT_ID = "agent-loop-v3-unknown-generator"
AGENT_IDS = tuple(sorted(HYPOTHESIS_IDS))
PROPOSALS_PER_AGENT = 3
SELECTED_TICKETS = 5
LEARNING_RATE = 0.18
RATING_RANGE = (0.50, 1.50)
HOT_WINDOWS = (12, 30, 60)


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
                "cumulative_brier": 0.0,
                "cumulative_skill_vs_h0": 0.0,
                "cumulative_skill_sq": 0.0,
                "evidence_wins": 0,
            }
            for agent in AGENT_IDS
        },
    }


def _evidence_summary(agent_state: dict) -> dict:
    reviews = int(agent_state["reviews"])
    cumulative_skill = float(
        agent_state.get("cumulative_skill_vs_h0", 0.0)
    )
    mean_skill = cumulative_skill / reviews if reviews else 0.0
    cumulative_square = float(
        agent_state.get("cumulative_skill_sq", 0.0)
    )
    if reviews > 1:
        variance = max(
            0.0,
            (
                cumulative_square
                - reviews * mean_skill * mean_skill
            )
            / (reviews - 1),
        )
        margin = 1.96 * math.sqrt(variance / reviews)
    else:
        margin = 0.0
    return {
        "mean_brier": round(
            float(agent_state.get("cumulative_brier", 0.0))
            / reviews,
            10,
        )
        if reviews
        else None,
        "mean_skill_vs_h0": round(mean_skill, 10),
        "confidence_interval_95": [
            round(mean_skill - margin, 10),
            round(mean_skill + margin, 10),
        ],
        "evidence_wins": int(agent_state.get("evidence_wins", 0)),
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
                "cumulative_brier": round(
                    float(
                        state["agents"][agent].get(
                            "cumulative_brier",
                            0.0,
                        )
                    ),
                    10,
                ),
                "cumulative_skill_vs_h0": round(
                    float(
                        state["agents"][agent].get(
                            "cumulative_skill_vs_h0",
                            0.0,
                        )
                    ),
                    10,
                ),
                "cumulative_skill_sq": round(
                    float(
                        state["agents"][agent].get(
                            "cumulative_skill_sq",
                            0.0,
                        )
                    ),
                    12,
                ),
                "evidence_wins": int(
                    state["agents"][agent].get("evidence_wins", 0)
                ),
                "blind_evidence": _evidence_summary(
                    state["agents"][agent]
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
    bucket_width = math.ceil(POOL[game] / 4)
    bucket_kinds = len({min(3, (number - 1) // bucket_width) for number in numbers})
    tail_counts = Counter(number % 10 for number in numbers)
    max_same_tail = max(tail_counts.values())
    gaps_between = [right - left for left, right in zip(numbers, numbers[1:])]
    gap_kinds = len(set(gaps_between))
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
        "bucket_kinds": bucket_kinds,
        "bucket_coverage_ok": bucket_kinds >= 3,
        "max_same_tail": max_same_tail,
        "tail_concentration_ok": max_same_tail <= 2,
        "gap_kinds": gap_kinds,
    }


def _antipop_features(numbers: list[int]) -> dict:
    differences = [right - left for left, right in zip(numbers, numbers[1:])]
    tail_counts = Counter(number % 10 for number in numbers)
    return {
        "above_31": sum(number > 31 for number in numbers),
        "month_band": sum(number <= 12 for number in numbers),
        "birthday_band": sum(number <= 31 for number in numbers),
        "round_numbers": sum(number % 5 == 0 for number in numbers),
        "repeated_tail_pairs": sum(
            count * (count - 1) // 2 for count in tail_counts.values()
        ),
        "arithmetic_sequence": len(set(differences)) == 1,
        "fully_consecutive": all(difference == 1 for difference in differences),
    }


def _analysis_context(game: str, history: list[Draw]) -> dict:
    return build_hypothesis_context(game, history)


def _argument(
    agent: str,
    game: str,
    history: list[Draw],
    ticket: dict,
    context: dict,
) -> tuple[str, dict]:
    numbers = ticket["numbers"]
    model = context["models"][agent]
    uniform = PICK_N / POOL[game]
    selected_probabilities = [
        {
            "number": number,
            "probability": round(
                model["main_probabilities"][number],
                10,
            ),
            "relative_to_uniform": round(
                model["main_probabilities"][number] / uniform,
                6,
            ),
        }
        for number in numbers
    ]
    return (
        model["thesis"],
        {
            "hypothesis_code": model["code"],
            "evidence_strength": model["evidence_strength"],
            "selected_probabilities": selected_probabilities,
            "mean_relative_to_uniform": round(
                sum(
                    item["relative_to_uniform"]
                    for item in selected_probabilities
                )
                / len(selected_probabilities),
                6,
            ),
            "diagnostics": model["diagnostics"],
            "distribution_hash": ticket["meta"]["distribution_hash"],
            "history_used": context["history_count"],
        },
    )


def _build_proposals(
    game: str, target: dict, history: list[Draw], context: dict
) -> list[dict]:
    proposals: list[dict] = []
    seen: set[frozenset[int]] = set()
    for agent in AGENT_IDS:
        for variant in range(1, PROPOSALS_PER_AGENT + 1):
            retry = 0
            while True:
                rng = _proposal_rng(game, target, agent, variant, retry)
                output = propose(agent, game, rng, context)
                validate_pick(game, output["numbers"], output["special"])
                key = frozenset(output["numbers"])
                if key not in seen or retry >= config.DEDUP_MAX_RETRY:
                    break
                retry += 1
            seen.add(key)
            thesis, evidence = _argument(agent, game, history, output, context)
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
    critic: str,
    game: str,
    history: list[Draw],
    proposal: dict,
    context: dict,
) -> tuple[float, float, str, dict]:
    numbers = proposal["numbers"]
    model = context["models"][critic]
    probabilities = model["main_probabilities"]
    population = list(probabilities.values())
    percentile_score = sum(
        _percentile(probabilities[number], population)
        for number in numbers
    ) / PICK_N
    uniform = PICK_N / POOL[game]
    relative_probability = sum(
        probabilities[number] / uniform
        for number in numbers
    ) / PICK_N
    confidence = float(model["evidence_strength"])
    evidence = {
        "hypothesis_code": model["code"],
        "probability_percentile": round(percentile_score, 6),
        "mean_relative_to_uniform": round(relative_probability, 6),
        "evidence_strength": confidence,
        "diagnostics": model["diagnostics"],
    }
    if critic == "independent_null":
        reason = (
            "H0 對所有合法號碼給相同邊際機率；本候選維持 0.5 校準分，"
            "但 H0 不享有席位或裁決加成。"
        )
    else:
        reason = (
            f"{model['code']} 對本候選的機率秩為 "
            f"{percentile_score:.3f}，相對均勻邊際 "
            f"{relative_probability:.3f} 倍；證據強度 "
            f"{confidence:.3f}。"
        )
    return percentile_score, confidence, reason, evidence


def _build_critiques(
    game: str, history: list[Draw], proposals: list[dict], context: dict
) -> list[dict]:
    critiques = []
    for critic in AGENT_IDS:
        for proposal in proposals:
            if proposal["agent"] == critic:
                continue
            score, confidence, reason, evidence = _critique_score(
                critic, game, history, proposal, context
            )
            critiques.append(
                {
                    "critic": critic,
                    "critic_name": NAMES[critic],
                    "target": proposal["proposal_id"],
                    "score": round(score, 6),
                    "confidence": round(confidence, 6),
                    "stance": (
                        "support" if score > 0.60 else "oppose" if score < 0.40 else "neutral"
                    ),
                    "reason": reason,
                    "evidence": evidence,
                }
            )
    return critiques


def _adjudicate(
    proposals: list[dict], critiques: list[dict], state: dict
) -> tuple[list[dict], list[dict], list[dict]]:
    ratings = {
        agent: float(state["agents"][agent]["rating"]) for agent in AGENT_IDS
    }
    scored = []
    for proposal in proposals:
        relevant = [
            critique for critique in critiques if critique["target"] == proposal["proposal_id"]
        ]
        weights = [
            ratings[item["critic"]] * float(item.get("confidence", 1.0))
            for item in relevant
        ]
        weight = sum(weights)
        consensus = (
            sum(
                item["score"] * item_weight
                for item, item_weight in zip(relevant, weights)
            )
            / weight
        )
        disagreement = math.sqrt(
            sum(
                item_weight * (item["score"] - consensus) ** 2
                for item, item_weight in zip(relevant, weights)
            )
            / weight
        )
        proposer_adjustment = 0.05 * (ratings[proposal["agent"]] - 1.0)
        debate_score = consensus - 0.08 * disagreement + proposer_adjustment
        scored.append(
            {
                "proposal": proposal,
                "debate_score": round(debate_score, 8),
                "consensus_score": round(consensus, 8),
                "disagreement": round(disagreement, 8),
                "proposer_adjustment": round(proposer_adjustment, 8),
                "critic_scores": [
                    {
                        "critic": item["critic"],
                        "score": item["score"],
                        "confidence": item.get("confidence", 1.0),
                    }
                    for item in relevant
                ],
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
            diversity_penalty = 0.14 * overlap
            voice_penalty = 0.05 * selected_agents[proposal["agent"]]
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
    candidate_scores = [
        {
            "proposal_id": item["proposal"]["proposal_id"],
            "agent": item["proposal"]["agent"],
            "debate_score": item["debate_score"],
            "consensus_score": item["consensus_score"],
            "disagreement": item["disagreement"],
            "proposer_adjustment": item["proposer_adjustment"],
            "critic_scores": item["critic_scores"],
        }
        for item in sorted(
            scored,
            key=lambda item: (
                -item["debate_score"],
                item["proposal"]["proposal_id"],
            ),
        )
    ]
    return tickets, ranking, candidate_scores


def conduct_debate(
    game: str, target: dict, history: list[Draw], state: dict
) -> dict:
    """產生目標期決策；不接受、也不接觸目標期開獎號碼。"""
    if game not in (SUPER, LOTTO649):
        raise ValueError(game)
    _validate_history(game, target, history)
    context = _analysis_context(game, history)
    proposals = _build_proposals(game, target, history, context)
    critiques = _build_critiques(game, history, proposals, context)
    selected, ranking, candidate_scores = _adjudicate(proposals, critiques, state)
    decision = {
        "schema_version": "3",
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
        "generator_contract": {
            "assumption": "unknown",
            "baseline_hypothesis": "independent_null",
            "baseline_is_privileged": False,
            "selection_rule": (
                "五個假說使用相同提案數、互評數與初始評等；"
                "只有嚴格早於目標期的逐期封存證據能更新後續權重。"
            ),
        },
        "hypotheses": public_hypothesis_snapshots(context),
        "proposals": proposals,
        "critiques": critiques,
        "adjudication": {
            "selected_count": SELECTED_TICKETS,
            "method": (
                "未知生成機制假說競爭：proper-score 可信度加權共識"
                "－評議分歧＋主號重疊與同假說集中懲罰"
            ),
            "ranking": ranking,
            "candidate_scores": candidate_scores,
            "judge": {
                "source": "deterministic_replay",
                "requested_model": None,
                "model": None,
                "summary": "歷史回放採可重現規則裁判；不呼叫語言模型。",
                "reasons": [],
            },
        },
        "selected_tickets": selected,
        "honesty_note": (
            "這是未知生成機制下的純模擬候選；不預設開獎獨立隨機，"
            "也不預設歷史必有規律。只有封存後的逐期盲測能累積證據。"
        ),
    }
    decision["decision_hash"] = canonical_hash(decision)
    return decision


def _selected_from_proposal_ids(
    decision: dict,
    proposal_ids: list[str],
    reasons: list[dict],
) -> tuple[list[dict], list[dict]]:
    proposals = {
        proposal["proposal_id"]: proposal for proposal in decision["proposals"]
    }
    candidate_scores = {
        item["proposal_id"]: item
        for item in decision["adjudication"]["candidate_scores"]
    }
    reason_map = {item["proposal_id"]: item["reason"] for item in reasons}
    if len(proposal_ids) != SELECTED_TICKETS or len(set(proposal_ids)) != SELECTED_TICKETS:
        raise ValueError("終局裁判必須選出五個不重複提案")
    if any(proposal_id not in proposals for proposal_id in proposal_ids):
        raise ValueError("終局裁判選到不存在的提案")

    tickets = []
    ranking = []
    seen_numbers: set[tuple[int, ...]] = set()
    selected_proposals = []
    for rank, proposal_id in enumerate(proposal_ids, 1):
        proposal = proposals[proposal_id]
        number_key = tuple(proposal["numbers"])
        if number_key in seen_numbers:
            raise ValueError("終局裁判選到主號重複的提案")
        seen_numbers.add(number_key)
        validate_pick(decision["game"], proposal["numbers"], proposal["special"])

        overlap = (
            max(
                len(set(proposal["numbers"]) & set(other["numbers"])) / 6
                for other in selected_proposals
            )
            if selected_proposals
            else 0.0
        )
        same_agent_count = sum(
            other["agent"] == proposal["agent"] for other in selected_proposals
        )
        diversity_penalty = 0.14 * overlap
        voice_penalty = 0.05 * same_agent_count
        score = candidate_scores[proposal_id]
        final_score = score["debate_score"] - diversity_penalty - voice_penalty
        tickets.append(
            {
                "slot": rank,
                "source_agent": proposal["agent"],
                "source_proposal": proposal_id,
                "numbers": proposal["numbers"],
                "special": proposal["special"],
            }
        )
        ranking.append(
            {
                "rank": rank,
                "proposal_id": proposal_id,
                "debate_score": score["debate_score"],
                "diversity_penalty": round(diversity_penalty, 8),
                "same_agent_penalty": round(voice_penalty, 8),
                "final_score": round(final_score, 8),
                "judge_reason": reason_map.get(proposal_id, ""),
            }
        )
        selected_proposals.append(proposal)
    return tickets, ranking


def apply_final_judge(
    decision: dict,
    judge: Callable[[dict], dict],
    *,
    requested_model: str = "qwen3:8b",
) -> dict:
    """只對下一期決策套用終局模型；失敗時保留可重現規則裁決並明確標示。"""
    baseline_tickets = decision["selected_tickets"]
    baseline_ranking = decision["adjudication"]["ranking"]
    judge_result = None
    try:
        judge_result = judge(decision)
        if judge_result.get("source") != "ollama":
            raise ValueError("終局裁判未證明輸出來自 Ollama")
        if judge_result.get("model") != requested_model:
            raise ValueError(
                f"終局模型不符：{judge_result.get('model') or 'unknown'}"
            )
        tickets, ranking = _selected_from_proposal_ids(
            decision,
            judge_result["selected_proposal_ids"],
            judge_result["reasons"],
        )
        decision["selected_tickets"] = tickets
        decision["adjudication"]["ranking"] = ranking
        decision["adjudication"]["method"] = (
            "Qwen3:8b 綜合 15 組提案、60 次信心度加權交叉評議與組合分散度終局裁決"
        )
        decision["adjudication"]["judge"] = judge_result
    except Exception as exc:
        telemetry = getattr(exc, "telemetry", None)
        feedback_provenance = getattr(
            exc, "feedback_provenance", None
        )
        feedback_context = getattr(exc, "feedback_context", None)
        if telemetry is None and isinstance(judge_result, dict):
            telemetry = judge_result.get("telemetry")
        if feedback_provenance is None and isinstance(judge_result, dict):
            feedback_provenance = judge_result.get(
                "feedback_provenance"
            )
        if feedback_context is None and isinstance(judge_result, dict):
            feedback_context = judge_result.get("feedback_context")
        if telemetry is None:
            telemetry = {
                "schema_version": "1",
                "outcome": "error",
                "wall_duration_ms": None,
                "ollama_total_duration_ms": None,
                "load_duration_ms": None,
                "prompt_eval_count": None,
                "prompt_eval_duration_ms": None,
                "eval_count": None,
                "eval_duration_ms": None,
                "eval_tokens_per_second": None,
                "error_type": type(exc).__name__,
                "complete": False,
            }
        decision["selected_tickets"] = baseline_tickets
        decision["adjudication"]["ranking"] = baseline_ranking
        decision["adjudication"]["method"] = (
            "Qwen3:8b 終局裁判失敗；使用可重現規則裁決降級結果"
        )
        decision["adjudication"]["judge"] = {
            "source": "deterministic_fallback",
            "requested_model": requested_model,
            "model": None,
            "selected_proposal_ids": [
                ticket["source_proposal"] for ticket in baseline_tickets
            ],
            "summary": "本次模型輸出不可驗證，已保留規則裁決結果。",
            "reasons": [],
            "fallback_reason": str(exc)[:300],
            "telemetry": telemetry,
            "feedback_provenance": feedback_provenance,
            "feedback_context": feedback_context,
        }
    decision.pop("decision_hash", None)
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


def _proper_score_results(decision: dict, draw: Draw) -> dict[str, dict]:
    snapshots = {
        hypothesis["id"]: hypothesis
        for hypothesis in decision["hypotheses"]
    }
    actual = set(draw.numbers)
    results = {}
    for agent in AGENT_IDS:
        snapshot = snapshots[agent]
        main_probabilities = snapshot["main_probabilities"]
        if len(main_probabilities) != POOL[draw.game]:
            raise ValueError(f"{agent} 主號機率快照長度不符")
        main_brier = sum(
            (
                float(probability)
                - float(number in actual)
            )
            ** 2
            for number, probability in enumerate(
                main_probabilities,
                1,
            )
        ) / POOL[draw.game]
        special_brier = None
        combined_brier = main_brier
        if draw.game == SUPER:
            special_probabilities = snapshot["special_probabilities"]
            if (
                special_probabilities is None
                or len(special_probabilities) != SPECIAL_POOL[SUPER]
            ):
                raise ValueError(f"{agent} 第二區機率快照長度不符")
            special_brier = sum(
                (
                    float(probability)
                    - float(number == draw.special)
                )
                ** 2
                for number, probability in enumerate(
                    special_probabilities,
                    1,
                )
            ) / SPECIAL_POOL[SUPER]
            combined_brier = 0.85 * main_brier + 0.15 * special_brier
        results[agent] = {
            "main_brier": round(main_brier, 10),
            "special_brier": (
                round(special_brier, 10)
                if special_brier is not None
                else None
            ),
            "brier": round(combined_brier, 10),
        }
    baseline = results["independent_null"]["brier"]
    for agent in AGENT_IDS:
        results[agent]["skill_vs_h0"] = round(
            baseline - results[agent]["brier"],
            10,
        )
    return results


def _updated_state(state: dict, agent_results: dict[str, dict]) -> dict:
    qualities = {
        agent: min(
            2.0,
            max(-2.0, 100.0 * result["skill_vs_h0"]),
        )
        for agent, result in agent_results.items()
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
            "cumulative_brier": round(
                float(before.get("cumulative_brier", 0.0))
                + result["brier"],
                10,
            ),
            "cumulative_skill_vs_h0": round(
                float(before.get("cumulative_skill_vs_h0", 0.0))
                + result["skill_vs_h0"],
                10,
            ),
            "cumulative_skill_sq": round(
                float(before.get("cumulative_skill_sq", 0.0))
                + result["skill_vs_h0"] ** 2,
                12,
            ),
            "evidence_wins": int(before.get("evidence_wins", 0))
            + int(result["skill_vs_h0"] > 0),
        }
    return next_state


def _lesson(agent: str, result: dict) -> str:
    outcome = (
        f"本期三個提案最佳主號命中 {result['best_main_hits']}/6，"
        f"proper-score 相對 H0 技能={result['skill_vs_h0']:+.6f}。"
    )
    notes = {
        "independent_null": "H0 只是比較尺，不因單期輸贏被宣告為真。",
        "temporal_dependency": "檢查短期記憶是否跨期重現；單期熱點不升格為規律。",
        "regime_shift": "檢查短長窗漂移是否延續；變點訊號失效時權重會下降。",
        "structural_bias": "檢查長期邊際與組合幾何是否持續；外觀相似不等於因果。",
        "overfit_guard": "只有跨窗一致且收縮後仍有效的訊號，才保留到下一期。",
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

    proper_results = _proper_score_results(decision, draw)
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
            **proper_results[agent],
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
        "schema_version": "2",
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
        "hypothesis_results": agent_results,
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
                "錯誤指封存機率與實際結果的落差；比較同時保留 H0 與替代假說，"
                "不預設生成機制，也不把單期結果升格為因果。"
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
    final_judge: Callable[[dict], dict] | None = None,
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

    future_decision = None
    if ordered:
        future_decision = conduct_debate(
            game, next_target(game, ordered[-1]), history, state
        )
        if final_judge is not None:
            future_decision = apply_final_judge(future_decision, final_judge)
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


def run_all(
    store,
    output_dir: Path,
    *,
    final_judge: Callable[[dict], dict] | None = None,
) -> dict:
    """兩遊戲完整回放並寫出總表；輸出與正式 records 完全隔離。"""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    games = {}
    for game in (SUPER, LOTTO649):
        path = output_dir / f"{game}.jsonl"
        summary = replay_game(
            game,
            store.draws(game),
            path,
            final_judge=final_judge,
        )
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
