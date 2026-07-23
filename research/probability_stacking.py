"""以逐期 proper-score 縮權的機率專家 future-only shadow。

完整歷史只依真實順序初始化線上權重與提供描述性診斷。任何策略升級只能
來自凍結後、不可回填的前向配對，不能用本模組重新開採既有 holdout。
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import statistics
from collections import Counter
from datetime import date
from pathlib import Path

from engine.agent_loop import (
    AGENT_IDS,
    LOOP_EXPERIMENT_ID,
    canonical_hash,
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
from research.agent_ablation import _validate_event, portfolio_metrics
from research.gates import tree_sha256
from research.max_coverage import select_consensus_disjoint_portfolio
from research.portfolio_coverage import portfolio_structure
from research.structural_optimum import structural_proof_reference


EXPERIMENT_ID = "online-probability-stacking-shadow-v1"
FORWARD_EXPERIMENT_ID = "probability-stacking-forward-shadow-v1"
SCORE_CAPSULE_EXPERIMENT_ID = "pre-reveal-probability-score-capsule-v1"
DEBATE_EXPERT = "debate_consensus"
UNIFORM_EXPERT = "uniform"
EXPERT_IDS = tuple(AGENT_IDS) + (DEBATE_EXPERT, UNIFORM_EXPERT)
SMOOTHING = 0.5
DEBATE_TEMPERATURE = 1.0
SELECTED_MAIN_NUMBERS = 30
SELECTED_TICKETS = 5
MONITORING_CHECKPOINTS = (52, 104, 208, 416, 832)
BOOTSTRAP_BLOCK_DRAWS = 13
BOOTSTRAP_SAMPLES = 2_000
LOOK_LOWER_TAIL_ALPHA = 0.005

PROTOCOL_CONFIG = {
    "experts": list(EXPERT_IDS),
    "smoothing": SMOOTHING,
    "debate_temperature": DEBATE_TEMPERATURE,
    "loss": "mean_negative_log_mass_of_six_drawn_main_numbers",
    "special_loss": "negative_log_mass_of_drawn_special",
    "learning_rate": "eta_t=1/sqrt(t)",
    "main_selection": "top_30_then_round_robin_five_disjoint_tickets",
    "special_selection": "top_5_then_pair_by_ticket_main_mass",
    "monitoring_checkpoints": list(MONITORING_CHECKPOINTS),
    "bootstrap_block_draws": BOOTSTRAP_BLOCK_DRAWS,
    "bootstrap_samples": BOOTSTRAP_SAMPLES,
    "look_lower_tail_alpha": LOOK_LOWER_TAIL_ALPHA,
    "historical_use": "prequential_initialization_and_description_only",
    "promotion_evidence": "future_forward_pairs_only",
}
PROTOCOL_HASH = canonical_hash(PROTOCOL_CONFIG)
SCORE_CAPSULE_RULES = {
    "main": "mean_negative_log_mass_of_six_drawn_main_numbers",
    "special": "negative_log_mass_of_drawn_special",
    "baseline": "discrete_uniform",
    "direction": "lower_loss_and_negative_regret_are_better",
}
SCORE_RESULT_INTERPRETATION = (
    "主號與第二區只用開獎前凍結的完整機率質量計分；"
    "regret 小於零代表優於同定義域均勻基準，單期不得直接升級策略。"
)


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(
            character in "0123456789abcdef"
            for character in value
        )
    )


def _softmax(log_values: dict[str, float]) -> dict[str, float]:
    if set(log_values) != set(EXPERT_IDS):
        raise ValueError("stacking 專家權重欄位不完整")
    values = {key: float(value) for key, value in log_values.items()}
    if any(not math.isfinite(value) for value in values.values()):
        raise ValueError("stacking 專家權重必須為有限值")
    maximum = max(values.values())
    exponentials = {
        key: math.exp(value - maximum)
        for key, value in values.items()
    }
    denominator = math.fsum(exponentials.values())
    if not denominator > 0:
        raise ValueError("stacking 專家權重無法正規化")
    return {
        key: exponentials[key] / denominator
        for key in EXPERT_IDS
    }


def _validate_distribution(
    distribution: dict[int, float],
    *,
    domain_size: int,
) -> None:
    if set(distribution) != set(range(1, domain_size + 1)):
        raise ValueError("stacking 機率分布定義域不完整")
    values = [float(distribution[index]) for index in distribution]
    if any(not math.isfinite(value) or value <= 0 for value in values):
        raise ValueError("stacking 機率質量必須為有限正值")
    if not math.isclose(
        math.fsum(values),
        1.0,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise ValueError("stacking 機率質量總和不為 1")


def _proposal_contract(
    game: str,
    decision: dict,
) -> tuple[list[dict], dict[str, float]]:
    if (
        game not in (SUPER, LOTTO649)
        or decision.get("game") != game
        or decision.get("experiment_id") != LOOP_EXPERIMENT_ID
    ):
        raise ValueError("stacking decision 遊戲不符")
    decision_payload = {
        key: value
        for key, value in decision.items()
        if key != "decision_hash"
    }
    if decision.get("decision_hash") != canonical_hash(decision_payload):
        raise ValueError("stacking decision_hash 不符")
    proposals = list(decision.get("proposals", ()))
    if (
        len(proposals) != 15
        or Counter(row.get("agent") for row in proposals)
        != Counter({agent: 3 for agent in AGENT_IDS})
    ):
        raise ValueError("stacking 需要五個 Agent 各三組提案")
    proposal_ids = [str(row.get("proposal_id")) for row in proposals]
    if len(set(proposal_ids)) != 15:
        raise ValueError("stacking proposal_id 重複")
    proposer_by_id = {
        str(row["proposal_id"]): row["agent"]
        for row in proposals
    }
    critiques = list(decision.get("critiques", ()))
    expected_critiques = Counter(
        (critic, proposal_id)
        for proposal_id, proposer in proposer_by_id.items()
        for critic in AGENT_IDS
        if critic != proposer
    )
    observed_critiques = Counter(
        (row.get("critic"), str(row.get("target")))
        for row in critiques
    )
    try:
        critique_values = [
            (float(row.get("score")), float(row.get("confidence")))
            for row in critiques
        ]
    except (TypeError, ValueError) as exc:
        raise ValueError("stacking 評論分數格式不符") from exc
    if (
        len(critiques) != 60
        or observed_critiques != expected_critiques
        or any(
            not math.isfinite(score)
            or not math.isfinite(confidence)
            or score < 0
            or score > 1
            or confidence < 0
            or confidence > 1
            for score, confidence in critique_values
        )
    ):
        raise ValueError("stacking 需要完整有效的 60 次跨 Agent 評論")
    score_rows = list(
        decision.get("adjudication", {}).get("candidate_scores", ())
    )
    try:
        scores = {
            str(row.get("proposal_id")): float(row.get("debate_score"))
            for row in score_rows
        }
    except (TypeError, ValueError) as exc:
        raise ValueError("stacking 辯論分數格式不符") from exc
    if (
        len(score_rows) != 15
        or set(scores) != set(proposal_ids)
        or any(not math.isfinite(value) for value in scores.values())
    ):
        raise ValueError("stacking 需要完整有限的辯論分數")
    return proposals, scores


def expert_distributions(
    game: str,
    decision: dict,
    *,
    dimension: str = "main",
) -> dict[str, dict[int, float]]:
    """只讀當期開獎前 decision，建立七個嚴格正值專家分布。"""
    proposals, scores = _proposal_contract(game, decision)
    if dimension == "main":
        domain_size = POOL[game]
        values_per_proposal = PICK_N

        def values(row: dict) -> list[int]:
            numbers = [int(number) for number in row.get("numbers", ())]
            if (
                len(numbers) != PICK_N
                or len(set(numbers)) != PICK_N
                or any(
                    number < 1 or number > domain_size
                    for number in numbers
                )
            ):
                raise ValueError("stacking 主號提案不合法")
            return numbers

    elif dimension == "special" and game == SUPER:
        domain_size = SPECIAL_POOL[SUPER]
        values_per_proposal = 1

        def values(row: dict) -> list[int]:
            special = row.get("special")
            if (
                not isinstance(special, int)
                or special < 1
                or special > domain_size
            ):
                raise ValueError("stacking 第二區提案不合法")
            return [special]

    else:
        raise ValueError("stacking dimension 不支援")

    output: dict[str, dict[int, float]] = {}
    for agent in AGENT_IDS:
        counts = Counter(
            value
            for proposal in proposals
            if proposal["agent"] == agent
            for value in values(proposal)
        )
        denominator = (
            3 * values_per_proposal + SMOOTHING * domain_size
        )
        output[agent] = {
            value: (counts[value] + SMOOTHING) / denominator
            for value in range(1, domain_size + 1)
        }

    maximum_score = max(scores.values())
    proposal_weights = {
        proposal_id: math.exp(
            (score - maximum_score) / DEBATE_TEMPERATURE
        )
        for proposal_id, score in scores.items()
    }
    debate_counts = Counter()
    for proposal in proposals:
        weight = proposal_weights[proposal["proposal_id"]]
        for value in values(proposal):
            debate_counts[value] += weight
    debate_denominator = (
        values_per_proposal
        * math.fsum(proposal_weights.values())
        + SMOOTHING * domain_size
    )
    output[DEBATE_EXPERT] = {
        value: (debate_counts[value] + SMOOTHING)
        / debate_denominator
        for value in range(1, domain_size + 1)
    }
    output[UNIFORM_EXPERT] = {
        value: 1.0 / domain_size
        for value in range(1, domain_size + 1)
    }
    if set(output) != set(EXPERT_IDS):
        raise AssertionError("stacking 專家分布遺漏")
    for distribution in output.values():
        _validate_distribution(
            distribution,
            domain_size=domain_size,
        )
    return output


def mixture_distribution(
    distributions: dict[str, dict[int, float]],
    log_weights: dict[str, float],
) -> dict[int, float]:
    if set(distributions) != set(EXPERT_IDS):
        raise ValueError("stacking mixture 專家分布不完整")
    weights = _softmax(log_weights)
    first = distributions[EXPERT_IDS[0]]
    domain = set(first)
    if any(set(distribution) != domain for distribution in distributions.values()):
        raise ValueError("stacking mixture 專家定義域不一致")
    mixed = {
        value: math.fsum(
            weights[expert] * distributions[expert][value]
            for expert in EXPERT_IDS
        )
        for value in sorted(domain)
    }
    _validate_distribution(mixed, domain_size=len(domain))
    return mixed


def _log_loss(
    distribution: dict[int, float],
    actual: list[int],
) -> float:
    if not actual:
        raise ValueError("stacking log loss 缺少實際結果")
    if len(set(actual)) != len(actual):
        raise ValueError("stacking log loss 實際結果重複")
    try:
        losses = [-math.log(distribution[int(value)]) for value in actual]
    except KeyError as exc:
        raise ValueError("stacking log loss 實際結果超出定義域") from exc
    return statistics.fmean(losses)


def build_probability_score_capsule(
    *,
    game: str,
    target: dict,
    candidate_hash: str,
    source_decision_hash: str,
    main_distribution: dict[int, float],
    special_distribution: dict[int, float] | None,
) -> dict:
    """在 reveal 前凍結完整機率質量，供未來 proper-score 結算。"""
    if game not in (SUPER, LOTTO649):
        raise ValueError("機率評分膠囊遊戲不符")
    _validate_distribution(
        main_distribution,
        domain_size=POOL[game],
    )
    if game == SUPER:
        if special_distribution is None:
            raise ValueError("威力彩機率評分膠囊缺少第二區分布")
        _validate_distribution(
            special_distribution,
            domain_size=SPECIAL_POOL[SUPER],
        )
    elif special_distribution is not None:
        raise ValueError("大樂透機率評分膠囊不得有第二區分布")
    normalized_target = {
        "date": str(target["date"]),
        "period": int(target["period"]),
    }
    if (
        not _is_sha256(candidate_hash)
        or not _is_sha256(source_decision_hash)
    ):
        raise ValueError("機率評分膠囊來源雜湊不符")
    payload = {
        "schema_version": "1",
        "experiment_id": SCORE_CAPSULE_EXPERIMENT_ID,
        "game": game,
        "target": normalized_target,
        "candidate_hash": candidate_hash,
        "protocol_hash": PROTOCOL_HASH,
        "source_decision_hash": source_decision_hash,
        "main_probability_mass": [
            float(main_distribution[number])
            for number in range(1, POOL[game] + 1)
        ],
        "special_probability_mass": (
            [
                float(special_distribution[number])
                for number in range(1, SPECIAL_POOL[SUPER] + 1)
            ]
            if game == SUPER
            else None
        ),
        "scoring_rules": SCORE_CAPSULE_RULES,
        "use": "future_forward_proper_score_only",
    }
    payload["capsule_hash"] = canonical_hash(payload)
    return payload


def validate_probability_score_capsule(
    capsule: dict,
    *,
    game: str,
    target: dict,
    candidate_hash: str,
    source_decision_hash: str,
) -> dict:
    """驗證評分膠囊的來源、完整分布與不可竄改雜湊。"""
    expected_fields = {
        "schema_version",
        "experiment_id",
        "game",
        "target",
        "candidate_hash",
        "protocol_hash",
        "source_decision_hash",
        "main_probability_mass",
        "special_probability_mass",
        "scoring_rules",
        "use",
        "capsule_hash",
    }
    normalized_target = {
        "date": str(target["date"]),
        "period": int(target["period"]),
    }
    if (
        not isinstance(capsule, dict)
        or set(capsule) != expected_fields
        or capsule.get("schema_version") != "1"
        or capsule.get("experiment_id")
        != SCORE_CAPSULE_EXPERIMENT_ID
        or capsule.get("game") != game
        or capsule.get("target") != normalized_target
        or capsule.get("candidate_hash") != candidate_hash
        or capsule.get("protocol_hash") != PROTOCOL_HASH
        or capsule.get("source_decision_hash")
        != source_decision_hash
        or capsule.get("scoring_rules") != SCORE_CAPSULE_RULES
        or capsule.get("use")
        != "future_forward_proper_score_only"
    ):
        raise ValueError("機率評分膠囊契約不符")
    payload = {
        key: value
        for key, value in capsule.items()
        if key != "capsule_hash"
    }
    if capsule.get("capsule_hash") != canonical_hash(payload):
        raise ValueError("機率評分膠囊雜湊不符")
    main_values = capsule.get("main_probability_mass")
    special_values = capsule.get("special_probability_mass")
    if (
        not isinstance(main_values, list)
        or len(main_values) != POOL[game]
    ):
        raise ValueError("機率評分膠囊主號分布不完整")
    try:
        main_distribution = {
            number: float(main_values[number - 1])
            for number in range(1, POOL[game] + 1)
        }
    except (TypeError, ValueError) as exc:
        raise ValueError("機率評分膠囊主號分布格式不符") from exc
    _validate_distribution(
        main_distribution,
        domain_size=POOL[game],
    )
    if game == SUPER:
        if (
            not isinstance(special_values, list)
            or len(special_values) != SPECIAL_POOL[SUPER]
        ):
            raise ValueError("威力彩機率評分膠囊第二區分布不完整")
        try:
            special_distribution = {
                number: float(special_values[number - 1])
                for number in range(1, SPECIAL_POOL[SUPER] + 1)
            }
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "威力彩機率評分膠囊第二區分布格式不符"
            ) from exc
        _validate_distribution(
            special_distribution,
            domain_size=SPECIAL_POOL[SUPER],
        )
    elif special_values is not None:
        raise ValueError("大樂透機率評分膠囊不得有第二區分布")
    return json.loads(json.dumps(capsule))


def settle_probability_score_capsule(
    capsule: dict,
    *,
    game: str,
    target: dict,
    candidate_hash: str,
    source_decision_hash: str,
    actual_main: list[int],
    actual_special: int | None,
    eligible: bool,
) -> dict:
    """只在 reveal 後，以凍結分布計算對數損失與均勻 regret。"""
    verified = validate_probability_score_capsule(
        capsule,
        game=game,
        target=target,
        candidate_hash=candidate_hash,
        source_decision_hash=source_decision_hash,
    )
    if (
        len(actual_main) != PICK_N
        or len(set(actual_main)) != PICK_N
        or any(
            type(number) is not int
            or number < 1
            or number > POOL[game]
            for number in actual_main
        )
    ):
        raise ValueError("機率評分實際主號不合法")
    main_distribution = {
        number: float(
            verified["main_probability_mass"][number - 1]
        )
        for number in range(1, POOL[game] + 1)
    }
    main_loss = _log_loss(main_distribution, actual_main)
    uniform_main_loss = math.log(POOL[game])
    main_regret = main_loss - uniform_main_loss
    if game == SUPER:
        if (
            type(actual_special) is not int
            or actual_special < 1
            or actual_special > SPECIAL_POOL[SUPER]
        ):
            raise ValueError("威力彩機率評分實際第二區不合法")
        special_distribution = {
            number: float(
                verified["special_probability_mass"][number - 1]
            )
            for number in range(1, SPECIAL_POOL[SUPER] + 1)
        }
        special_loss = _log_loss(
            special_distribution,
            [actual_special],
        )
        uniform_special_loss = math.log(SPECIAL_POOL[SUPER])
        special_regret = special_loss - uniform_special_loss
        special_verdict = _score_verdict(special_regret)
    else:
        if actual_special is not None:
            raise ValueError("大樂透機率評分不得有第二區")
        special_loss = None
        uniform_special_loss = None
        special_regret = None
        special_verdict = "not_applicable"
    result = {
        "schema_version": "1",
        "experiment_id": SCORE_CAPSULE_EXPERIMENT_ID,
        "capsule_hash": verified["capsule_hash"],
        "protocol_hash": PROTOCOL_HASH,
        "candidate_hash": candidate_hash,
        "eligible": bool(eligible),
        "main_log_loss": main_loss,
        "uniform_main_log_loss": uniform_main_loss,
        "main_regret_vs_uniform": main_regret,
        "main_verdict": _score_verdict(main_regret),
        "special_log_loss": special_loss,
        "uniform_special_log_loss": uniform_special_loss,
        "special_regret_vs_uniform": special_regret,
        "special_verdict": special_verdict,
        "interpretation": SCORE_RESULT_INTERPRETATION,
    }
    verify_probability_score_result(result, game=game)
    return result


def _score_verdict(regret: float) -> str:
    if math.isclose(regret, 0.0, rel_tol=0.0, abs_tol=1e-15):
        return "tie_uniform"
    return "better_than_uniform" if regret < 0 else "worse_than_uniform"


def verify_probability_score_result(result: dict, *, game: str) -> None:
    """獨立驗證不含原始號碼的 proper-score 摘要。"""
    expected_fields = {
        "schema_version",
        "experiment_id",
        "capsule_hash",
        "protocol_hash",
        "candidate_hash",
        "eligible",
        "main_log_loss",
        "uniform_main_log_loss",
        "main_regret_vs_uniform",
        "main_verdict",
        "special_log_loss",
        "uniform_special_log_loss",
        "special_regret_vs_uniform",
        "special_verdict",
        "interpretation",
    }
    if (
        game not in (SUPER, LOTTO649)
        or not isinstance(result, dict)
        or set(result) != expected_fields
        or result.get("schema_version") != "1"
        or result.get("experiment_id")
        != SCORE_CAPSULE_EXPERIMENT_ID
        or result.get("protocol_hash") != PROTOCOL_HASH
        or not _is_sha256(result.get("capsule_hash"))
        or not _is_sha256(result.get("candidate_hash"))
        or type(result.get("eligible")) is not bool
        or result.get("interpretation")
        != SCORE_RESULT_INTERPRETATION
    ):
        raise ValueError("機率 proper-score 結果契約不符")
    try:
        main_loss = float(result["main_log_loss"])
        uniform_main_loss = float(result["uniform_main_log_loss"])
        main_regret = float(result["main_regret_vs_uniform"])
    except (TypeError, ValueError) as exc:
        raise ValueError("機率 proper-score 主號格式不符") from exc
    if (
        any(
            not math.isfinite(value)
            for value in (
                main_loss,
                uniform_main_loss,
                main_regret,
            )
        )
        or main_loss <= 0
        or not math.isclose(
            uniform_main_loss,
            math.log(POOL[game]),
            rel_tol=0.0,
            abs_tol=1e-15,
        )
        or not math.isclose(
            main_regret,
            main_loss - uniform_main_loss,
            rel_tol=0.0,
            abs_tol=1e-15,
        )
        or result.get("main_verdict") != _score_verdict(main_regret)
    ):
        raise ValueError("機率 proper-score 主號語意不符")
    if game == SUPER:
        try:
            special_loss = float(result["special_log_loss"])
            uniform_special_loss = float(
                result["uniform_special_log_loss"]
            )
            special_regret = float(
                result["special_regret_vs_uniform"]
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "機率 proper-score 第二區格式不符"
            ) from exc
        if (
            any(
                not math.isfinite(value)
                for value in (
                    special_loss,
                    uniform_special_loss,
                    special_regret,
                )
            )
            or special_loss <= 0
            or not math.isclose(
                uniform_special_loss,
                math.log(SPECIAL_POOL[SUPER]),
                rel_tol=0.0,
                abs_tol=1e-15,
            )
            or not math.isclose(
                special_regret,
                special_loss - uniform_special_loss,
                rel_tol=0.0,
                abs_tol=1e-15,
            )
            or result.get("special_verdict")
            != _score_verdict(special_regret)
        ):
            raise ValueError("機率 proper-score 第二區語意不符")
    elif (
        result.get("special_log_loss") is not None
        or result.get("uniform_special_log_loss") is not None
        or result.get("special_regret_vs_uniform") is not None
        or result.get("special_verdict") != "not_applicable"
    ):
        raise ValueError("大樂透 proper-score 第二區欄位不符")


def update_log_weights(
    log_weights: dict[str, float],
    distributions: dict[str, dict[int, float]],
    actual: list[int],
    *,
    sequence: int,
) -> tuple[dict[str, float], dict[str, float]]:
    """Reveal 後更新；回傳新權重與本期各專家 loss。"""
    if not isinstance(sequence, int) or sequence < 1:
        raise ValueError("stacking sequence 必須為正整數")
    _softmax(log_weights)
    if set(distributions) != set(EXPERT_IDS):
        raise ValueError("stacking 更新缺少專家分布")
    losses = {
        expert: _log_loss(distributions[expert], actual)
        for expert in EXPERT_IDS
    }
    uniform_loss = losses[UNIFORM_EXPERT]
    eta = 1.0 / math.sqrt(sequence)
    updated = {
        expert: float(log_weights[expert])
        - eta * (losses[expert] - uniform_loss)
        for expert in EXPERT_IDS
    }
    maximum = max(updated.values())
    centered = {
        expert: updated[expert] - maximum
        for expert in EXPERT_IDS
    }
    if any(not math.isfinite(value) for value in centered.values()):
        raise ValueError("stacking 更新產生非有限權重")
    return centered, losses


def portfolio_from_distribution(
    game: str,
    main_distribution: dict[int, float],
    special_distribution: dict[int, float] | None = None,
) -> tuple[list[dict], dict]:
    """把機率順位映射成五注完全分散結構。"""
    if game not in (SUPER, LOTTO649):
        raise ValueError("stacking 不支援的遊戲")
    _validate_distribution(
        main_distribution,
        domain_size=POOL[game],
    )
    ranking = sorted(
        main_distribution,
        key=lambda number: (
            -main_distribution[number],
            number,
        ),
    )
    selected = ranking[:SELECTED_MAIN_NUMBERS]
    bins = [[] for _ in range(SELECTED_TICKETS)]
    for index, number in enumerate(selected):
        bins[index % SELECTED_TICKETS].append(number)
    bin_mass = [
        math.fsum(main_distribution[number] for number in numbers)
        for numbers in bins
    ]
    if game == SUPER:
        if special_distribution is None:
            raise ValueError("威力彩 stacking 缺少第二區分布")
        _validate_distribution(
            special_distribution,
            domain_size=SPECIAL_POOL[SUPER],
        )
        specials = sorted(
            special_distribution,
            key=lambda value: (
                -special_distribution[value],
                value,
            ),
        )[:SELECTED_TICKETS]
        bin_order = sorted(
            range(SELECTED_TICKETS),
            key=lambda index: (-bin_mass[index], index),
        )
        special_by_bin = {
            bin_index: specials[rank]
            for rank, bin_index in enumerate(bin_order)
        }
    else:
        if special_distribution is not None:
            raise ValueError("大樂透 stacking 不得有第二區分布")
        special_by_bin = {
            index: None for index in range(SELECTED_TICKETS)
        }
        specials = []
    tickets = [
        {
            "slot": index + 1,
            "source_agent": "probability_stacking_synthesizer",
            "source_proposal": f"probability-stacking:{index + 1}",
            "numbers": sorted(numbers),
            "special": special_by_bin[index],
        }
        for index, numbers in enumerate(bins)
    ]
    for ticket in tickets:
        validate_pick(game, ticket["numbers"], ticket["special"])
    structure = portfolio_structure(game, tickets)
    if (
        structure["main_union_size"] != SELECTED_MAIN_NUMBERS
        or structure["maximum_pairwise_main_overlap"] != 0
        or (
            game == SUPER
            and structure["special_coverage_probability"]
            != SELECTED_TICKETS / SPECIAL_POOL[SUPER]
        )
    ):
        raise RuntimeError("stacking 五注未達完全分散結構")
    return tickets, {
        "selected_main_numbers": selected,
        "selected_specials": specials if game == SUPER else None,
        "ticket_main_probability_mass": bin_mass,
        "structure": structure,
    }


def _candidate_payload(result: dict) -> dict:
    return {
        "schema_version": "1",
        "experiment_id": FORWARD_EXPERIMENT_ID,
        "source_experiment_id": EXPERIMENT_ID,
        "protocol_hash": PROTOCOL_HASH,
        "parameters": PROTOCOL_CONFIG,
        "use": "future_forward_shadow_only",
        "historical_evidence_status": (
            "reused_history_for_prequential_initialization_only"
        ),
        "fitted_through": {
            game: result["data_quality"]["source_last_dates"][game]
            for game in (SUPER, LOTTO649)
        },
        "source_ledger_hashes": {
            game: result["data_quality"]["ledger_verification"][game][
                "ledger_sha256"
            ]
            for game in (SUPER, LOTTO649)
        },
        "models": result["final_models"],
        "structural_optimum_proof": structural_proof_reference(),
    }


def validate_forward_candidate(candidate: dict) -> dict:
    if not isinstance(candidate, dict):
        raise ValueError("stacking forward candidate 格式不符")
    payload = {
        key: value
        for key, value in candidate.items()
        if key != "candidate_hash"
    }
    if (
        set(candidate) != {
            "schema_version",
            "experiment_id",
            "source_experiment_id",
            "protocol_hash",
            "parameters",
            "use",
            "historical_evidence_status",
            "fitted_through",
            "source_ledger_hashes",
            "models",
            "structural_optimum_proof",
            "candidate_hash",
        }
        or candidate.get("schema_version") != "1"
        or candidate.get("experiment_id") != FORWARD_EXPERIMENT_ID
        or candidate.get("source_experiment_id") != EXPERIMENT_ID
        or candidate.get("protocol_hash") != PROTOCOL_HASH
        or candidate.get("parameters") != PROTOCOL_CONFIG
        or candidate.get("use") != "future_forward_shadow_only"
        or candidate.get("historical_evidence_status")
        != "reused_history_for_prequential_initialization_only"
        or candidate.get("structural_optimum_proof")
        != structural_proof_reference()
        or candidate.get("candidate_hash") != canonical_hash(payload)
    ):
        raise ValueError("stacking forward candidate 契約不符")
    fitted = candidate.get("fitted_through")
    ledgers = candidate.get("source_ledger_hashes")
    models = candidate.get("models")
    try:
        fitted_dates = {
            game: date.fromisoformat(value)
            for game, value in fitted.items()
        }
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("stacking forward candidate 日期格式不符") from exc
    if (
        not isinstance(fitted, dict)
        or set(fitted) != {SUPER, LOTTO649}
        or set(fitted_dates) != {SUPER, LOTTO649}
        or not isinstance(ledgers, dict)
        or set(ledgers) != {SUPER, LOTTO649}
        or any(
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
            for value in ledgers.values()
        )
        or not isinstance(models, dict)
        or set(models) != {SUPER, LOTTO649}
    ):
        raise ValueError("stacking forward candidate 來源欄位不符")
    for game in (SUPER, LOTTO649):
        model = models[game]
        expected = {"main_log_weights", "main_weights"}
        if game == SUPER:
            expected |= {"special_log_weights", "special_weights"}
        if set(model) != expected:
            raise ValueError("stacking forward model 欄位不符")
        for prefix in ("main", "special") if game == SUPER else ("main",):
            logs = model[f"{prefix}_log_weights"]
            weights = model[f"{prefix}_weights"]
            recalculated = _softmax(logs)
            if (
                not isinstance(weights, dict)
                or set(weights) != set(EXPERT_IDS)
                or any(
                    not math.isclose(
                        float(weights[expert]),
                        recalculated[expert],
                        rel_tol=0.0,
                        abs_tol=1e-15,
                    )
                    for expert in EXPERT_IDS
                )
            ):
                raise ValueError("stacking forward model 權重不符")
    return json.loads(json.dumps(candidate))


def select_probability_stacked_portfolio(
    game: str,
    decision: dict,
    candidate: dict,
) -> tuple[list[dict], dict]:
    """用已驗證的過去模型與當期 decision 建立 future-only 五注。"""
    verified = validate_forward_candidate(candidate)
    if game not in (SUPER, LOTTO649):
        raise ValueError("stacking 不支援的遊戲")
    try:
        target_date = date.fromisoformat(
            decision.get("target", {}).get("date")
        )
        fitted_date = date.fromisoformat(
            verified["fitted_through"][game]
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("stacking 目標日期格式不符") from exc
    if fitted_date >= target_date:
        raise ValueError("stacking candidate 含目標期或未來資料")
    model = verified["models"][game]
    main_experts = expert_distributions(
        game,
        decision,
        dimension="main",
    )
    main = mixture_distribution(
        main_experts,
        model["main_log_weights"],
    )
    special = None
    if game == SUPER:
        special = mixture_distribution(
            expert_distributions(
                game,
                decision,
                dimension="special",
            ),
            model["special_log_weights"],
        )
    tickets, selection = portfolio_from_distribution(
        game,
        main,
        special,
    )
    score_capsule = build_probability_score_capsule(
        game=game,
        target=decision["target"],
        candidate_hash=verified["candidate_hash"],
        source_decision_hash=decision["decision_hash"],
        main_distribution=main,
        special_distribution=special,
    )
    evidence = {
        "candidate_hash": verified["candidate_hash"],
        "protocol_hash": PROTOCOL_HASH,
        "game": game,
        "target": decision["target"],
        "source_decision_hash": decision["decision_hash"],
        "selected_main_numbers": selection["selected_main_numbers"],
        "selected_specials": selection["selected_specials"],
        "ticket_main_probability_mass": selection[
            "ticket_main_probability_mass"
        ],
        "structure": selection["structure"],
        "score_capsule_hash": score_capsule["capsule_hash"],
    }
    return tickets, {
        "experiment_id": FORWARD_EXPERIMENT_ID,
        "candidate_hash": verified["candidate_hash"],
        "protocol_hash": PROTOCOL_HASH,
        "selection_hash": canonical_hash(
            {"game": game, "tickets": tickets}
        ),
        "support_evidence_hash": canonical_hash(evidence),
        "selected_main_numbers": selection["selected_main_numbers"],
        "selected_specials": selection["selected_specials"],
        "ticket_main_probability_mass": selection[
            "ticket_main_probability_mass"
        ],
        "structure": selection["structure"],
        "score_capsule": score_capsule,
        "use": "future_forward_shadow_only",
    }


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def _direction_halves(values: list[float]) -> dict:
    midpoint = len(values) // 2
    return {
        "first_half_mean": _mean(values[:midpoint]),
        "second_half_mean": _mean(values[midpoint:]),
        "same_nonzero_direction": (
            _mean(values[:midpoint]) * _mean(values[midpoint:]) > 0
            if midpoint and len(values) - midpoint
            else False
        ),
    }


def run_probability_stacking(
    ledger_paths: dict[str, Path],
    *,
    base: Path,
    verify_ledgers: bool = True,
) -> dict:
    """依時間順序初始化權重；舊資料只作描述，不作升級檢定。"""
    if set(ledger_paths) != {SUPER, LOTTO649}:
        raise ValueError("stacking 需要兩款遊戲 ledger")
    base = Path(base)
    records_before = tree_sha256(base / "records")
    verification = {}
    source_last_dates = {}
    source_first_dates = {}
    summaries = {}
    final_models = {}

    for game in (SUPER, LOTTO649):
        path = Path(ledger_paths[game])
        verification[game] = (
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
                "ledger_sha256": _file_sha256(path),
                "last_event_hash": None,
            }
        )
        main_logs = {expert: 0.0 for expert in EXPERT_IDS}
        special_logs = (
            {expert: 0.0 for expert in EXPERT_IDS}
            if game == SUPER
            else None
        )
        main_losses = {expert: [] for expert in EXPERT_IDS}
        special_losses = (
            {expert: [] for expert in EXPERT_IDS}
            if game == SUPER
            else None
        )
        mixture_main_losses = []
        mixture_special_losses = []
        metric_names = (
            "union_main_hits",
            "best_main_hits",
            "any_three_plus",
            "any_prize",
        )
        deltas = {metric: [] for metric in metric_names}
        previous_key = None
        seen_periods = set()
        sequence = 0

        with path.open(encoding="utf-8") as handle:
            for sequence, line in enumerate(handle, 1):
                event = json.loads(line)
                _validate_event(event, game, sequence)
                reveal = event["reveal"]
                key = (str(reveal["date"]), int(reveal["period"]))
                if previous_key is not None and key <= previous_key:
                    raise ValueError("stacking 期別未嚴格遞增")
                if key[1] in seen_periods:
                    raise ValueError("stacking 期別重複")
                previous_key = key
                seen_periods.add(key[1])
                source_first_dates.setdefault(game, key[0])
                source_last_dates[game] = key[0]
                decision = event["decision"]

                main_experts = expert_distributions(
                    game,
                    decision,
                    dimension="main",
                )
                main_mix = mixture_distribution(
                    main_experts,
                    main_logs,
                )
                special_experts = None
                special_mix = None
                if game == SUPER:
                    special_experts = expert_distributions(
                        game,
                        decision,
                        dimension="special",
                    )
                    special_mix = mixture_distribution(
                        special_experts,
                        special_logs,
                    )
                tickets, _ = portfolio_from_distribution(
                    game,
                    main_mix,
                    special_mix,
                )
                baseline, _ = select_consensus_disjoint_portfolio(
                    game,
                    decision,
                )
                candidate_result = portfolio_metrics(
                    game,
                    tickets,
                    reveal,
                )
                baseline_result = portfolio_metrics(
                    game,
                    baseline,
                    reveal,
                )
                for metric in metric_names:
                    deltas[metric].append(
                        candidate_result[metric]
                        - baseline_result[metric]
                    )

                actual_main = [
                    int(number) for number in reveal["numbers"]
                ]
                mixture_main_losses.append(
                    _log_loss(main_mix, actual_main)
                )
                main_logs, losses = update_log_weights(
                    main_logs,
                    main_experts,
                    actual_main,
                    sequence=sequence,
                )
                for expert in EXPERT_IDS:
                    main_losses[expert].append(losses[expert])

                if game == SUPER:
                    actual_special = [int(reveal["special"])]
                    mixture_special_losses.append(
                        _log_loss(special_mix, actual_special)
                    )
                    special_logs, losses = update_log_weights(
                        special_logs,
                        special_experts,
                        actual_special,
                        sequence=sequence,
                    )
                    for expert in EXPERT_IDS:
                        special_losses[expert].append(losses[expert])

        if sequence == 0:
            raise ValueError("stacking ledger 不得為空")
        if verification[game]["lines"] != sequence:
            raise AssertionError("stacking 實際讀取期數不符")
        summary = {
            "game": game,
            "game_name": GAME_NAMES[game],
            "draws": sequence,
            "first_date": source_first_dates[game],
            "last_date": source_last_dates[game],
            "mean_mixture_main_log_loss": _mean(
                mixture_main_losses
            ),
            "mean_expert_main_log_loss": {
                expert: _mean(main_losses[expert])
                for expert in EXPERT_IDS
            },
            "stacking_minus_consensus": {
                metric: {
                    "mean": _mean(deltas[metric]),
                    **_direction_halves(deltas[metric]),
                }
                for metric in metric_names
            },
        }
        model = {
            "main_log_weights": main_logs,
            "main_weights": _softmax(main_logs),
        }
        if game == SUPER:
            summary["mean_mixture_special_log_loss"] = _mean(
                mixture_special_losses
            )
            summary["mean_expert_special_log_loss"] = {
                expert: _mean(special_losses[expert])
                for expert in EXPERT_IDS
            }
            model.update(
                {
                    "special_log_weights": special_logs,
                    "special_weights": _softmax(special_logs),
                }
            )
        summaries[game] = summary
        final_models[game] = model

    records_after = tree_sha256(base / "records")
    result = {
        "schema_version": "1",
        "experiment_id": EXPERIMENT_ID,
        "source_experiment_id": LOOP_EXPERIMENT_ID,
        "generated_at": max(source_last_dates.values())
        + "T23:59:59+08:00",
        "question": (
            "逐期 proper-score 縮權能否建立比未校準辯論共識更可信的"
            "未來號碼標籤 shadow？"
        ),
        "methodology": {
            **PROTOCOL_CONFIG,
            "protocol_hash": PROTOCOL_HASH,
            "unit": "每款遊戲每期一個開獎前專家集合",
            "lookahead_control": (
                "第 t 期票券使用 update 前權重；第 t 期 reveal 只更新"
                "第 t+1 期權重。"
            ),
            "structural_optimum_proof": structural_proof_reference(),
        },
        "data_quality": {
            "status": "pass",
            "ledger_verification": verification,
            "source_first_dates": source_first_dates,
            "source_last_dates": source_last_dates,
            "chronology": "strictly_increasing",
            "duplicate_periods": 0,
            "proposal_coverage": "5 agents × 3 proposals per draw",
            "critique_coverage": "60 cross-agent critiques per draw",
            "candidate_score_coverage": "15 per draw",
            "expert_distributions": (
                "strictly_positive_finite_and_sum_to_one"
            ),
        },
        "prequential_summary": summaries,
        "final_models": final_models,
        "conclusion": {
            "status": "future_shadow_only",
            "historical_promotion_eligible": False,
            "reason": (
                "完整歷史已被多項研究使用；描述性 prequential 結果"
                "不得重開歷史 holdout。"
            ),
            "next_evidence": (
                "只接受不可回填的前向 52/104/208/416/832 共同 checkpoint。"
            ),
        },
        "records_integrity": {
            "before_sha256": records_before,
            "after_sha256": records_after,
            "unchanged": records_before == records_after,
        },
        "limitations": [
            "公平模型下每個合法號碼標籤理論等機率。",
            "歷史結果只初始化 online weights，不是新的確認性 holdout。",
            "前向樣本未達共同 checkpoint 前不得宣稱機率提高。",
            "本系統純模擬，不構成購買或下注建議。",
        ],
    }
    candidate_payload = _candidate_payload(result)
    result["future_forward_shadow_candidate"] = {
        **candidate_payload,
        "candidate_hash": canonical_hash(candidate_payload),
    }
    validate_forward_candidate(
        result["future_forward_shadow_candidate"]
    )
    if not result["records_integrity"]["unchanged"]:
        raise RuntimeError("stacking 研究不應改動正式 records")
    return result


def write_results(result: dict, output_dir: Path) -> Path:
    validate_forward_candidate(
        result["future_forward_shadow_candidate"]
    )
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "probability_stacking.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return path
