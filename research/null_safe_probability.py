"""以有效的公平零模型證據閘門限制號碼機率偏移。

現行七專家 stacking 仍會留下極小的非均勻質量。這個模組使用完整六號子集
likelihood 建立可重啟的 mixture e-process；只有開獎前證據超過固定門檻時，
下一期才採用 stacking 分布，否則回退到精確均勻機率與既有 coverage 標籤。
歷史只用來初始化狀態與描述，不作升級證據。
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import statistics
from copy import deepcopy
from pathlib import Path

from engine.agent_loop import (
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
from research.gates import tree_sha256
from research.max_coverage import (
    select_consensus_disjoint_portfolio,
)
from research.portfolio_coverage import portfolio_structure
from research.probability_stacking import (
    EXPERT_IDS,
    FORWARD_EXPERIMENT_ID as STACKING_FORWARD_EXPERIMENT_ID,
    PROTOCOL_HASH as STACKING_PROTOCOL_HASH,
    _log_loss,
    _softmax,
    expert_distributions,
    mixture_distribution,
    portfolio_from_distribution,
    update_log_weights,
    validate_forward_candidate as validate_stacking_forward_candidate,
)
from research.structural_optimum import structural_proof_reference


EXPERIMENT_ID = "null-safe-probability-gate-v1"
FORWARD_EXPERIMENT_ID = "null-safe-probability-forward-shadow-v1"
SCORE_CAPSULE_EXPERIMENT_ID = (
    "null-safe-probability-score-capsule-v1"
)
FORWARD_STATE_EXPERIMENT_ID = (
    "null-safe-probability-forward-state-v1"
)
E_PROCESS_PROTOCOL_ID = "restart-mixture-e-process-v1"
FAMILY_ALPHA = 0.05
EVIDENCE_STREAMS = (
    "super_main",
    "super_special",
    "lotto649_main",
)
STREAM_ALPHA = FAMILY_ALPHA / len(EVIDENCE_STREAMS)
ACTIVATION_E_THRESHOLD = 1.0 / STREAM_ALPHA
LOG_ACTIVATION_E_THRESHOLD = math.log(ACTIVATION_E_THRESHOLD)
START_WEIGHT_NORMALIZER = 6.0 / math.pi**2
SENSITIVITY_THRESHOLDS = (3.0, 20.0, ACTIVATION_E_THRESHOLD)

PROTOCOL_CONFIG = {
    "e_process_protocol_id": E_PROCESS_PROTOCOL_ID,
    "main_likelihood": (
        "product_weighted_unordered_six_number_subset"
    ),
    "special_likelihood": "categorical_probability_mass",
    "restart_start_weight": "6/(pi^2*s^2)",
    "family_alpha": FAMILY_ALPHA,
    "evidence_streams": list(EVIDENCE_STREAMS),
    "stream_alpha": STREAM_ALPHA,
    "activation_e_threshold": ACTIVATION_E_THRESHOLD,
    "activation_timing": (
        "target_t_uses_only_e_value_through_reveal_t_minus_1"
    ),
    "inactive_main_forecast": "exact_discrete_uniform",
    "inactive_special_forecast": "exact_discrete_uniform",
    "inactive_ticket_labels": "consensus_coverage",
    "historical_use": "initialization_and_description_only",
    "promotion_evidence": "future_forward_scores_only",
}
PROTOCOL_HASH = canonical_hash(PROTOCOL_CONFIG)
SCORE_CAPSULE_RULES = {
    "main_safe_score": (
        "negative_log_probability_of_complete_unordered_six_number_subset"
    ),
    "special_safe_score": "negative_log_probability_mass",
    "evidence_model": "ungated_underlying_stacking_distribution",
    "baseline": "exact_discrete_uniform",
    "state_update": (
        "restart_mixture_e_process_with_reveal_log_likelihood_ratio"
    ),
    "direction": "lower_safe_regret_is_better",
}
SCORE_RESULT_INTERPRETATION = (
    "安全分布只用開獎前凍結的完整合法子集機率計分；"
    "未開牌的 stacking 分布只更新 e-process，當期不得回頭改 gate。"
)


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _logaddexp(left: float | None, right: float | None) -> float:
    if left is None:
        if right is None:
            raise ValueError("logaddexp 至少需要一個值")
        return float(right)
    if right is None:
        return float(left)
    left = float(left)
    right = float(right)
    if not math.isfinite(left) or not math.isfinite(right):
        raise ValueError("logaddexp 只接受有限值")
    maximum = max(left, right)
    return maximum + math.log(
        math.exp(left - maximum) + math.exp(right - maximum)
    )


def _log_tail(allocated_start_weight: float) -> float | None:
    tail = max(0.0, 1.0 - allocated_start_weight)
    return math.log(tail) if tail > 0 else None


def _uniform_distribution(domain_size: int) -> dict[int, float]:
    if not isinstance(domain_size, int) or domain_size < 1:
        raise ValueError("均勻分布定義域不合法")
    return {
        number: 1.0 / domain_size
        for number in range(1, domain_size + 1)
    }


def _validate_distribution(
    distribution: dict[int, float],
    *,
    domain_size: int,
) -> dict[int, float]:
    if (
        not isinstance(distribution, dict)
        or set(distribution) != set(range(1, domain_size + 1))
    ):
        raise ValueError("機率分布定義域不完整")
    values = {
        number: float(distribution[number])
        for number in range(1, domain_size + 1)
    }
    if (
        any(
            not math.isfinite(value) or value <= 0
            for value in values.values()
        )
        or not math.isclose(
            math.fsum(values.values()),
            1.0,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
    ):
        raise ValueError("機率分布必須為有限正值且總和為 1")
    return values


def log_elementary_symmetric(
    values: list[float],
    order: int,
) -> float:
    """以 O(pool × order) 計算 elementary symmetric polynomial 的 log。"""
    if (
        not isinstance(values, list)
        or not isinstance(order, int)
        or order < 1
        or order > len(values)
    ):
        raise ValueError("elementary symmetric 輸入不合法")
    numeric = [float(value) for value in values]
    if any(
        not math.isfinite(value) or value <= 0
        for value in numeric
    ):
        raise ValueError("elementary symmetric 只接受有限正值")
    dynamic: list[float | None] = [0.0] + [None] * order
    for value in numeric:
        log_value = math.log(value)
        for index in range(order, 0, -1):
            include = (
                dynamic[index - 1] + log_value
                if dynamic[index - 1] is not None
                else None
            )
            dynamic[index] = _logaddexp(
                dynamic[index],
                include,
            ) if (
                dynamic[index] is not None or include is not None
            ) else None
    if dynamic[order] is None:
        raise AssertionError("elementary symmetric 無法計算")
    return dynamic[order]


def weighted_subset_log_probability(
    distribution: dict[int, float],
    actual: list[int],
) -> float:
    """定義 P(S) ∝ product(p_i) 的合法無序子集 likelihood。"""
    domain_size = len(distribution)
    verified = _validate_distribution(
        distribution,
        domain_size=domain_size,
    )
    if (
        not isinstance(actual, list)
        or len(actual) != PICK_N
        or len(set(actual)) != PICK_N
        or any(
            type(number) is not int
            or number < 1
            or number > domain_size
            for number in actual
        )
    ):
        raise ValueError("子集 likelihood 的實際主號不合法")
    return math.fsum(
        math.log(verified[number]) for number in actual
    ) - log_elementary_symmetric(
        list(verified.values()),
        PICK_N,
    )


def subset_log_likelihood_ratio_vs_uniform(
    distribution: dict[int, float],
    actual: list[int],
) -> float:
    log_probability = weighted_subset_log_probability(
        distribution,
        actual,
    )
    return log_probability + math.log(
        math.comb(len(distribution), PICK_N)
    )


def initial_e_process_state() -> dict:
    return {
        "schema_version": "1",
        "protocol_id": E_PROCESS_PROTOCOL_ID,
        "sequence": 0,
        "log_active_component_wealth": None,
        "allocated_start_weight": 0.0,
        "log_e_value": 0.0,
    }


def validate_e_process_state(state: dict) -> dict:
    expected_fields = {
        "schema_version",
        "protocol_id",
        "sequence",
        "log_active_component_wealth",
        "allocated_start_weight",
        "log_e_value",
    }
    if (
        not isinstance(state, dict)
        or set(state) != expected_fields
        or state.get("schema_version") != "1"
        or state.get("protocol_id") != E_PROCESS_PROTOCOL_ID
        or type(state.get("sequence")) is not int
        or state["sequence"] < 0
    ):
        raise ValueError("e-process state 契約不符")
    sequence = state["sequence"]
    try:
        allocated = float(state["allocated_start_weight"])
        log_e_value = float(state["log_e_value"])
    except (TypeError, ValueError) as exc:
        raise ValueError("e-process state 數值格式不符") from exc
    expected_allocated = math.fsum(
        START_WEIGHT_NORMALIZER / (index * index)
        for index in range(1, sequence + 1)
    )
    if (
        not math.isfinite(allocated)
        or not 0 <= allocated <= 1
        or not math.isclose(
            allocated,
            expected_allocated,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        or not math.isfinite(log_e_value)
    ):
        raise ValueError("e-process state 累積權重不符")
    active = state["log_active_component_wealth"]
    if sequence == 0:
        if active is not None or log_e_value != 0.0:
            raise ValueError("初始 e-process state 不符")
    else:
        try:
            active = float(active)
        except (TypeError, ValueError) as exc:
            raise ValueError("e-process active wealth 格式不符") from exc
        if not math.isfinite(active):
            raise ValueError("e-process active wealth 非有限")
        expected_log_e = _logaddexp(active, _log_tail(allocated))
        if not math.isclose(
            log_e_value,
            expected_log_e,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError("e-process e-value 無法重建")
    return deepcopy(state)


def restart_e_process_step(
    state: dict,
    log_likelihood_ratio: float,
) -> dict:
    verified = validate_e_process_state(state)
    try:
        log_lr = float(log_likelihood_ratio)
    except (TypeError, ValueError) as exc:
        raise ValueError("e-process log likelihood ratio 格式不符") from exc
    if not math.isfinite(log_lr):
        raise ValueError("e-process log likelihood ratio 必須有限")
    sequence = verified["sequence"] + 1
    start_weight = START_WEIGHT_NORMALIZER / (sequence * sequence)
    previous_active = verified["log_active_component_wealth"]
    base = _logaddexp(
        float(previous_active) if previous_active is not None else None,
        math.log(start_weight),
    )
    log_active = base + log_lr
    allocated = (
        float(verified["allocated_start_weight"]) + start_weight
    )
    return validate_e_process_state(
        {
            "schema_version": "1",
            "protocol_id": E_PROCESS_PROTOCOL_ID,
            "sequence": sequence,
            "log_active_component_wealth": log_active,
            "allocated_start_weight": allocated,
            "log_e_value": _logaddexp(
                log_active,
                _log_tail(allocated),
            ),
        }
    )


def gate_is_active(
    state: dict,
    *,
    threshold: float = ACTIVATION_E_THRESHOLD,
) -> bool:
    verified = validate_e_process_state(state)
    try:
        numeric_threshold = float(threshold)
    except (TypeError, ValueError) as exc:
        raise ValueError("e-process threshold 格式不符") from exc
    if not math.isfinite(numeric_threshold) or numeric_threshold <= 1:
        raise ValueError("e-process threshold 必須大於 1")
    return float(verified["log_e_value"]) >= math.log(
        numeric_threshold
    )


def null_safe_distribution(
    distribution: dict[int, float],
    state: dict,
) -> tuple[dict[int, float], bool]:
    verified = _validate_distribution(
        distribution,
        domain_size=len(distribution),
    )
    active = gate_is_active(state)
    return (
        verified
        if active
        else _uniform_distribution(len(verified)),
        active,
    )


def _mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def _display_e_value(log_e_value: float) -> float:
    return (
        math.exp(log_e_value)
        if log_e_value < math.log(float.fromhex("0x1.fffffffffffffp+1023"))
        else float.fromhex("0x1.fffffffffffffp+1023")
    )


def _stream_summary(
    *,
    mixture_losses: list[float],
    safe_losses: list[float],
    uniform_loss: float,
    log_likelihood_ratios: list[float],
    prior_log_e_values: list[float],
    final_state: dict,
) -> dict:
    mixture_regret = _mean(mixture_losses) - uniform_loss
    safe_regret = _mean(safe_losses) - uniform_loss
    all_log_e_values = [0.0] + [
        float(value) for value in prior_log_e_values[1:]
    ] + [float(final_state["log_e_value"])]
    return {
        "draws": len(mixture_losses),
        "mean_existing_mixture_log_loss": _mean(mixture_losses),
        "mean_null_safe_log_loss": _mean(safe_losses),
        "uniform_log_loss": uniform_loss,
        "existing_mixture_regret_vs_uniform": mixture_regret,
        "null_safe_regret_vs_uniform": safe_regret,
        "null_safe_improvement_vs_existing": (
            mixture_regret - safe_regret
        ),
        "cumulative_log_likelihood_ratio_vs_uniform": math.fsum(
            log_likelihood_ratios
        ),
        "maximum_restart_e_value": _display_e_value(
            max(all_log_e_values)
        ),
        "final_restart_e_value": _display_e_value(
            float(final_state["log_e_value"])
        ),
        "activation_periods": sum(
            log_e >= LOG_ACTIVATION_E_THRESHOLD
            for log_e in prior_log_e_values
        ),
        "sensitivity_activation_periods": {
            str(threshold): sum(
                log_e >= math.log(threshold)
                for log_e in prior_log_e_values
            )
            for threshold in SENSITIVITY_THRESHOLDS
        },
        "final_state": validate_e_process_state(final_state),
    }


def _candidate_payload(result: dict) -> dict:
    models = {}
    for game in (SUPER, LOTTO649):
        source = result["final_models"][game]
        model = {
            "main_log_weights": source["main_log_weights"],
            "main_weights": source["main_weights"],
            "main_e_process": source["main_e_process"],
            "main_gate_active": source["main_gate_active"],
        }
        if game == SUPER:
            model.update(
                {
                    "special_log_weights": source[
                        "special_log_weights"
                    ],
                    "special_weights": source["special_weights"],
                    "special_e_process": source[
                        "special_e_process"
                    ],
                    "special_gate_active": source[
                        "special_gate_active"
                    ],
                }
            )
        models[game] = model
    return {
        "schema_version": "1",
        "experiment_id": FORWARD_EXPERIMENT_ID,
        "source_experiment_id": EXPERIMENT_ID,
        "underlying_stacking_experiment_id": (
            STACKING_FORWARD_EXPERIMENT_ID
        ),
        "underlying_stacking_protocol_hash": (
            STACKING_PROTOCOL_HASH
        ),
        "protocol_hash": PROTOCOL_HASH,
        "parameters": PROTOCOL_CONFIG,
        "use": "future_forward_shadow_only",
        "historical_evidence_status": (
            "descriptive_only_not_promotion"
        ),
        "fitted_through": result["data_quality"]["source_last_dates"],
        "source_ledger_hashes": {
            game: result["data_quality"]["ledger_verification"][game][
                "ledger_sha256"
            ]
            for game in (SUPER, LOTTO649)
        },
        "models": models,
        "structural_optimum_proof": structural_proof_reference(),
    }


def validate_forward_candidate(candidate: dict) -> dict:
    expected_fields = {
        "schema_version",
        "experiment_id",
        "source_experiment_id",
        "underlying_stacking_experiment_id",
        "underlying_stacking_protocol_hash",
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
    if (
        not isinstance(candidate, dict)
        or set(candidate) != expected_fields
        or candidate.get("schema_version") != "1"
        or candidate.get("experiment_id") != FORWARD_EXPERIMENT_ID
        or candidate.get("source_experiment_id") != EXPERIMENT_ID
        or candidate.get("underlying_stacking_experiment_id")
        != STACKING_FORWARD_EXPERIMENT_ID
        or candidate.get("underlying_stacking_protocol_hash")
        != STACKING_PROTOCOL_HASH
        or candidate.get("protocol_hash") != PROTOCOL_HASH
        or candidate.get("parameters") != PROTOCOL_CONFIG
        or candidate.get("use") != "future_forward_shadow_only"
        or candidate.get("historical_evidence_status")
        != "descriptive_only_not_promotion"
        or set(candidate.get("fitted_through", {}))
        != {SUPER, LOTTO649}
        or set(candidate.get("source_ledger_hashes", {}))
        != {SUPER, LOTTO649}
        or set(candidate.get("models", {})) != {SUPER, LOTTO649}
        or any(
            not _is_sha256(value)
            for value in candidate["source_ledger_hashes"].values()
        )
    ):
        raise ValueError("null-safe forward candidate 契約不符")
    for game in (SUPER, LOTTO649):
        model = candidate["models"][game]
        expected_model_fields = {
            "main_log_weights",
            "main_weights",
            "main_e_process",
            "main_gate_active",
        }
        if game == SUPER:
            expected_model_fields.update(
                {
                    "special_log_weights",
                    "special_weights",
                    "special_e_process",
                    "special_gate_active",
                }
            )
        if set(model) != expected_model_fields:
            raise ValueError("null-safe candidate model 欄位不符")
        # Keep the derived weights for readable, backward-compatible JSON.
        # They are informational only: math.exp()/libm can differ across
        # platforms, so runtime calculations must use the log weights.
        if (
            set(model["main_log_weights"]) != set(EXPERT_IDS)
            or set(model["main_weights"]) != set(EXPERT_IDS)
            or any(
                not math.isfinite(float(value))
                for value in model["main_log_weights"].values()
            )
            or any(
                not math.isfinite(float(value))
                for value in model["main_weights"].values()
            )
        ):
            raise ValueError("null-safe candidate 主號模型不符")
        main_state = validate_e_process_state(
            model["main_e_process"]
        )
        if (
            type(model["main_gate_active"]) is not bool
            or model["main_gate_active"]
            is not gate_is_active(main_state)
        ):
            raise ValueError("null-safe candidate 主號閘門不符")
        if game == SUPER:
            if (
                set(model["special_log_weights"])
                != set(EXPERT_IDS)
                or set(model["special_weights"]) != set(EXPERT_IDS)
                or any(
                    not math.isfinite(float(value))
                    for value in model[
                        "special_log_weights"
                    ].values()
                )
                or any(
                    not math.isfinite(float(value))
                    for value in model["special_weights"].values()
                )
            ):
                raise ValueError("null-safe candidate 第二區模型不符")
            special_state = validate_e_process_state(
                model["special_e_process"]
            )
            if (
                type(model["special_gate_active"]) is not bool
                or model["special_gate_active"]
                is not gate_is_active(special_state)
            ):
                raise ValueError("null-safe candidate 第二區閘門不符")
    payload = {
        key: value
        for key, value in candidate.items()
        if key != "candidate_hash"
    }
    if candidate.get("candidate_hash") != canonical_hash(payload):
        raise ValueError("null-safe candidate hash 不符")
    return deepcopy(candidate)


def forecast_null_safe_distributions(
    game: str,
    decision: dict,
    candidate: dict,
) -> dict:
    verified = validate_forward_candidate(candidate)
    if (
        game not in (SUPER, LOTTO649)
        or decision.get("game") != game
        or str(decision.get("target", {}).get("date", ""))
        <= str(verified["fitted_through"][game])
    ):
        raise ValueError("null-safe forecast 不得含目標期 reveal")
    model = verified["models"][game]
    main_experts = expert_distributions(
        game,
        decision,
        dimension="main",
    )
    main_mixture = mixture_distribution(
        main_experts,
        model["main_log_weights"],
    )
    main, main_active = null_safe_distribution(
        main_mixture,
        model["main_e_process"],
    )
    if game == SUPER:
        special_experts = expert_distributions(
            game,
            decision,
            dimension="special",
        )
        special_mixture = mixture_distribution(
            special_experts,
            model["special_log_weights"],
        )
        special, special_active = null_safe_distribution(
            special_mixture,
            model["special_e_process"],
        )
    else:
        special = None
        special_mixture = None
        special_active = False
    return {
        "main_distribution": main,
        "special_distribution": special,
        "main_mixture_distribution": main_mixture,
        "special_mixture_distribution": special_mixture,
        "main_gate_active": main_active,
        "special_gate_active": special_active,
    }


def select_null_safe_portfolio(
    game: str,
    decision: dict,
    candidate: dict,
) -> tuple[list[dict], dict]:
    verified = validate_forward_candidate(candidate)
    forecast = forecast_null_safe_distributions(
        game,
        decision,
        verified,
    )
    baseline, baseline_metadata = (
        select_consensus_disjoint_portfolio(game, decision)
    )
    if forecast["main_gate_active"]:
        tickets, _ = portfolio_from_distribution(
            game,
            forecast["main_distribution"],
            forecast["special_distribution"],
        )
    else:
        tickets = deepcopy(baseline)
    if game == SUPER:
        if forecast["special_gate_active"]:
            specials = sorted(
                forecast["special_distribution"],
                key=lambda number: (
                    -forecast["special_distribution"][number],
                    number,
                ),
            )[:5]
            masses = [
                math.fsum(
                    forecast["main_distribution"][number]
                    for number in ticket["numbers"]
                )
                for ticket in tickets
            ]
            bin_order = sorted(
                range(5),
                key=lambda index: (-masses[index], index),
            )
            for rank, index in enumerate(bin_order):
                tickets[index]["special"] = specials[rank]
        else:
            baseline_specials = {
                int(ticket["slot"]): int(ticket["special"])
                for ticket in baseline
            }
            for ticket in tickets:
                ticket["special"] = baseline_specials[
                    int(ticket["slot"])
                ]
    for index, ticket in enumerate(tickets, 1):
        ticket["slot"] = index
        ticket["source_agent"] = "null_safe_probability_synthesizer"
        ticket["source_proposal"] = f"null-safe-probability:{index}"
        ticket["numbers"] = sorted(
            int(number) for number in ticket["numbers"]
        )
        validate_pick(game, ticket["numbers"], ticket["special"])
    structure = portfolio_structure(game, tickets)
    selected_main = [
        number
        for ticket in tickets
        for number in ticket["numbers"]
    ]
    ticket_masses = [
        math.fsum(
            forecast["main_distribution"][number]
            for number in ticket["numbers"]
        )
        for ticket in tickets
    ]
    evidence = {
        "candidate_hash": verified["candidate_hash"],
        "protocol_hash": PROTOCOL_HASH,
        "game": game,
        "target": {
            "date": str(decision["target"]["date"]),
            "period": int(decision["target"]["period"]),
        },
        "source_decision_hash": decision["decision_hash"],
        "main_gate_active": forecast["main_gate_active"],
        "special_gate_active": (
            forecast["special_gate_active"]
            if game == SUPER
            else None
        ),
        "ticket_label_source": (
            "stacking_probability"
            if forecast["main_gate_active"]
            else "consensus_coverage"
        ),
        "baseline_support_evidence_hash": baseline_metadata[
            "support_evidence_hash"
        ],
        "selected_main_numbers": selected_main,
        "selected_specials": (
            [int(ticket["special"]) for ticket in tickets]
            if game == SUPER
            else None
        ),
        "ticket_main_probability_mass": ticket_masses,
        "structure": structure,
        "main_probability_mass": [
            forecast["main_distribution"][number]
            for number in range(1, POOL[game] + 1)
        ],
        "special_probability_mass": (
            [
                forecast["special_distribution"][number]
                for number in range(1, SPECIAL_POOL[SUPER] + 1)
            ]
            if game == SUPER
            else None
        ),
    }
    return tickets, {
        "schema_version": "1",
        "experiment_id": FORWARD_EXPERIMENT_ID,
        **evidence,
        "support_evidence_hash": canonical_hash(evidence),
        "use": "future_forward_shadow_only",
    }


def _mass_to_distribution(
    mass: object,
    *,
    domain_size: int,
    label: str,
) -> dict[int, float]:
    if not isinstance(mass, list) or len(mass) != domain_size:
        raise ValueError(f"{label}機率質量不完整")
    try:
        distribution = {
            number: float(mass[number - 1])
            for number in range(1, domain_size + 1)
        }
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}機率質量格式不符") from exc
    return _validate_distribution(
        distribution,
        domain_size=domain_size,
    )


def _distribution_mass(
    distribution: dict[int, float],
    *,
    domain_size: int,
) -> list[float]:
    verified = _validate_distribution(
        distribution,
        domain_size=domain_size,
    )
    return [
        verified[number] for number in range(1, domain_size + 1)
    ]


def build_null_safe_score_capsule(
    *,
    game: str,
    target: dict,
    candidate_hash: str,
    source_decision_hash: str,
    safe_main_distribution: dict[int, float],
    evidence_main_distribution: dict[int, float],
    main_e_process: dict,
    safe_special_distribution: dict[int, float] | None,
    evidence_special_distribution: dict[int, float] | None,
    special_e_process: dict | None,
) -> dict:
    """在 reveal 前封存安全預測、未開牌證據分布與 prior state。"""
    if game not in (SUPER, LOTTO649):
        raise ValueError("null-safe score capsule 遊戲不符")
    if not _is_sha256(candidate_hash) or not _is_sha256(
        source_decision_hash
    ):
        raise ValueError("null-safe score capsule 來源雜湊不符")
    main_state = validate_e_process_state(main_e_process)
    safe_main = _validate_distribution(
        safe_main_distribution,
        domain_size=POOL[game],
    )
    evidence_main = _validate_distribution(
        evidence_main_distribution,
        domain_size=POOL[game],
    )
    expected_safe_main, main_active = null_safe_distribution(
        evidence_main,
        main_state,
    )
    if safe_main != expected_safe_main:
        raise ValueError("null-safe 主號安全分布與 prior gate 不符")
    if game == SUPER:
        if (
            safe_special_distribution is None
            or evidence_special_distribution is None
            or special_e_process is None
        ):
            raise ValueError(
                "威力彩 null-safe score capsule 缺少第二區"
            )
        special_state = validate_e_process_state(
            special_e_process
        )
        safe_special = _validate_distribution(
            safe_special_distribution,
            domain_size=SPECIAL_POOL[SUPER],
        )
        evidence_special = _validate_distribution(
            evidence_special_distribution,
            domain_size=SPECIAL_POOL[SUPER],
        )
        expected_safe_special, special_active = (
            null_safe_distribution(
                evidence_special,
                special_state,
            )
        )
        if safe_special != expected_safe_special:
            raise ValueError(
                "null-safe 第二區安全分布與 prior gate 不符"
            )
    else:
        if any(
            value is not None
            for value in (
                safe_special_distribution,
                evidence_special_distribution,
                special_e_process,
            )
        ):
            raise ValueError(
                "大樂透 null-safe score capsule 不得有第二區"
            )
        safe_special = None
        evidence_special = None
        special_state = None
        special_active = False
    payload = {
        "schema_version": "1",
        "experiment_id": SCORE_CAPSULE_EXPERIMENT_ID,
        "game": game,
        "target": {
            "date": str(target["date"]),
            "period": int(target["period"]),
        },
        "candidate_hash": candidate_hash,
        "protocol_hash": PROTOCOL_HASH,
        "source_decision_hash": source_decision_hash,
        "activation_e_threshold": ACTIVATION_E_THRESHOLD,
        "main_gate_active": main_active,
        "special_gate_active": (
            special_active if game == SUPER else None
        ),
        "main_prior_e_process": main_state,
        "special_prior_e_process": special_state,
        "safe_main_probability_mass": _distribution_mass(
            safe_main,
            domain_size=POOL[game],
        ),
        "evidence_main_probability_mass": _distribution_mass(
            evidence_main,
            domain_size=POOL[game],
        ),
        "safe_special_probability_mass": (
            _distribution_mass(
                safe_special,
                domain_size=SPECIAL_POOL[SUPER],
            )
            if game == SUPER
            else None
        ),
        "evidence_special_probability_mass": (
            _distribution_mass(
                evidence_special,
                domain_size=SPECIAL_POOL[SUPER],
            )
            if game == SUPER
            else None
        ),
        "scoring_rules": SCORE_CAPSULE_RULES,
        "use": "future_forward_proper_score_only",
    }
    payload["capsule_hash"] = canonical_hash(payload)
    return payload


def validate_null_safe_score_capsule(
    capsule: dict,
    *,
    game: str,
    target: dict,
    candidate_hash: str,
    source_decision_hash: str,
) -> dict:
    expected_fields = {
        "schema_version",
        "experiment_id",
        "game",
        "target",
        "candidate_hash",
        "protocol_hash",
        "source_decision_hash",
        "activation_e_threshold",
        "main_gate_active",
        "special_gate_active",
        "main_prior_e_process",
        "special_prior_e_process",
        "safe_main_probability_mass",
        "evidence_main_probability_mass",
        "safe_special_probability_mass",
        "evidence_special_probability_mass",
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
        or capsule.get("activation_e_threshold")
        != ACTIVATION_E_THRESHOLD
        or capsule.get("scoring_rules") != SCORE_CAPSULE_RULES
        or capsule.get("use")
        != "future_forward_proper_score_only"
    ):
        raise ValueError("null-safe score capsule 契約不符")
    payload = {
        key: value
        for key, value in capsule.items()
        if key != "capsule_hash"
    }
    if capsule.get("capsule_hash") != canonical_hash(payload):
        raise ValueError("null-safe score capsule 雜湊不符")
    main_state = validate_e_process_state(
        capsule["main_prior_e_process"]
    )
    safe_main = _mass_to_distribution(
        capsule["safe_main_probability_mass"],
        domain_size=POOL[game],
        label="null-safe 主號安全",
    )
    evidence_main = _mass_to_distribution(
        capsule["evidence_main_probability_mass"],
        domain_size=POOL[game],
        label="null-safe 主號證據",
    )
    expected_safe_main, main_active = null_safe_distribution(
        evidence_main,
        main_state,
    )
    if (
        type(capsule.get("main_gate_active")) is not bool
        or capsule["main_gate_active"] is not main_active
        or safe_main != expected_safe_main
    ):
        raise ValueError("null-safe 主號 gate snapshot 不符")
    if game == SUPER:
        special_state = validate_e_process_state(
            capsule["special_prior_e_process"]
        )
        safe_special = _mass_to_distribution(
            capsule["safe_special_probability_mass"],
            domain_size=SPECIAL_POOL[SUPER],
            label="null-safe 第二區安全",
        )
        evidence_special = _mass_to_distribution(
            capsule["evidence_special_probability_mass"],
            domain_size=SPECIAL_POOL[SUPER],
            label="null-safe 第二區證據",
        )
        expected_safe_special, special_active = (
            null_safe_distribution(
                evidence_special,
                special_state,
            )
        )
        if (
            type(capsule.get("special_gate_active")) is not bool
            or capsule["special_gate_active"] is not special_active
            or safe_special != expected_safe_special
        ):
            raise ValueError("null-safe 第二區 gate snapshot 不符")
    elif any(
        capsule.get(field) is not None
        for field in (
            "special_gate_active",
            "special_prior_e_process",
            "safe_special_probability_mass",
            "evidence_special_probability_mass",
        )
    ):
        raise ValueError(
            "大樂透 null-safe score capsule 第二區欄位不符"
        )
    return deepcopy(capsule)


def _score_verdict(regret: float) -> str:
    if math.isclose(regret, 0.0, rel_tol=0.0, abs_tol=1e-12):
        return "tie_uniform"
    return "better_than_uniform" if regret < 0 else "worse_than_uniform"


def settle_null_safe_score_capsule(
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
    """以凍結分布結算，並只讓 reveal 更新下一期 e-process state。"""
    verified = validate_null_safe_score_capsule(
        capsule,
        game=game,
        target=target,
        candidate_hash=candidate_hash,
        source_decision_hash=source_decision_hash,
    )
    if (
        not isinstance(actual_main, list)
        or len(actual_main) != PICK_N
        or len(set(actual_main)) != PICK_N
        or any(
            type(number) is not int
            or number < 1
            or number > POOL[game]
            for number in actual_main
        )
    ):
        raise ValueError("null-safe score 實際主號不合法")
    safe_main = _mass_to_distribution(
        verified["safe_main_probability_mass"],
        domain_size=POOL[game],
        label="null-safe 主號安全",
    )
    evidence_main = _mass_to_distribution(
        verified["evidence_main_probability_mass"],
        domain_size=POOL[game],
        label="null-safe 主號證據",
    )
    main_safe_loss = -weighted_subset_log_probability(
        safe_main,
        actual_main,
    )
    uniform_main_loss = math.log(math.comb(POOL[game], PICK_N))
    main_safe_regret = main_safe_loss - uniform_main_loss
    main_log_lr = subset_log_likelihood_ratio_vs_uniform(
        evidence_main,
        actual_main,
    )
    main_updated = restart_e_process_step(
        verified["main_prior_e_process"],
        main_log_lr,
    )
    if game == SUPER:
        if (
            type(actual_special) is not int
            or actual_special < 1
            or actual_special > SPECIAL_POOL[SUPER]
        ):
            raise ValueError("null-safe score 實際第二區不合法")
        safe_special = _mass_to_distribution(
            verified["safe_special_probability_mass"],
            domain_size=SPECIAL_POOL[SUPER],
            label="null-safe 第二區安全",
        )
        evidence_special = _mass_to_distribution(
            verified["evidence_special_probability_mass"],
            domain_size=SPECIAL_POOL[SUPER],
            label="null-safe 第二區證據",
        )
        special_safe_loss = -math.log(safe_special[actual_special])
        uniform_special_loss = math.log(SPECIAL_POOL[SUPER])
        special_safe_regret = (
            special_safe_loss - uniform_special_loss
        )
        special_log_lr = math.log(
            evidence_special[actual_special]
            * SPECIAL_POOL[SUPER]
        )
        special_updated = restart_e_process_step(
            verified["special_prior_e_process"],
            special_log_lr,
        )
    else:
        if actual_special is not None:
            raise ValueError(
                "大樂透 null-safe score 不得有第二區"
            )
        special_safe_loss = None
        uniform_special_loss = None
        special_safe_regret = None
        special_log_lr = None
        special_updated = None
    result = {
        "schema_version": "1",
        "experiment_id": SCORE_CAPSULE_EXPERIMENT_ID,
        "capsule_hash": verified["capsule_hash"],
        "protocol_hash": PROTOCOL_HASH,
        "candidate_hash": candidate_hash,
        "eligible": bool(eligible),
        "main_gate_active_for_scored_target": verified[
            "main_gate_active"
        ],
        "main_safe_log_loss": main_safe_loss,
        "uniform_main_log_loss": uniform_main_loss,
        "main_safe_regret_vs_uniform": main_safe_regret,
        "main_safe_verdict": _score_verdict(main_safe_regret),
        "main_evidence_log_likelihood_ratio_vs_uniform": main_log_lr,
        "main_prior_e_process": verified["main_prior_e_process"],
        "main_updated_e_process": main_updated,
        "main_next_gate_active": gate_is_active(main_updated),
        "special_gate_active_for_scored_target": (
            verified["special_gate_active"]
            if game == SUPER
            else None
        ),
        "special_safe_log_loss": special_safe_loss,
        "uniform_special_log_loss": uniform_special_loss,
        "special_safe_regret_vs_uniform": special_safe_regret,
        "special_safe_verdict": (
            _score_verdict(special_safe_regret)
            if game == SUPER
            else "not_applicable"
        ),
        "special_evidence_log_likelihood_ratio_vs_uniform": (
            special_log_lr
        ),
        "special_prior_e_process": (
            verified["special_prior_e_process"]
            if game == SUPER
            else None
        ),
        "special_updated_e_process": special_updated,
        "special_next_gate_active": (
            gate_is_active(special_updated)
            if game == SUPER
            else None
        ),
        "interpretation": SCORE_RESULT_INTERPRETATION,
    }
    verify_null_safe_score_result(result, game=game)
    return result


def verify_null_safe_score_result(
    result: dict,
    *,
    game: str,
) -> None:
    expected_fields = {
        "schema_version",
        "experiment_id",
        "capsule_hash",
        "protocol_hash",
        "candidate_hash",
        "eligible",
        "main_gate_active_for_scored_target",
        "main_safe_log_loss",
        "uniform_main_log_loss",
        "main_safe_regret_vs_uniform",
        "main_safe_verdict",
        "main_evidence_log_likelihood_ratio_vs_uniform",
        "main_prior_e_process",
        "main_updated_e_process",
        "main_next_gate_active",
        "special_gate_active_for_scored_target",
        "special_safe_log_loss",
        "uniform_special_log_loss",
        "special_safe_regret_vs_uniform",
        "special_safe_verdict",
        "special_evidence_log_likelihood_ratio_vs_uniform",
        "special_prior_e_process",
        "special_updated_e_process",
        "special_next_gate_active",
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
        or type(result.get("main_gate_active_for_scored_target"))
        is not bool
        or type(result.get("main_next_gate_active")) is not bool
        or result.get("interpretation")
        != SCORE_RESULT_INTERPRETATION
    ):
        raise ValueError("null-safe score result 契約不符")
    try:
        main_loss = float(result["main_safe_log_loss"])
        uniform_main_loss = float(result["uniform_main_log_loss"])
        main_regret = float(result["main_safe_regret_vs_uniform"])
        main_log_lr = float(
            result[
                "main_evidence_log_likelihood_ratio_vs_uniform"
            ]
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("null-safe 主號 score 格式不符") from exc
    main_prior = validate_e_process_state(
        result["main_prior_e_process"]
    )
    expected_main_updated = restart_e_process_step(
        main_prior,
        main_log_lr,
    )
    if (
        any(
            not math.isfinite(value)
            for value in (
                main_loss,
                uniform_main_loss,
                main_regret,
                main_log_lr,
            )
        )
        or main_loss <= 0
        or not math.isclose(
            uniform_main_loss,
            math.log(math.comb(POOL[game], PICK_N)),
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        or not math.isclose(
            main_regret,
            main_loss - uniform_main_loss,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        or result["main_safe_verdict"]
        != _score_verdict(main_regret)
        or result["main_updated_e_process"]
        != expected_main_updated
        or result["main_next_gate_active"]
        is not gate_is_active(expected_main_updated)
    ):
        raise ValueError("null-safe 主號 score 語意不符")
    if game == SUPER:
        if (
            type(
                result["special_gate_active_for_scored_target"]
            )
            is not bool
            or type(result["special_next_gate_active"]) is not bool
        ):
            raise ValueError("null-safe 第二區 gate 格式不符")
        try:
            special_loss = float(result["special_safe_log_loss"])
            uniform_special_loss = float(
                result["uniform_special_log_loss"]
            )
            special_regret = float(
                result["special_safe_regret_vs_uniform"]
            )
            special_log_lr = float(
                result[
                    "special_evidence_log_likelihood_ratio_vs_uniform"
                ]
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "null-safe 第二區 score 格式不符"
            ) from exc
        special_prior = validate_e_process_state(
            result["special_prior_e_process"]
        )
        expected_special_updated = restart_e_process_step(
            special_prior,
            special_log_lr,
        )
        if (
            any(
                not math.isfinite(value)
                for value in (
                    special_loss,
                    uniform_special_loss,
                    special_regret,
                    special_log_lr,
                )
            )
            or special_loss <= 0
            or not math.isclose(
                uniform_special_loss,
                math.log(SPECIAL_POOL[SUPER]),
                rel_tol=0.0,
                abs_tol=1e-12,
            )
            or not math.isclose(
                special_regret,
                special_loss - uniform_special_loss,
                rel_tol=0.0,
                abs_tol=1e-12,
            )
            or result["special_safe_verdict"]
            != _score_verdict(special_regret)
            or result["special_updated_e_process"]
            != expected_special_updated
            or result["special_next_gate_active"]
            is not gate_is_active(expected_special_updated)
        ):
            raise ValueError("null-safe 第二區 score 語意不符")
    elif any(
        result[field] is not None
        for field in (
            "special_gate_active_for_scored_target",
            "special_safe_log_loss",
            "uniform_special_log_loss",
            "special_safe_regret_vs_uniform",
            "special_evidence_log_likelihood_ratio_vs_uniform",
            "special_prior_e_process",
            "special_updated_e_process",
            "special_next_gate_active",
        )
    ) or result.get("special_safe_verdict") != "not_applicable":
        raise ValueError("大樂透 null-safe 第二區 score 不符")


def advance_forward_candidate(
    prior_candidate: dict,
    stacking_candidate: dict,
    score_settlements: list[dict],
) -> tuple[dict, list[dict]]:
    """只用已預註冊 v7 score 推進 gate，並讀取最新 stacking 權重。"""
    prior = validate_forward_candidate(prior_candidate)
    stacking = validate_stacking_forward_candidate(
        stacking_candidate
    )
    if not isinstance(score_settlements, list):
        raise ValueError("null-safe forward settlements 格式不符")
    for game in (SUPER, LOTTO649):
        if (
            stacking["fitted_through"][game]
            < prior["fitted_through"][game]
        ):
            raise ValueError(
                "null-safe stacking fitted-through 不得倒退"
            )
    models = deepcopy(prior["models"])
    applied = []
    previous_target = {
        game: (
            prior["fitted_through"][game],
            -1,
        )
        for game in (SUPER, LOTTO649)
    }
    normalized_rows = []
    for row in score_settlements:
        if (
            not isinstance(row, dict)
            or set(row)
            != {
                "game",
                "target",
                "registration_hash",
                "proper_score",
            }
            or row.get("game") not in (SUPER, LOTTO649)
            or not _is_sha256(row.get("registration_hash"))
        ):
            raise ValueError(
                "null-safe forward settlement 來源欄位不符"
            )
        game = row["game"]
        target = {
            "date": str(row["target"]["date"]),
            "period": int(row["target"]["period"]),
        }
        score = deepcopy(row["proper_score"])
        verify_null_safe_score_result(score, game=game)
        normalized_rows.append(
            {
                "game": game,
                "target": target,
                "registration_hash": row["registration_hash"],
                "proper_score": score,
            }
        )
    normalized_rows.sort(
        key=lambda row: (
            row["target"]["date"],
            row["target"]["period"],
            row["game"],
        )
    )
    seen = set()
    for row in normalized_rows:
        game = row["game"]
        target = row["target"]
        target_key = (target["date"], target["period"])
        unique_key = (game, *target_key)
        if unique_key in seen:
            raise ValueError(
                "null-safe forward settlement 目標重複"
            )
        seen.add(unique_key)
        if target["date"] > stacking["fitted_through"][game]:
            raise ValueError(
                "null-safe settlement 晚於 stacking fitted-through"
            )
        if target["date"] <= prior["fitted_through"][game]:
            continue
        if target_key <= previous_target[game]:
            raise ValueError(
                "null-safe forward settlement 期別未嚴格遞增"
            )
        score = row["proper_score"]
        if (
            score["main_prior_e_process"]
            != models[game]["main_e_process"]
        ):
            raise ValueError(
                "null-safe 主號 settlement prior state 不連續"
            )
        models[game]["main_e_process"] = deepcopy(
            score["main_updated_e_process"]
        )
        models[game]["main_gate_active"] = bool(
            score["main_next_gate_active"]
        )
        if game == SUPER:
            if (
                score["special_prior_e_process"]
                != models[game]["special_e_process"]
            ):
                raise ValueError(
                    "null-safe 第二區 settlement prior state 不連續"
                )
            models[game]["special_e_process"] = deepcopy(
                score["special_updated_e_process"]
            )
            models[game]["special_gate_active"] = bool(
                score["special_next_gate_active"]
            )
        previous_target[game] = target_key
        applied.append(
            {
                "game": game,
                "target": target,
                "registration_hash": row["registration_hash"],
                "capsule_hash": score["capsule_hash"],
                "main_updated_e_process": deepcopy(
                    score["main_updated_e_process"]
                ),
                "special_updated_e_process": deepcopy(
                    score["special_updated_e_process"]
                ),
            }
        )
    for game in (SUPER, LOTTO649):
        models[game]["main_log_weights"] = deepcopy(
            stacking["models"][game]["main_log_weights"]
        )
        models[game]["main_weights"] = deepcopy(
            stacking["models"][game]["main_weights"]
        )
        if game == SUPER:
            models[game]["special_log_weights"] = deepcopy(
                stacking["models"][game]["special_log_weights"]
            )
            models[game]["special_weights"] = deepcopy(
                stacking["models"][game]["special_weights"]
            )
    payload = {
        **{
            key: deepcopy(value)
            for key, value in prior.items()
            if key != "candidate_hash"
        },
        "fitted_through": deepcopy(stacking["fitted_through"]),
        "source_ledger_hashes": deepcopy(
            stacking["source_ledger_hashes"]
        ),
        "models": models,
    }
    candidate = {
        **payload,
        "candidate_hash": canonical_hash(payload),
    }
    return validate_forward_candidate(candidate), applied


def build_forward_state_artifact(
    prior_candidate: dict,
    stacking_candidate: dict,
    score_settlements: list[dict],
) -> dict:
    candidate, applied = advance_forward_candidate(
        prior_candidate,
        stacking_candidate,
        score_settlements,
    )
    stacking = validate_stacking_forward_candidate(
        stacking_candidate
    )
    settlement_refs = []
    for row in score_settlements:
        game = row["game"]
        score = row["proper_score"]
        verify_null_safe_score_result(score, game=game)
        settlement_refs.append(
            {
                "game": game,
                "target": {
                    "date": str(row["target"]["date"]),
                    "period": int(row["target"]["period"]),
                },
                "registration_hash": row["registration_hash"],
                "capsule_hash": score["capsule_hash"],
            }
        )
    settlement_refs.sort(
        key=lambda row: (
            row["target"]["date"],
            row["target"]["period"],
            row["game"],
        )
    )
    payload = {
        "schema_version": "1",
        "experiment_id": FORWARD_STATE_EXPERIMENT_ID,
        "generated_at": max(candidate["fitted_through"].values())
        + "T23:59:59+08:00",
        "prior_candidate_hash": prior_candidate["candidate_hash"],
        "stacking_candidate_hash": stacking["candidate_hash"],
        "applied_transitions": applied,
        "registered_score_capsules": settlement_refs,
        "future_forward_shadow_candidate": candidate,
        "historical_backfill_allowed": False,
        "honesty_note": (
            "stacking 權重可讀取最新 reveal；e-process 每次從凍結"
            "正式基線加上帳本全部已登記 v7 score capsule 決定性"
            "重建，v6 空窗不得推進 gate。"
        ),
    }
    payload["state_hash"] = canonical_hash(payload)
    return payload


def validate_forward_state_artifact(artifact: dict) -> dict:
    expected_fields = {
        "schema_version",
        "experiment_id",
        "generated_at",
        "prior_candidate_hash",
        "stacking_candidate_hash",
        "applied_transitions",
        "registered_score_capsules",
        "future_forward_shadow_candidate",
        "historical_backfill_allowed",
        "honesty_note",
        "state_hash",
    }
    if (
        not isinstance(artifact, dict)
        or set(artifact) != expected_fields
        or artifact.get("schema_version") != "1"
        or artifact.get("experiment_id")
        != FORWARD_STATE_EXPERIMENT_ID
        or not _is_sha256(artifact.get("prior_candidate_hash"))
        or not _is_sha256(
            artifact.get("stacking_candidate_hash")
        )
        or artifact.get("historical_backfill_allowed") is not False
        or not isinstance(artifact.get("honesty_note"), str)
        or not isinstance(
            artifact.get("applied_transitions"), list
        )
        or not isinstance(
            artifact.get("registered_score_capsules"), list
        )
    ):
        raise ValueError("null-safe forward state artifact 契約不符")
    payload = {
        key: value
        for key, value in artifact.items()
        if key != "state_hash"
    }
    if artifact.get("state_hash") != canonical_hash(payload):
        raise ValueError("null-safe forward state artifact hash 不符")
    validate_forward_candidate(
        artifact["future_forward_shadow_candidate"]
    )
    for row in artifact["applied_transitions"]:
        if (
            not isinstance(row, dict)
            or set(row)
            != {
                "game",
                "target",
                "registration_hash",
                "capsule_hash",
                "main_updated_e_process",
                "special_updated_e_process",
            }
            or row.get("game") not in (SUPER, LOTTO649)
            or not _is_sha256(row.get("registration_hash"))
            or not _is_sha256(row.get("capsule_hash"))
        ):
            raise ValueError(
                "null-safe forward state transition 不符"
            )
        validate_e_process_state(row["main_updated_e_process"])
        if row["game"] == SUPER:
            validate_e_process_state(
                row["special_updated_e_process"]
            )
        elif row["special_updated_e_process"] is not None:
            raise ValueError(
                "大樂透 forward transition 不得有第二區"
            )
    for row in artifact["registered_score_capsules"]:
        if (
            not isinstance(row, dict)
            or set(row)
            != {
                "game",
                "target",
                "registration_hash",
                "capsule_hash",
            }
            or row.get("game") not in (SUPER, LOTTO649)
            or not _is_sha256(row.get("registration_hash"))
            or not _is_sha256(row.get("capsule_hash"))
        ):
            raise ValueError(
                "null-safe registered score reference 不符"
            )
    return deepcopy(artifact)


def write_forward_state(
    artifact: dict,
    output_dir: Path,
) -> Path:
    verified = validate_forward_state_artifact(artifact)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "null_safe_probability_forward.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(verified, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return path


def run_null_safe_probability(
    ledger_paths: dict[str, Path],
    *,
    base: Path,
    verify_ledgers: bool = True,
) -> dict:
    if set(ledger_paths) != {SUPER, LOTTO649}:
        raise ValueError("null-safe 研究需要兩款遊戲 ledger")
    base = Path(base)
    records_before = tree_sha256(base / "records")
    verification = {}
    source_first_dates = {}
    source_last_dates = {}
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
        main_state = initial_e_process_state()
        special_logs = (
            {expert: 0.0 for expert in EXPERT_IDS}
            if game == SUPER
            else None
        )
        special_state = (
            initial_e_process_state()
            if game == SUPER
            else None
        )
        main_mixture_losses = []
        main_safe_losses = []
        main_log_lrs = []
        main_prior_log_e = []
        special_mixture_losses = []
        special_safe_losses = []
        special_log_lrs = []
        special_prior_log_e = []
        previous_key = None
        seen_periods = set()
        sequence = 0

        with path.open(encoding="utf-8") as handle:
            for sequence, line in enumerate(handle, 1):
                event = json.loads(line)
                reveal = event["reveal"]
                key = (str(reveal["date"]), int(reveal["period"]))
                if previous_key is not None and key <= previous_key:
                    raise ValueError("null-safe 期別未嚴格遞增")
                if key[1] in seen_periods:
                    raise ValueError("null-safe 期別重複")
                previous_key = key
                seen_periods.add(key[1])
                source_first_dates.setdefault(game, key[0])
                source_last_dates[game] = key[0]
                decision = event["decision"]
                actual_main = [
                    int(number) for number in reveal["numbers"]
                ]

                main_experts = expert_distributions(
                    game,
                    decision,
                    dimension="main",
                )
                main_mixture = mixture_distribution(
                    main_experts,
                    main_logs,
                )
                main_safe, _ = null_safe_distribution(
                    main_mixture,
                    main_state,
                )
                main_prior_log_e.append(
                    float(main_state["log_e_value"])
                )
                main_mixture_losses.append(
                    -weighted_subset_log_probability(
                        main_mixture,
                        actual_main,
                    )
                )
                main_safe_losses.append(
                    -weighted_subset_log_probability(
                        main_safe,
                        actual_main,
                    )
                )
                main_log_lr = subset_log_likelihood_ratio_vs_uniform(
                    main_mixture,
                    actual_main,
                )
                main_log_lrs.append(main_log_lr)
                main_state = restart_e_process_step(
                    main_state,
                    main_log_lr,
                )
                main_logs, _ = update_log_weights(
                    main_logs,
                    main_experts,
                    actual_main,
                    sequence=sequence,
                )

                if game == SUPER:
                    special_experts = expert_distributions(
                        game,
                        decision,
                        dimension="special",
                    )
                    special_mixture = mixture_distribution(
                        special_experts,
                        special_logs,
                    )
                    special_safe, _ = null_safe_distribution(
                        special_mixture,
                        special_state,
                    )
                    actual_special = int(reveal["special"])
                    special_prior_log_e.append(
                        float(special_state["log_e_value"])
                    )
                    special_mixture_losses.append(
                        -math.log(
                            special_mixture[actual_special]
                        )
                    )
                    special_safe_losses.append(
                        -math.log(special_safe[actual_special])
                    )
                    special_log_lr = math.log(
                        special_mixture[actual_special]
                        * SPECIAL_POOL[SUPER]
                    )
                    special_log_lrs.append(special_log_lr)
                    special_state = restart_e_process_step(
                        special_state,
                        special_log_lr,
                    )
                    special_logs, _ = update_log_weights(
                        special_logs,
                        special_experts,
                        [actual_special],
                        sequence=sequence,
                    )

        if sequence == 0:
            raise ValueError("null-safe ledger 不得為空")
        if verification[game]["lines"] != sequence:
            raise AssertionError("null-safe 實際讀取期數不符")
        main_summary = _stream_summary(
            mixture_losses=main_mixture_losses,
            safe_losses=main_safe_losses,
            uniform_loss=math.log(
                math.comb(POOL[game], PICK_N)
            ),
            log_likelihood_ratios=main_log_lrs,
            prior_log_e_values=main_prior_log_e,
            final_state=main_state,
        )
        summary = {
            "game": game,
            "game_name": GAME_NAMES[game],
            "draws": sequence,
            "first_date": source_first_dates[game],
            "last_date": source_last_dates[game],
            "main": main_summary,
        }
        model = {
            "main_log_weights": main_logs,
            "main_weights": _softmax(main_logs),
            "main_e_process": main_state,
            "main_gate_active": gate_is_active(main_state),
        }
        if game == SUPER:
            special_summary = _stream_summary(
                mixture_losses=special_mixture_losses,
                safe_losses=special_safe_losses,
                uniform_loss=math.log(SPECIAL_POOL[SUPER]),
                log_likelihood_ratios=special_log_lrs,
                prior_log_e_values=special_prior_log_e,
                final_state=special_state,
            )
            summary["special"] = special_summary
            model.update(
                {
                    "special_log_weights": special_logs,
                    "special_weights": _softmax(special_logs),
                    "special_e_process": special_state,
                    "special_gate_active": gate_is_active(
                        special_state
                    ),
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
            "在沒有足夠非均勻 likelihood 證據時回退精確均勻分布，"
            "能否消除 stacking 的無證據 proper-score 損失？"
        ),
        "methodology": {
            **PROTOCOL_CONFIG,
            "protocol_hash": PROTOCOL_HASH,
            "unit": "每款遊戲每期一個開獎前可預測分布",
            "lookahead_control": (
                "第 t 期 gate 只讀截至 t-1 reveal 的 e-value；"
                "第 t 期 reveal 只更新 t+1 gate。"
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
            "likelihood": (
                "normalized_unordered_subset_and_categorical"
            ),
            "e_process_complexity": "O(draws)",
        },
        "prequential_summary": summaries,
        "final_models": final_models,
        "conclusion": {
            "status": "candidate_ready_future_shadow",
            "historical_promotion_eligible": False,
            "current_gate_active": {
                SUPER: {
                    "main": final_models[SUPER][
                        "main_gate_active"
                    ],
                    "special": final_models[SUPER][
                        "special_gate_active"
                    ],
                },
                LOTTO649: {
                    "main": final_models[LOTTO649][
                        "main_gate_active"
                    ],
                    "special": None,
                },
            },
            "reason": (
                "所有歷史 evidence stream 都遠低於固定啟用門檻；"
                "無證據時精確均勻 forecast 消除現行微小正 regret。"
            ),
            "next_evidence": (
                "只接受新 experiment ID 下不可回填的前向 proper score。"
            ),
        },
        "records_integrity": {
            "before_sha256": records_before,
            "after_sha256": records_after,
            "unchanged": records_before == records_after,
        },
        "limitations": [
            "公平零模型下合法號碼標籤與合法六號子集理論等機率。",
            "歷史只初始化 gate，不是新的確認性 holdout。",
            "regret 降為 0 代表回到公平基準，不代表提高中獎率。",
            "只有未來證據跨過固定門檻後才允許非均勻 forecast。",
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
        raise RuntimeError("null-safe 研究不應改動正式 records")
    return result


def write_results(result: dict, output_dir: Path) -> Path:
    validate_forward_candidate(
        result["future_forward_shadow_candidate"]
    )
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "null_safe_probability.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return path
