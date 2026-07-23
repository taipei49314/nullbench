"""Unknown-generator council with exact subset likelihood and regime recovery.

The module deliberately separates two questions:

1. Belief: how much probability evidence supports each generator hypothesis?
2. Action: which five-ticket portfolio preserves the strongest structural
   coverage while the label signal is still uncertain?

Historical replay is strictly prequential.  Draw t is scored using weights and
distributions frozen before draw t, then it may update the prior for draw t+1.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import statistics
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
)
from research.agent_ablation import (
    _validate_event,
    block_bootstrap_ci,
    portfolio_metrics,
)
from research.gates import tree_sha256
from research.max_coverage import (
    _support_rows,
    select_consensus_disjoint_portfolio,
)
from research.null_safe_probability import (
    weighted_subset_log_probability,
)
from research.probability_stacking import (
    DEBATE_EXPERT,
    UNIFORM_EXPERT,
    _proposal_contract,
    expert_distributions as proposal_expert_distributions,
    portfolio_from_distribution,
)
from research.structural_optimum import structural_proof_reference


EXPERIMENT_ID = "switching-bayes-unknown-generator-shadow-v2"
FORWARD_EXPERIMENT_ID = (
    "switching-bayes-unknown-generator-forward-shadow-v2"
)
SCORE_CAPSULE_EXPERIMENT_ID = (
    "switching-bayes-exact-outcome-score-capsule-v2"
)
INDEPENDENT_NULL = "independent_null"
HYPOTHESIS_EXPERTS = tuple(
    expert for expert in AGENT_IDS if expert != INDEPENDENT_NULL
)
EXPERT_IDS = HYPOTHESIS_EXPERTS + (
    DEBATE_EXPERT,
    UNIFORM_EXPERT,
)
FIXED_SHARE = 1.0 / 208.0
WARMUP_DRAWS = 60
DEVELOPMENT_FRACTION = 0.70
BOOTSTRAP_BLOCK_DRAWS = 13
BOOTSTRAP_SAMPLES = 2_000
RECENT_DRAWS = 208

PROTOCOL_CONFIG = {
    "experts": list(EXPERT_IDS),
    "h0_representation": UNIFORM_EXPERT,
    "hypothesis_input": (
        "complete_pre_reveal_probability_snapshots_for_h1_to_h4"
    ),
    "debate_input": "all_15_proposals_and_60_cross_agent_critiques",
    "main_outcome_model": (
        "product_weighted_unordered_six_number_subset"
    ),
    "special_outcome_model": "categorical_probability_mass",
    "update": "bayesian_posterior_then_fixed_share",
    "fixed_share": FIXED_SHARE,
    "minimum_next_prior_weight": FIXED_SHARE / len(EXPERT_IDS),
    "belief_action_separation": True,
    "belief_portfolio": (
        "top_30_from_prior_weighted_label_mass_then_five_disjoint_tickets"
    ),
    "production_action_while_unproven": (
        "consensus_ranked_30_unique_main_numbers_in_five_disjoint_tickets"
    ),
    "historical_use": "prequential_description_only",
    "promotion_evidence": "future_preregistered_pairs_only",
}
PROTOCOL_HASH = canonical_hash(PROTOCOL_CONFIG)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _uniform(domain_size: int) -> dict[int, float]:
    if type(domain_size) is not int or domain_size < 1:
        raise ValueError("均勻分布的定義域不合法")
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
    result = {
        number: float(distribution[number])
        for number in range(1, domain_size + 1)
    }
    if (
        any(
            not math.isfinite(value) or value <= 0
            for value in result.values()
        )
        or not math.isclose(
            math.fsum(result.values()),
            1.0,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
    ):
        raise ValueError("機率分布必須為有限正值且總和為 1")
    return result


def validate_weights(weights: dict[str, float]) -> dict[str, float]:
    if not isinstance(weights, dict) or set(weights) != set(EXPERT_IDS):
        raise ValueError("switching Bayes 專家權重欄位不完整")
    result = {
        expert: float(weights[expert])
        for expert in EXPERT_IDS
    }
    if (
        any(
            not math.isfinite(value) or value < 0
            for value in result.values()
        )
        or not math.isclose(
            math.fsum(result.values()),
            1.0,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        or not any(value > 0 for value in result.values())
    ):
        raise ValueError("switching Bayes 權重必須為非負有限值且總和為 1")
    return result


def initial_weights() -> dict[str, float]:
    return {
        expert: 1.0 / len(EXPERT_IDS)
        for expert in EXPERT_IDS
    }


def _snapshot_distribution(
    snapshot: dict,
    *,
    key: str,
    domain_size: int,
    expected_total: float,
) -> dict[int, float]:
    raw = snapshot.get(key)
    if not isinstance(raw, list) or len(raw) != domain_size:
        raise ValueError(f"{snapshot.get('id')} 的 {key} 長度不符")
    values = [float(value) for value in raw]
    if any(
        not math.isfinite(value)
        or value <= 0
        or (key == "main_probabilities" and value > 1)
        for value in values
    ):
        raise ValueError(f"{snapshot.get('id')} 的 {key} 含非法值")
    total = math.fsum(values)
    if not math.isclose(
        total,
        expected_total,
        rel_tol=0.0,
        abs_tol=1e-6,
    ):
        raise ValueError(f"{snapshot.get('id')} 的 {key} 總和不符")
    distribution = {
        number: value / total
        for number, value in enumerate(values, 1)
    }
    return _validate_distribution(
        distribution,
        domain_size=domain_size,
    )


def snapshot_expert_distributions(
    game: str,
    decision: dict,
    *,
    dimension: str = "main",
) -> dict[str, dict[int, float]]:
    """Build six unique experts from the complete frozen decision."""
    _proposal_contract(game, decision)
    snapshots = list(decision.get("hypotheses", ()))
    by_id = {
        str(snapshot.get("id")): snapshot
        for snapshot in snapshots
    }
    if (
        len(snapshots) != len(AGENT_IDS)
        or set(by_id) != set(AGENT_IDS)
    ):
        raise ValueError("完整假設機率快照缺漏或重複")

    if dimension == "main":
        domain_size = POOL[game]
        key = "main_probabilities"
        expected_total = float(PICK_N)
    elif dimension == "special" and game == SUPER:
        domain_size = SPECIAL_POOL[SUPER]
        key = "special_probabilities"
        expected_total = 1.0
    else:
        raise ValueError("switching Bayes dimension 不支援")

    output = {
        expert: _snapshot_distribution(
            by_id[expert],
            key=key,
            domain_size=domain_size,
            expected_total=expected_total,
        )
        for expert in HYPOTHESIS_EXPERTS
    }
    proposal_experts = proposal_expert_distributions(
        game,
        decision,
        dimension=dimension,
    )
    output[DEBATE_EXPERT] = proposal_experts[DEBATE_EXPERT]
    output[UNIFORM_EXPERT] = _uniform(domain_size)
    if set(output) != set(EXPERT_IDS):
        raise AssertionError("switching Bayes 專家集合遺漏")
    for distribution in output.values():
        _validate_distribution(
            distribution,
            domain_size=domain_size,
        )
    return output


def mixture_label_distribution(
    distributions: dict[str, dict[int, float]],
    weights: dict[str, float],
) -> dict[int, float]:
    if not isinstance(distributions, dict) or set(distributions) != set(
        EXPERT_IDS
    ):
        raise ValueError("switching Bayes mixture 專家分布不完整")
    verified_weights = validate_weights(weights)
    domain_size = len(distributions[EXPERT_IDS[0]])
    verified = {
        expert: _validate_distribution(
            distributions[expert],
            domain_size=domain_size,
        )
        for expert in EXPERT_IDS
    }
    mixed = {
        number: math.fsum(
            verified_weights[expert] * verified[expert][number]
            for expert in EXPERT_IDS
        )
        for number in range(1, domain_size + 1)
    }
    return _validate_distribution(mixed, domain_size=domain_size)


def _logsumexp(values: list[float]) -> float:
    if not values or any(not math.isfinite(value) for value in values):
        raise ValueError("logsumexp 需要至少一個有限值")
    maximum = max(values)
    return maximum + math.log(
        math.fsum(math.exp(value - maximum) for value in values)
    )


def mixture_outcome_log_probability(
    expert_log_probabilities: dict[str, float],
    weights: dict[str, float],
) -> float:
    if (
        not isinstance(expert_log_probabilities, dict)
        or set(expert_log_probabilities) != set(EXPERT_IDS)
        or any(
            not math.isfinite(float(value))
            for value in expert_log_probabilities.values()
        )
    ):
        raise ValueError("完整結果的專家 log probability 不完整")
    verified_weights = validate_weights(weights)
    return _logsumexp(
        [
            math.log(verified_weights[expert])
            + float(expert_log_probabilities[expert])
            for expert in EXPERT_IDS
            if verified_weights[expert] > 0
        ]
    )


def main_outcome_log_probabilities(
    distributions: dict[str, dict[int, float]],
    actual: list[int],
) -> dict[str, float]:
    if set(distributions) != set(EXPERT_IDS):
        raise ValueError("主號結果評分缺少專家")
    return {
        expert: weighted_subset_log_probability(
            distributions[expert],
            actual,
        )
        for expert in EXPERT_IDS
    }


def special_outcome_log_probabilities(
    distributions: dict[str, dict[int, float]],
    actual: int,
) -> dict[str, float]:
    if (
        set(distributions) != set(EXPERT_IDS)
        or type(actual) is not int
        or actual < 1
        or actual > SPECIAL_POOL[SUPER]
    ):
        raise ValueError("第二區結果評分輸入不合法")
    return {
        expert: math.log(distributions[expert][actual])
        for expert in EXPERT_IDS
    }


def fixed_share_update(
    weights: dict[str, float],
    expert_log_probabilities: dict[str, float],
    *,
    share: float = FIXED_SHARE,
) -> tuple[dict[str, float], dict[str, float]]:
    """Return next-draw prior and the current-draw Bayesian posterior."""
    if not math.isfinite(float(share)) or not 0 <= share < 1:
        raise ValueError("fixed share 必須介於 0（含）與 1 之間")
    verified_weights = validate_weights(weights)
    mixture_log_probability = mixture_outcome_log_probability(
        expert_log_probabilities,
        verified_weights,
    )
    posterior = {
        expert: (
            math.exp(
                math.log(verified_weights[expert])
                + float(expert_log_probabilities[expert])
                - mixture_log_probability
            )
            if verified_weights[expert] > 0
            else 0.0
        )
        for expert in EXPERT_IDS
    }
    posterior = validate_weights(posterior)
    next_prior = {
        expert: (
            (1.0 - share) * posterior[expert]
            + share / len(EXPERT_IDS)
        )
        for expert in EXPERT_IDS
    }
    next_prior = validate_weights(next_prior)
    floor = share / len(EXPERT_IDS)
    if share and any(
        value < floor - 1e-15
        for value in next_prior.values()
    ):
        raise AssertionError("fixed share 未保住專家最低存活權重")
    return next_prior, posterior


def static_expert_regret_bound(draws: int) -> float:
    """Exact HMM prior bound against the best single expert in hindsight."""
    if type(draws) is not int or draws < 1:
        raise ValueError("draws 必須為正整數")
    stay_probability = (
        1.0 - FIXED_SHARE
        + FIXED_SHARE / len(EXPERT_IDS)
    )
    return (
        math.log(len(EXPERT_IDS))
        - (draws - 1) * math.log(stay_probability)
    )


def _split_start(draws: int) -> int:
    eligible = draws - WARMUP_DRAWS
    if eligible < 2:
        raise ValueError("逐期研究至少需要 warmup 後兩期")
    development = math.floor(
        eligible * DEVELOPMENT_FRACTION
    )
    if development < 1 or eligible - development < 1:
        raise ValueError("development/holdout 無法切分")
    return WARMUP_DRAWS + development


def _series_summary(
    values: list[float],
    *,
    holdout_start: int,
    seed: str,
) -> dict:
    holdout = values[holdout_start:]
    ci_low, ci_high = block_bootstrap_ci(
        holdout,
        samples=BOOTSTRAP_SAMPLES,
        block=BOOTSTRAP_BLOCK_DRAWS,
        seed=seed,
    )
    return {
        "all_mean": statistics.fmean(values),
        "all_sum": math.fsum(values),
        "holdout_draws": len(holdout),
        "holdout_mean": statistics.fmean(holdout),
        "holdout_ci_low": ci_low,
        "holdout_ci_high": ci_high,
        "recent_208_mean": statistics.fmean(
            values[-min(RECENT_DRAWS, len(values)) :]
        ),
    }


def _candidate(
    *,
    source_last_dates: dict[str, str],
    final_models: dict[str, dict],
) -> dict:
    payload = {
        "schema_version": "1",
        "experiment_id": FORWARD_EXPERIMENT_ID,
        "source_experiment_id": EXPERIMENT_ID,
        "protocol_hash": PROTOCOL_HASH,
        "fitted_through": {
            game: source_last_dates[game]
            for game in (SUPER, LOTTO649)
        },
        "models": final_models,
        "use": "future_forward_shadow_only",
        "historical_backfill_allowed": False,
    }
    payload["candidate_hash"] = canonical_hash(payload)
    return payload


def validate_forward_candidate(candidate: dict) -> dict:
    if not isinstance(candidate, dict):
        raise ValueError("switching Bayes forward candidate 格式不符")
    payload = {
        key: value
        for key, value in candidate.items()
        if key != "candidate_hash"
    }
    if (
        set(candidate)
        != {
            "schema_version",
            "experiment_id",
            "source_experiment_id",
            "protocol_hash",
            "fitted_through",
            "models",
            "use",
            "historical_backfill_allowed",
            "candidate_hash",
        }
        or candidate.get("schema_version") != "1"
        or candidate.get("experiment_id") != FORWARD_EXPERIMENT_ID
        or candidate.get("source_experiment_id") != EXPERIMENT_ID
        or candidate.get("protocol_hash") != PROTOCOL_HASH
        or candidate.get("use") != "future_forward_shadow_only"
        or candidate.get("historical_backfill_allowed") is not False
        or candidate.get("candidate_hash") != canonical_hash(payload)
        or not _is_sha256(candidate.get("candidate_hash"))
        or set(candidate.get("fitted_through", {}))
        != {SUPER, LOTTO649}
        or set(candidate.get("models", {}))
        != {SUPER, LOTTO649}
    ):
        raise ValueError("switching Bayes forward candidate 契約不符")
    for game in (SUPER, LOTTO649):
        model = candidate["models"][game]
        expected = {
            "main_prior_weights",
            "special_prior_weights",
        }
        if not isinstance(model, dict) or set(model) != expected:
            raise ValueError("switching Bayes forward model 欄位不符")
        validate_weights(model["main_prior_weights"])
        if game == SUPER:
            validate_weights(model["special_prior_weights"])
        elif model["special_prior_weights"] is not None:
            raise ValueError("大樂透不得有第二區 switching 權重")
    return json.loads(json.dumps(candidate, ensure_ascii=False))


def forecast(
    game: str,
    decision: dict,
    candidate: dict,
) -> dict:
    verified = validate_forward_candidate(candidate)
    if game not in (SUPER, LOTTO649) or decision.get("game") != game:
        raise ValueError("switching Bayes forecast 遊戲不符")
    target_date = str(decision.get("target", {}).get("date"))
    if target_date <= str(verified["fitted_through"][game]):
        raise ValueError("switching Bayes candidate 含目標期或未來資料")
    main_experts = snapshot_expert_distributions(
        game,
        decision,
        dimension="main",
    )
    model = verified["models"][game]
    main_distribution = mixture_label_distribution(
        main_experts,
        model["main_prior_weights"],
    )
    special_experts = None
    special_distribution = None
    if game == SUPER:
        special_experts = snapshot_expert_distributions(
            game,
            decision,
            dimension="special",
        )
        special_distribution = mixture_label_distribution(
            special_experts,
            model["special_prior_weights"],
        )
    return {
        "game": game,
        "target": {
            "date": target_date,
            "period": int(decision["target"]["period"]),
        },
        "candidate_hash": verified["candidate_hash"],
        "source_decision_hash": decision["decision_hash"],
        "main_prior_weights": model["main_prior_weights"],
        "main_expert_distributions": main_experts,
        "main_label_distribution": main_distribution,
        "special_prior_weights": model["special_prior_weights"],
        "special_expert_distributions": special_experts,
        "special_label_distribution": special_distribution,
    }


def select_shadow_portfolio(
    game: str,
    decision: dict,
    candidate: dict,
) -> tuple[list[dict], dict]:
    prediction = forecast(game, decision, candidate)
    tickets, structure = portfolio_from_distribution(
        game,
        prediction["main_label_distribution"],
        prediction["special_label_distribution"],
    )
    return tickets, {
        "experiment_id": FORWARD_EXPERIMENT_ID,
        "candidate_hash": prediction["candidate_hash"],
        "protocol_hash": PROTOCOL_HASH,
        "source_decision_hash": prediction[
            "source_decision_hash"
        ],
        "belief_weights": prediction["main_prior_weights"],
        "structure": structure["structure"],
        "use": "future_forward_shadow_only",
    }


def build_score_capsule(prediction: dict) -> dict:
    game = prediction.get("game")
    if game not in (SUPER, LOTTO649):
        raise ValueError("switching Bayes score capsule 遊戲不符")
    payload = {
        "schema_version": "1",
        "experiment_id": SCORE_CAPSULE_EXPERIMENT_ID,
        "protocol_hash": PROTOCOL_HASH,
        "game": game,
        "target": prediction["target"],
        "candidate_hash": prediction["candidate_hash"],
        "source_decision_hash": prediction[
            "source_decision_hash"
        ],
        "main_prior_weights": prediction["main_prior_weights"],
        "main_expert_probability_mass": {
            expert: [
                prediction["main_expert_distributions"][expert][
                    number
                ]
                for number in range(1, POOL[game] + 1)
            ]
            for expert in EXPERT_IDS
        },
        "special_prior_weights": prediction[
            "special_prior_weights"
        ],
        "special_expert_probability_mass": (
            {
                expert: [
                    prediction["special_expert_distributions"][
                        expert
                    ][number]
                    for number in range(
                        1,
                        SPECIAL_POOL[SUPER] + 1,
                    )
                ]
                for expert in EXPERT_IDS
            }
            if game == SUPER
            else None
        ),
    }
    payload["capsule_hash"] = canonical_hash(payload)
    return validate_score_capsule(payload)


def validate_score_capsule(capsule: dict) -> dict:
    if not isinstance(capsule, dict):
        raise ValueError("switching Bayes score capsule 格式不符")
    payload = {
        key: value
        for key, value in capsule.items()
        if key != "capsule_hash"
    }
    expected = {
        "schema_version",
        "experiment_id",
        "protocol_hash",
        "game",
        "target",
        "candidate_hash",
        "source_decision_hash",
        "main_prior_weights",
        "main_expert_probability_mass",
        "special_prior_weights",
        "special_expert_probability_mass",
        "capsule_hash",
    }
    game = capsule.get("game")
    if (
        set(capsule) != expected
        or capsule.get("schema_version") != "1"
        or capsule.get("experiment_id")
        != SCORE_CAPSULE_EXPERIMENT_ID
        or capsule.get("protocol_hash") != PROTOCOL_HASH
        or game not in (SUPER, LOTTO649)
        or not _is_sha256(capsule.get("candidate_hash"))
        or not _is_sha256(capsule.get("source_decision_hash"))
        or capsule.get("capsule_hash") != canonical_hash(payload)
        or not _is_sha256(capsule.get("capsule_hash"))
    ):
        raise ValueError("switching Bayes score capsule 契約不符")
    validate_weights(capsule["main_prior_weights"])
    main = capsule["main_expert_probability_mass"]
    if not isinstance(main, dict) or set(main) != set(EXPERT_IDS):
        raise ValueError("switching Bayes 主號 score 分布缺漏")
    for expert in EXPERT_IDS:
        values = main[expert]
        if not isinstance(values, list) or len(values) != POOL[game]:
            raise ValueError("switching Bayes 主號 score 分布長度不符")
        _validate_distribution(
            {
                number: value
                for number, value in enumerate(values, 1)
            },
            domain_size=POOL[game],
        )
    if game == SUPER:
        validate_weights(capsule["special_prior_weights"])
        special = capsule["special_expert_probability_mass"]
        if not isinstance(special, dict) or set(special) != set(
            EXPERT_IDS
        ):
            raise ValueError("switching Bayes 第二區 score 分布缺漏")
        for expert in EXPERT_IDS:
            values = special[expert]
            if (
                not isinstance(values, list)
                or len(values) != SPECIAL_POOL[SUPER]
            ):
                raise ValueError("switching Bayes 第二區 score 分布長度不符")
            _validate_distribution(
                {
                    number: value
                    for number, value in enumerate(values, 1)
                },
                domain_size=SPECIAL_POOL[SUPER],
            )
    elif (
        capsule["special_prior_weights"] is not None
        or capsule["special_expert_probability_mass"] is not None
    ):
        raise ValueError("大樂透 score capsule 不得有第二區")
    return json.loads(json.dumps(capsule, ensure_ascii=False))


def settle_score_capsule(
    capsule: dict,
    *,
    actual_main: list[int],
    actual_special: int | None,
) -> dict:
    verified = validate_score_capsule(capsule)
    game = verified["game"]
    main_distributions = {
        expert: {
            number: value
            for number, value in enumerate(
                verified["main_expert_probability_mass"][expert],
                1,
            )
        }
        for expert in EXPERT_IDS
    }
    main_logs = main_outcome_log_probabilities(
        main_distributions,
        actual_main,
    )
    main_mix_log = mixture_outcome_log_probability(
        main_logs,
        verified["main_prior_weights"],
    )
    next_main, posterior_main = fixed_share_update(
        verified["main_prior_weights"],
        main_logs,
    )
    result = {
        "schema_version": "1",
        "experiment_id": SCORE_CAPSULE_EXPERIMENT_ID,
        "capsule_hash": verified["capsule_hash"],
        "game": game,
        "target": verified["target"],
        "main_log_probability": main_mix_log,
        "uniform_main_log_probability": -math.log(
            math.comb(POOL[game], PICK_N)
        ),
        "main_regret_vs_uniform": (
            -main_mix_log
            - math.log(math.comb(POOL[game], PICK_N))
        ),
        "main_posterior_weights": posterior_main,
        "next_main_prior_weights": next_main,
        "special_log_probability": None,
        "uniform_special_log_probability": None,
        "special_regret_vs_uniform": None,
        "special_posterior_weights": None,
        "next_special_prior_weights": None,
    }
    if game == SUPER:
        if type(actual_special) is not int:
            raise ValueError("威力彩 score settlement 缺少第二區")
        special_distributions = {
            expert: {
                number: value
                for number, value in enumerate(
                    verified[
                        "special_expert_probability_mass"
                    ][expert],
                    1,
                )
            }
            for expert in EXPERT_IDS
        }
        special_logs = special_outcome_log_probabilities(
            special_distributions,
            actual_special,
        )
        special_mix_log = mixture_outcome_log_probability(
            special_logs,
            verified["special_prior_weights"],
        )
        next_special, posterior_special = fixed_share_update(
            verified["special_prior_weights"],
            special_logs,
        )
        result.update(
            {
                "special_log_probability": special_mix_log,
                "uniform_special_log_probability": -math.log(
                    SPECIAL_POOL[SUPER]
                ),
                "special_regret_vs_uniform": (
                    -special_mix_log
                    - math.log(SPECIAL_POOL[SUPER])
                ),
                "special_posterior_weights": posterior_special,
                "next_special_prior_weights": next_special,
            }
        )
    elif actual_special is not None:
        raise ValueError("大樂透 score settlement 不得有第二區")
    result["result_hash"] = canonical_hash(result)
    return result


def run_switching_bayes_study(
    ledger_paths: dict[str, Path],
    *,
    base: Path,
    verify_ledgers: bool = True,
) -> dict:
    """Run a strict walk-forward audit without changing production picks."""
    if set(ledger_paths) != {SUPER, LOTTO649}:
        raise ValueError("switching Bayes 需要兩款遊戲 ledger")
    base = Path(base)
    records_before = tree_sha256(base / "records")
    verification = {}
    summaries = {}
    final_models = {}
    source_first_dates = {}
    source_last_dates = {}

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
        total_draws = int(verification[game]["lines"])
        holdout_start = _split_start(total_draws)
        main_weights = initial_weights()
        special_weights = (
            initial_weights() if game == SUPER else None
        )
        mixture_main_losses = []
        expert_main_losses = {
            expert: [] for expert in EXPERT_IDS
        }
        main_regrets = []
        special_regrets = []
        expert_special_losses = {
            expert: [] for expert in EXPERT_IDS
        }
        mixture_special_losses = []
        ranking_excess = {
            expert: [] for expert in EXPERT_IDS
        }
        portfolio_deltas = {
            metric: []
            for metric in (
                "union_main_hits",
                "best_main_hits",
                "any_three_plus",
                "any_prize",
            )
        }
        minimum_next_weight = 1.0
        previous_key = None

        with path.open(encoding="utf-8") as handle:
            for sequence, line in enumerate(handle, 1):
                event = json.loads(line)
                _validate_event(event, game, sequence)
                reveal = event["reveal"]
                key = (
                    str(reveal["date"]),
                    int(reveal["period"]),
                )
                if previous_key is not None and key <= previous_key:
                    raise ValueError("switching Bayes 期別未嚴格遞增")
                previous_key = key
                source_first_dates.setdefault(game, key[0])
                source_last_dates[game] = key[0]
                decision = event["decision"]
                main_experts = snapshot_expert_distributions(
                    game,
                    decision,
                    dimension="main",
                )
                main_mix = mixture_label_distribution(
                    main_experts,
                    main_weights,
                )
                special_experts = None
                special_mix = None
                if game == SUPER:
                    special_experts = snapshot_expert_distributions(
                        game,
                        decision,
                        dimension="special",
                    )
                    special_mix = mixture_label_distribution(
                        special_experts,
                        special_weights,
                    )

                belief_tickets, _ = portfolio_from_distribution(
                    game,
                    main_mix,
                    special_mix,
                )
                action_tickets, _ = (
                    select_consensus_disjoint_portfolio(
                        game,
                        decision,
                    )
                )
                belief_result = portfolio_metrics(
                    game,
                    belief_tickets,
                    reveal,
                )
                action_result = portfolio_metrics(
                    game,
                    action_tickets,
                    reveal,
                )
                for metric in portfolio_deltas:
                    portfolio_deltas[metric].append(
                        belief_result[metric]
                        - action_result[metric]
                    )

                actual_main = [
                    int(number)
                    for number in reveal["numbers"]
                ]
                actual_set = set(actual_main)
                expected_top_30 = 30 * PICK_N / POOL[game]
                for expert in HYPOTHESIS_EXPERTS:
                    ranking = sorted(
                        main_experts[expert],
                        key=lambda number: (
                            -main_experts[expert][number],
                            number,
                        ),
                    )
                    ranking_excess[expert].append(
                        len(actual_set & set(ranking[:30]))
                        - expected_top_30
                    )
                consensus_ranking = [
                    row["number"]
                    for row in _support_rows(game, decision)
                ]
                ranking_excess[DEBATE_EXPERT].append(
                    len(
                        actual_set
                        & set(consensus_ranking[:30])
                    )
                    - expected_top_30
                )
                ranking_excess[UNIFORM_EXPERT].append(0.0)

                main_logs = main_outcome_log_probabilities(
                    main_experts,
                    actual_main,
                )
                main_mix_log = mixture_outcome_log_probability(
                    main_logs,
                    main_weights,
                )
                uniform_main_log = -math.log(
                    math.comb(POOL[game], PICK_N)
                )
                mixture_main_losses.append(-main_mix_log)
                main_regrets.append(
                    -main_mix_log + uniform_main_log
                )
                for expert in EXPERT_IDS:
                    expert_main_losses[expert].append(
                        -main_logs[expert]
                    )
                main_weights, _ = fixed_share_update(
                    main_weights,
                    main_logs,
                )
                minimum_next_weight = min(
                    minimum_next_weight,
                    min(main_weights.values()),
                )

                if game == SUPER:
                    actual_special = int(reveal["special"])
                    special_logs = (
                        special_outcome_log_probabilities(
                            special_experts,
                            actual_special,
                        )
                    )
                    special_mix_log = (
                        mixture_outcome_log_probability(
                            special_logs,
                            special_weights,
                        )
                    )
                    uniform_special_log = -math.log(
                        SPECIAL_POOL[SUPER]
                    )
                    mixture_special_losses.append(
                        -special_mix_log
                    )
                    special_regrets.append(
                        -special_mix_log
                        + uniform_special_log
                    )
                    for expert in EXPERT_IDS:
                        expert_special_losses[expert].append(
                            -special_logs[expert]
                        )
                    special_weights, _ = fixed_share_update(
                        special_weights,
                        special_logs,
                    )
                    minimum_next_weight = min(
                        minimum_next_weight,
                        min(special_weights.values()),
                    )

        if sequence != total_draws:
            raise AssertionError("switching Bayes 實際讀取期數不符")
        best_main_expert = min(
            EXPERT_IDS,
            key=lambda expert: math.fsum(
                expert_main_losses[expert]
            ),
        )
        main_regret_to_best = (
            math.fsum(mixture_main_losses)
            - math.fsum(
                expert_main_losses[best_main_expert]
            )
        )
        bound = static_expert_regret_bound(total_draws)
        if main_regret_to_best > bound + 1e-9:
            raise AssertionError("switching Bayes 主號 regret bound 失敗")

        summary = {
            "game": game,
            "game_name": GAME_NAMES[game],
            "draws": total_draws,
            "first_date": source_first_dates[game],
            "last_date": source_last_dates[game],
            "holdout_start_sequence": holdout_start + 1,
            "main_exact_subset_regret_vs_uniform": _series_summary(
                main_regrets,
                holdout_start=holdout_start,
                seed=f"{EXPERIMENT_ID}|{game}|main-regret",
            ),
            "best_static_main_expert": best_main_expert,
            "main_regret_to_best_static_expert": (
                main_regret_to_best
            ),
            "main_static_expert_regret_bound": bound,
            "main_bound_pass": main_regret_to_best <= bound + 1e-9,
            "top_30_hit_excess_vs_label_symmetry": {
                expert: _series_summary(
                    ranking_excess[expert],
                    holdout_start=holdout_start,
                    seed=(
                        f"{EXPERIMENT_ID}|{game}|"
                        f"rank-{expert}"
                    ),
                )
                for expert in EXPERT_IDS
            },
            "belief_minus_consensus_action": {
                metric: _series_summary(
                    values,
                    holdout_start=holdout_start,
                    seed=(
                        f"{EXPERIMENT_ID}|{game}|"
                        f"portfolio-{metric}"
                    ),
                )
                for metric, values in portfolio_deltas.items()
            },
            "minimum_observed_next_prior_weight": (
                minimum_next_weight
            ),
        }
        if game == SUPER:
            best_special_expert = min(
                EXPERT_IDS,
                key=lambda expert: math.fsum(
                    expert_special_losses[expert]
                ),
            )
            special_regret_to_best = (
                math.fsum(mixture_special_losses)
                - math.fsum(
                    expert_special_losses[
                        best_special_expert
                    ]
                )
            )
            if special_regret_to_best > bound + 1e-9:
                raise AssertionError(
                    "switching Bayes 第二區 regret bound 失敗"
                )
            summary.update(
                {
                    "special_regret_vs_uniform": (
                        _series_summary(
                            special_regrets,
                            holdout_start=holdout_start,
                            seed=(
                                f"{EXPERIMENT_ID}|"
                                "super|special-regret"
                            ),
                        )
                    ),
                    "best_static_special_expert": (
                        best_special_expert
                    ),
                    "special_regret_to_best_static_expert": (
                        special_regret_to_best
                    ),
                    "special_static_expert_regret_bound": bound,
                    "special_bound_pass": (
                        special_regret_to_best
                        <= bound + 1e-9
                    ),
                }
            )
        summaries[game] = summary
        final_models[game] = {
            "main_prior_weights": main_weights,
            "special_prior_weights": special_weights,
        }

    consensus_signals = [
        summaries[game][
            "top_30_hit_excess_vs_label_symmetry"
        ][DEBATE_EXPERT]
        for game in (SUPER, LOTTO649)
    ]
    label_signal_proven = all(
        row["holdout_ci_low"] > 0
        for row in consensus_signals
    )
    candidate = _candidate(
        source_last_dates=source_last_dates,
        final_models=final_models,
    )
    records_after = tree_sha256(base / "records")
    return {
        "schema_version": "1",
        "experiment_id": EXPERIMENT_ID,
        "source_experiment_id": LOOP_EXPERIMENT_ID,
        "generated_at": (
            max(source_last_dates.values())
            + "T23:59:59+08:00"
        ),
        "question": (
            "若開獎生成器可能非固定亂數，完整假設機率與可切換 Bayes "
            "是否能在不偷看未來的條件下提高下一期號碼品質？"
        ),
        "methodology": {
            **PROTOCOL_CONFIG,
            "protocol_hash": PROTOCOL_HASH,
            "warmup_draws": WARMUP_DRAWS,
            "development_fraction": DEVELOPMENT_FRACTION,
            "bootstrap_block_draws": BOOTSTRAP_BLOCK_DRAWS,
            "bootstrap_samples": BOOTSTRAP_SAMPLES,
            "structural_optimum_proof": (
                structural_proof_reference()
            ),
        },
        "data_quality": {
            "status": "pass",
            "ledger_verification": verification,
            "source_first_dates": source_first_dates,
            "source_last_dates": source_last_dates,
            "chronology": "strictly_increasing",
            "lookahead_control": (
                "draw_t_uses_pre_reveal_t_weights;"
                "reveal_t_only_updates_draw_t_plus_1"
            ),
        },
        "prequential_summary": summaries,
        "final_models": final_models,
        "decision": {
            "status": "future_shadow_only",
            "label_signal_proven": label_signal_proven,
            "belief_layer_promoted": False,
            "production_number_policy": (
                "consensus_max_coverage"
            ),
            "reason": (
                "兩款遊戲的 holdout 共識 top-30 命中超額 "
                "95% block-bootstrap CI 尚未同時高於 0；"
                "因此保留可切換信念層作未來 shadow，"
                "正式出號仍採 30 主號完全互斥的共識覆蓋。"
            ),
        },
        "future_forward_shadow_candidate": candidate,
        "records_integrity": {
            "before": records_before,
            "after": records_after,
            "unchanged": records_before == records_after,
        },
    }


def write_results(result: dict, output_dir: Path) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "switching_bayes.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return path
