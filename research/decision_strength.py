"""量化機率接近均勻時，top-k 號碼決策實際承載的訊號強度。"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from statistics import NormalDist

from engine.agent_loop import canonical_hash
from engine.games import LOTTO649, PICK_N, POOL, SPECIAL_POOL, SUPER
from research.gates import tree_sha256
from research.probability_stacking import (
    EXPERT_IDS,
    MONITORING_CHECKPOINTS,
    PROTOCOL_HASH as STACKING_PROTOCOL_HASH,
    UNIFORM_EXPERT,
    expert_distributions,
    mixture_distribution,
    select_probability_stacked_portfolio,
    validate_forward_candidate,
)


EXPERIMENT_ID = "probability-label-decision-strength-audit-v1"
ONE_SIDED_ALPHA = 0.005
TARGET_POWER = 0.80
SELECTED_MAIN_NUMBERS = 30
SELECTED_SPECIAL_NUMBERS = 5
TIE_TOLERANCE = 1e-18


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hypergeometric_variance(
    *,
    population: int,
    selected: int,
    draws: int,
) -> float:
    if not 0 < selected < population or not 0 < draws <= population:
        raise ValueError("decision strength 超幾何參數不合法")
    proportion = selected / population
    return (
        draws
        * proportion
        * (1.0 - proportion)
        * (population - draws)
        / (population - 1)
    )


def distribution_strength(
    distribution: dict[int, float],
    *,
    selected_count: int,
    draws_per_event: int,
) -> dict:
    """把機率分布的軟差異換算成 top-k 決策效果與可偵測尺度。"""
    domain_size = len(distribution)
    if set(distribution) != set(range(1, domain_size + 1)):
        raise ValueError("decision strength 機率定義域不完整")
    values = [float(distribution[index]) for index in distribution]
    if (
        any(not math.isfinite(value) or value <= 0 for value in values)
        or not math.isclose(
            math.fsum(values),
            1.0,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
    ):
        raise ValueError("decision strength 機率分布不合法")
    if not 0 < selected_count < domain_size:
        raise ValueError("decision strength selected_count 不合法")
    ranking = sorted(
        distribution,
        key=lambda number: (-distribution[number], number),
    )
    selected = ranking[:selected_count]
    uniform_probability = 1.0 / domain_size
    uniform_mass = selected_count / domain_size
    selected_mass = math.fsum(
        distribution[number] for number in selected
    )
    mass_lift = selected_mass - uniform_mass
    expected_hit_lift = draws_per_event * mass_lift
    variance = _hypergeometric_variance(
        population=domain_size,
        selected=selected_count,
        draws=draws_per_event,
    )
    critical_scale = (
        NormalDist().inv_cdf(1.0 - ONE_SIDED_ALPHA)
        + NormalDist().inv_cdf(TARGET_POWER)
    )
    checkpoint_detection = {
        str(checkpoint): {
            "standard_error_under_uniform": math.sqrt(
                variance / checkpoint
            ),
            "approx_minimum_detectable_mean_lift": (
                critical_scale * math.sqrt(variance / checkpoint)
            ),
            "model_lift_to_detectable_floor_ratio": (
                expected_hit_lift
                / (critical_scale * math.sqrt(variance / checkpoint))
            ),
        }
        for checkpoint in MONITORING_CHECKPOINTS
    }
    required_pairs = (
        math.ceil(
            critical_scale
            * critical_scale
            * variance
            / (expected_hit_lift * expected_hit_lift)
        )
        if expected_hit_lift > 0
        else None
    )
    boundary_probability = distribution[ranking[selected_count - 1]]
    boundary_tied = [
        number
        for number in ranking
        if math.isclose(
            distribution[number],
            boundary_probability,
            rel_tol=0.0,
            abs_tol=TIE_TOLERANCE,
        )
    ]
    entropy = -math.fsum(
        probability * math.log(probability)
        for probability in values
    )
    maximum = max(values)
    minimum = min(values)
    return {
        "domain_size": domain_size,
        "selected_count": selected_count,
        "draws_per_event": draws_per_event,
        "selected_numbers": selected,
        "uniform_probability": uniform_probability,
        "minimum_probability": minimum,
        "maximum_probability": maximum,
        "absolute_probability_spread": maximum - minimum,
        "relative_spread_vs_uniform": (
            (maximum - minimum) / uniform_probability
        ),
        "total_variation_from_uniform": (
            0.5
            * math.fsum(
                abs(probability - uniform_probability)
                for probability in values
            )
        ),
        "kl_divergence_from_uniform": (
            math.log(domain_size) - entropy
        ),
        "selected_probability_mass": selected_mass,
        "uniform_selected_mass": uniform_mass,
        "selected_mass_lift": mass_lift,
        "model_implied_expected_hit_lift": expected_hit_lift,
        "uniform_event_variance": variance,
        "boundary_probability_gap": (
            distribution[ranking[selected_count - 1]]
            - distribution[ranking[selected_count]]
        ),
        "boundary_tied_numbers": boundary_tied,
        "boundary_tie_count": len(boundary_tied),
        "checkpoint_detection": checkpoint_detection,
        "approx_pairs_for_80pct_power": required_pairs,
    }


def _loss_diagnostics(stacking_result: dict, game: str) -> dict:
    summary = stacking_result["prequential_summary"][game]
    main = summary["mean_expert_main_log_loss"]
    uniform = float(main[UNIFORM_EXPERT])
    output = {
        "uniform_is_best_main_expert": (
            min(main, key=main.get) == UNIFORM_EXPERT
        ),
        "main_expert_loss_minus_uniform": {
            expert: float(main[expert]) - uniform
            for expert in EXPERT_IDS
            if expert != UNIFORM_EXPERT
        },
    }
    if game == SUPER:
        special = summary["mean_expert_special_log_loss"]
        uniform_special = float(special[UNIFORM_EXPERT])
        output.update(
            {
                "uniform_is_best_special_expert": (
                    min(special, key=special.get)
                    == UNIFORM_EXPERT
                ),
                "special_expert_loss_minus_uniform": {
                    expert: (
                        float(special[expert]) - uniform_special
                    )
                    for expert in EXPERT_IDS
                    if expert != UNIFORM_EXPERT
                },
            }
        )
    return output


def run_decision_strength_audit(base: Path) -> dict:
    base = Path(base)
    records_before = tree_sha256(base / "records")
    stacking_path = (
        base / "research" / "results" / "probability_stacking.json"
    )
    manifest_path = base / "simulation" / "results" / "manifest.json"
    stacking_result = json.loads(
        stacking_path.read_text(encoding="utf-8")
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    candidate = validate_forward_candidate(
        stacking_result["future_forward_shadow_candidate"]
    )
    expected_fitted = {
        game: manifest["games"][game]["last_target"]["date"]
        for game in (SUPER, LOTTO649)
    }
    if candidate["fitted_through"] != expected_fitted:
        raise ValueError(
            "decision strength stacking artifact 與目前 manifest 不同步"
        )

    games = {}
    for game in (SUPER, LOTTO649):
        decision = manifest["games"][game]["next_decision"]
        tickets, selection = select_probability_stacked_portfolio(
            game,
            decision,
            candidate,
        )
        model = candidate["models"][game]
        main_distribution = mixture_distribution(
            expert_distributions(game, decision, dimension="main"),
            model["main_log_weights"],
        )
        main_strength = distribution_strength(
            main_distribution,
            selected_count=SELECTED_MAIN_NUMBERS,
            draws_per_event=PICK_N,
        )
        if sorted(main_strength["selected_numbers"]) != sorted(
            selection["selected_main_numbers"]
        ):
            raise AssertionError(
                "decision strength 與 stacking 主號選擇不一致"
            )
        special_strength = None
        if game == SUPER:
            special_distribution = mixture_distribution(
                expert_distributions(
                    game,
                    decision,
                    dimension="special",
                ),
                model["special_log_weights"],
            )
            special_strength = distribution_strength(
                special_distribution,
                selected_count=SELECTED_SPECIAL_NUMBERS,
                draws_per_event=1,
            )
            if sorted(
                special_strength["selected_numbers"]
            ) != sorted(selection["selected_specials"]):
                raise AssertionError(
                    "decision strength 與 stacking 第二區選擇不一致"
                )
        detectable = main_strength["checkpoint_detection"][
            str(MONITORING_CHECKPOINTS[-1])
        ]["approx_minimum_detectable_mean_lift"]
        games[game] = {
            "game": game,
            "target": decision["target"],
            "source_decision_hash": decision["decision_hash"],
            "candidate_hash": candidate["candidate_hash"],
            "selection_hash": selection["selection_hash"],
            "tickets": tickets,
            "main": main_strength,
            "special": special_strength,
            "final_main_weights": model["main_weights"],
            "final_special_weights": model.get(
                "special_weights"
            ),
            "nonuniform_main_weight": (
                1.0 - model["main_weights"][UNIFORM_EXPERT]
            ),
            "loss_diagnostics": _loss_diagnostics(
                stacking_result,
                game,
            ),
            "material_at_maximum_checkpoint": (
                main_strength["model_implied_expected_hit_lift"]
                >= detectable
            ),
        }

    records_after = tree_sha256(base / "records")
    all_uniform_best = all(
        row["loss_diagnostics"]["uniform_is_best_main_expert"]
        for row in games.values()
    ) and games[SUPER]["loss_diagnostics"][
        "uniform_is_best_special_expert"
    ]
    all_immaterial = all(
        not row["material_at_maximum_checkpoint"]
        for row in games.values()
    )
    result = {
        "schema_version": "1",
        "experiment_id": EXPERIMENT_ID,
        "generated_at": (
            max(expected_fitted.values()) + "T23:59:59+08:00"
        ),
        "question": (
            "接近均勻的 stacking 機率差，是否大到足以支持 top-30 "
            "硬性號碼決策？"
        ),
        "metric_definition": {
            "soft_signal": (
                "mixture probability 相對 uniform 的 top-k mass lift"
            ),
            "decision_effect": (
                "draws_per_event × top-k mass lift，作為模型隱含的"
                "每期聯集主號命中提升"
            ),
            "uncertainty_baseline": (
                "公平開獎下固定 k 號聯集命中的超幾何變異"
            ),
            "detectability": (
                "one-sided alpha=0.005、power=0.80 的常態近似"
            ),
            "checkpoints": list(MONITORING_CHECKPOINTS),
            "historical_use": "descriptive_diagnostic_only",
        },
        "source": {
            "stacking_artifact": str(
                stacking_path.relative_to(base)
            ),
            "stacking_artifact_sha256": _file_sha256(
                stacking_path
            ),
            "stacking_protocol_hash": STACKING_PROTOCOL_HASH,
            "manifest": str(manifest_path.relative_to(base)),
            "manifest_sha256": _file_sha256(manifest_path),
            "manifest_hash": manifest["manifest_hash"],
            "fitted_through": expected_fitted,
        },
        "games": games,
        "diagnosis": {
            "uniform_is_best_in_all_scored_dimensions": (
                all_uniform_best
            ),
            "model_lift_below_max_checkpoint_detectability": (
                all_immaterial
            ),
            "top_k_amplification_present": bool(
                all_uniform_best and all_immaterial
            ),
            "interpretation": (
                "top-k 仍會輸出 30 個確定標籤，但目前軟機率差遠小於"
                "固定 832 期設計可辨識的效果；號碼清單不得被解讀為"
                "30 個有實質較高開出率的標籤。"
            ),
        },
        "decision": {
            "status": "retain_existing_future_shadow_only",
            "launch_additional_label_variant": False,
            "change_existing_frozen_numbers": False,
            "reason": (
                "現有 v5 已可用未來資料檢驗 residual ranking；在首個"
                "共同 checkpoint 前增加另一套標籤會擴大比較 family，"
                "卻沒有可偵測的模型效果支撐。"
            ),
            "next_action": (
                "維持 v5 不回填；未來同時監看 proper-score 與實際"
                "coverage 配對，只有預註冊 checkpoint 可改證據狀態。"
            ),
        },
        "records_integrity": {
            "before_sha256": records_before,
            "after_sha256": records_after,
            "unchanged": records_before == records_after,
        },
        "limitations": [
            "可偵測下限是常態近似的規劃尺度，不是新的歷史顯著性檢定。",
            "完整歷史已被多項研究使用，本稽核不重開 holdout。",
            "公平開獎下任意固定 30 個標籤的理論聯集分布相同。",
            "純模擬，不構成購買或下注建議。",
        ],
    }
    payload = {
        key: value
        for key, value in result.items()
        if key != "audit_hash"
    }
    result["audit_hash"] = canonical_hash(payload)
    if not result["records_integrity"]["unchanged"]:
        raise RuntimeError("decision strength 稽核不應修改 records")
    return result


def write_results(result: dict, output_dir: Path) -> Path:
    payload = {
        key: value
        for key, value in result.items()
        if key != "audit_hash"
    }
    if result.get("audit_hash") != canonical_hash(payload):
        raise ValueError("decision strength audit_hash 不符")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "decision_strength.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return path
