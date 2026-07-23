"""AI 辯論逐期信心是否能辨識較可靠排名的時間校準稽核。"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import random
import statistics

from engine.agent_loop import AGENT_IDS, verify_replay
from engine.games import GAME_NAMES, LOTTO649, PICK_N, POOL, SUPER
from research.agent_ablation import _validate_event
from research.debate_rank_calibration import (
    build_debate_ranking,
    ranking_metrics,
    _single_hypergeometric,
    _total_hit_distribution,
)
from research.gates import tree_sha256
from research.label_signal import _holm_adjust
from research.max_coverage import _support_rows
from research.mechanism_signal import _profile_events


EXPERIMENT_ID = "debate-confidence-gating-audit-v1"
PROTOCOL_FILE = "DEBATE_CONFIDENCE_PROTOCOL.md"
GAMES = (SUPER, LOTTO649)
CUTOFFS = (10, 30)
FEATURES = (
    "support_margin",
    "mean_candidate_disagreement",
    "proposal_hhi",
    "mean_critique_confidence",
)
PRIMARY_COMPONENTS = (
    "support_margin",
    "mean_candidate_disagreement",
)
SAFE_LAMBDAS = (0.05, 0.10, 0.20, 0.40, 0.80, 1.60)


@dataclass(frozen=True)
class DebateConfidenceConfig:
    warmup_draws: int = 60
    development_fraction: float = 0.70
    low_quantile: float = 0.25
    high_quantile: float = 0.75
    bootstrap_samples: int = 2_000
    bootstrap_block: int = 13
    minimum_holdout_group_share: float = 0.15
    maximum_holdout_mean_drift: float = 0.50

    def validate(self) -> None:
        if self.warmup_draws < 1:
            raise ValueError("辯論信心暖機至少為 1")
        if not 0.5 <= self.development_fraction < 1:
            raise ValueError(
                "development_fraction 必須介於 0.5 與 1"
            )
        if not 0 < self.low_quantile < self.high_quantile < 1:
            raise ValueError("信心分位門檻不合法")
        if self.bootstrap_samples < 100:
            raise ValueError("bootstrap_samples 至少為 100")
        if self.bootstrap_block < 1:
            raise ValueError("bootstrap_block 至少為 1")
        if not 0 < self.minimum_holdout_group_share < 0.5:
            raise ValueError("minimum_holdout_group_share 不合法")
        if self.maximum_holdout_mean_drift <= 0:
            raise ValueError("maximum_holdout_mean_drift 必須為正")


def _split_profile(
    total_draws: int,
    config: DebateConfidenceConfig,
) -> dict:
    eligible = total_draws - config.warmup_draws
    if eligible < 20:
        raise ValueError("辯論信心暖機後資料不足")
    development = math.floor(
        eligible * config.development_fraction
    )
    holdout = eligible - development
    if min(development, holdout) < 5:
        raise ValueError("辯論信心切分資料不足")
    return {
        "total_draws": total_draws,
        "warmup_draws": config.warmup_draws,
        "eligible_draws": eligible,
        "development_draws": development,
        "holdout_draws": holdout,
    }


def build_confidence_features(
    game: str,
    decision: dict,
) -> tuple[dict[str, float], list[int], dict]:
    """只用當期開獎前 decision 建立信心 feature 與完整排名。"""
    ranking, rank_quality = build_debate_ranking(game, decision)
    proposals = list(decision.get("proposals", ()))
    proposal_agents = {
        str(proposal["proposal_id"]): str(proposal["agent"])
        for proposal in proposals
    }
    critiques = list(decision.get("critiques", ()))
    critique_keys = {
        (str(row.get("critic")), str(row.get("target")))
        for row in critiques
    }
    critic_counts = Counter(
        str(row.get("critic")) for row in critiques
    )
    if (
        len(critiques) != 60
        or len(critique_keys) != 60
        or critic_counts != Counter(
            {agent: 12 for agent in AGENT_IDS}
        )
        or any(
            str(row.get("critic")) not in AGENT_IDS
            or str(row.get("target")) not in proposal_agents
            or proposal_agents[str(row.get("target"))]
            == str(row.get("critic"))
            for row in critiques
        )
    ):
        raise ValueError("辯論信心需要完整 60 筆 cross-agent critique")
    critique_confidences = [
        float(row["confidence"]) for row in critiques
    ]
    if any(
        not math.isfinite(value) or not 0 <= value <= 1
        for value in critique_confidences
    ):
        raise ValueError("critique confidence 必須是 0 到 1 的有限值")

    score_rows = list(
        decision.get("adjudication", {}).get(
            "candidate_scores", ()
        )
    )
    disagreements = [
        float(row["disagreement"]) for row in score_rows
    ]
    if len(disagreements) != 15 or any(
        not math.isfinite(value) or value < 0
        for value in disagreements
    ):
        raise ValueError("candidate disagreement 契約不合法")

    support_rows = _support_rows(game, decision)
    support_margin = (
        statistics.fmean(
            float(row["debate_support"])
            for row in support_rows[:10]
        )
        - statistics.fmean(
            float(row["debate_support"])
            for row in support_rows[10:20]
        )
    )
    appearances = Counter(
        int(number)
        for proposal in proposals
        for number in proposal["numbers"]
    )
    appearance_total = sum(appearances.values())
    proposal_hhi = math.fsum(
        (
            appearances.get(number, 0) / appearance_total
        )
        ** 2
        for number in range(1, POOL[game] + 1)
    )
    features = {
        "support_margin": support_margin,
        "mean_candidate_disagreement": statistics.fmean(
            disagreements
        ),
        "proposal_hhi": proposal_hhi,
        "mean_critique_confidence": statistics.fmean(
            critique_confidences
        ),
    }
    if any(not math.isfinite(value) for value in features.values()):
        raise ValueError("辯論信心 feature 必須全部為有限值")
    quality = {
        **rank_quality,
        "proposals": len(proposals),
        "candidate_scores": len(score_rows),
        "critiques": len(critiques),
        "unique_critique_pairs": len(critique_keys),
    }
    return features, ranking, quality


def _quantile(values: list[float], probability: float) -> float:
    if not values:
        raise ValueError("空序列無法計算分位數")
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return (
        ordered[lower] * (1 - fraction)
        + ordered[upper] * fraction
    )


def fit_confidence_model(
    development_features: list[dict[str, float]],
    *,
    low_quantile: float = 0.25,
    high_quantile: float = 0.75,
) -> dict:
    """只以 development feature 擬合固定標準化與分位閾值。"""
    if len(development_features) < 5:
        raise ValueError("擬合 confidence model 的 development 不足")
    component_stats = {}
    for feature in PRIMARY_COMPONENTS:
        values = [float(row[feature]) for row in development_features]
        mean = statistics.fmean(values)
        standard_deviation = statistics.pstdev(values)
        if not math.isfinite(standard_deviation) or standard_deviation <= 0:
            raise ValueError(f"{feature} development 標準差必須為正")
        component_stats[feature] = {
            "mean": mean,
            "standard_deviation": standard_deviation,
        }
    scores = [
        _score_components(row, component_stats)
        for row in development_features
    ]
    return {
        "component_stats": component_stats,
        "formula": (
            "(z(support_margin)-"
            "z(mean_candidate_disagreement))/sqrt(2)"
        ),
        "low_quantile": low_quantile,
        "high_quantile": high_quantile,
        "low_threshold": _quantile(scores, low_quantile),
        "high_threshold": _quantile(scores, high_quantile),
    }


def _score_components(
    features: dict[str, float],
    component_stats: dict,
) -> float:
    margin = component_stats["support_margin"]
    disagreement = component_stats[
        "mean_candidate_disagreement"
    ]
    margin_z = (
        float(features["support_margin"]) - margin["mean"]
    ) / margin["standard_deviation"]
    disagreement_z = (
        float(features["mean_candidate_disagreement"])
        - disagreement["mean"]
    ) / disagreement["standard_deviation"]
    score = (margin_z - disagreement_z) / math.sqrt(2)
    if not math.isfinite(score):
        raise ValueError("confidence index 必須為有限值")
    return score


def score_confidence(
    features: dict[str, float],
    model: dict,
) -> tuple[float, str]:
    score = _score_components(
        features, model["component_stats"]
    )
    if score >= float(model["high_threshold"]):
        group = "high"
    elif score <= float(model["low_threshold"]):
        group = "low"
    else:
        group = "middle"
    return score, group


def _feature_profile(rows: list[dict]) -> dict:
    profile = {}
    for feature in FEATURES:
        values = [float(row["features"][feature]) for row in rows]
        profile[feature] = {
            "minimum": min(values),
            "q25": _quantile(values, 0.25),
            "median": _quantile(values, 0.50),
            "q75": _quantile(values, 0.75),
            "maximum": max(values),
            "mean": statistics.fmean(values),
            "standard_deviation": statistics.pstdev(values),
            "distinct_values": len(set(values)),
        }
    scores = [float(row["confidence_index"]) for row in rows]
    groups = Counter(str(row["confidence_group"]) for row in rows)
    profile["confidence_index"] = {
        "minimum": min(scores),
        "q25": _quantile(scores, 0.25),
        "median": _quantile(scores, 0.50),
        "q75": _quantile(scores, 0.75),
        "maximum": max(scores),
        "mean": statistics.fmean(scores),
        "standard_deviation": statistics.pstdev(scores),
        "distinct_values": len(set(scores)),
    }
    profile["groups"] = {
        group: {
            "draws": groups[group],
            "share": groups[group] / len(rows),
        }
        for group in ("high", "middle", "low")
    }
    return profile


def _upper_tail_total(
    *,
    pool: int,
    selected: int,
    periods: int,
    observed: int,
) -> float:
    distribution = _total_hit_distribution(
        pool=pool,
        selected=selected,
        periods=periods,
    )
    return min(1.0, math.fsum(distribution[observed:]))


def _log_centered_mgf(
    *,
    pool: int,
    selected: int,
    theta: float,
) -> float:
    distribution = _single_hypergeometric(pool, selected)
    mean = PICK_N * selected / pool
    terms = [
        math.log(probability) + theta * (hits - mean)
        for hits, probability in enumerate(distribution)
        if probability > 0
    ]
    maximum = max(terms)
    return maximum + math.log(
        math.fsum(math.exp(term - maximum) for term in terms)
    )


def sequential_safe_evidence(
    game: str,
    cutoff: int,
    rows: list[dict],
    *,
    metric: str,
    contrast: str,
) -> dict:
    """Predictable weights 的 mixture betting e-value 與 anytime p。"""
    if contrast not in {"high_vs_null", "high_minus_low"}:
        raise ValueError("未知 sequential-safe contrast")
    expected = PICK_N * cutoff / POOL[game]
    log_e_values = []
    for betting_lambda in SAFE_LAMBDAS:
        log_e = 0.0
        for row in rows:
            group = row["confidence_group"]
            weight = (
                1.0
                if group == "high"
                else -1.0
                if contrast == "high_minus_low"
                and group == "low"
                else 0.0
            )
            if weight == 0:
                continue
            centered = float(row[metric]) - expected
            log_e += (
                betting_lambda * weight * centered
                - _log_centered_mgf(
                    pool=POOL[game],
                    selected=cutoff,
                    theta=betting_lambda * weight,
                )
            )
        log_e_values.append(log_e)
    maximum = max(log_e_values)
    log_mixture = (
        maximum
        + math.log(
            math.fsum(
                math.exp(value - maximum)
                for value in log_e_values
            )
        )
        - math.log(len(log_e_values))
    )
    anytime_p = (
        math.exp(-log_mixture) if log_mixture > 0 else 1.0
    )
    capped = log_mixture > 700
    return {
        "contrast": contrast,
        "lambdas": list(SAFE_LAMBDAS),
        "component_log_e_values": log_e_values,
        "mixture_log_e_value": log_mixture,
        "mixture_e_value": math.exp(min(log_mixture, 700)),
        "e_value_capped": capped,
        "anytime_valid_p_value": min(1.0, anytime_p),
        "predictable_weight_contract": (
            "high=1,other=0"
            if contrast == "high_vs_null"
            else "high=1,low=-1,middle=0"
        ),
    }


def _interaction_upper_tail(
    *,
    pool: int,
    selected: int,
    high_periods: int,
    low_periods: int,
    high_observed: int,
    low_observed: int,
) -> float:
    """精確計算 high mean - low mean 至少與觀察值同大的機率。"""
    if high_periods < 1 or low_periods < 1:
        raise ValueError("high／low 精確 interaction 需要非空群組")
    high_distribution = _total_hit_distribution(
        pool=pool,
        selected=selected,
        periods=high_periods,
    )
    low_distribution = _total_hit_distribution(
        pool=pool,
        selected=selected,
        periods=low_periods,
    )
    observed_numerator = (
        high_observed * low_periods
        - low_observed * high_periods
    )
    probability = 0.0
    for high_hits, high_probability in enumerate(
        high_distribution
    ):
        if high_probability == 0:
            continue
        conditional = math.fsum(
            low_probability
            for low_hits, low_probability in enumerate(
                low_distribution
            )
            if (
                high_hits * low_periods
                - low_hits * high_periods
                >= observed_numerator
            )
        )
        probability += high_probability * conditional
    return min(1.0, probability)


def _circular_block_indices(
    length: int,
    *,
    block: int,
    rng: random.Random,
) -> list[int]:
    if length < 1:
        raise ValueError("block bootstrap 序列不得為空")
    indices = []
    while len(indices) < length:
        start = rng.randrange(length)
        indices.extend(
            (start + offset) % length for offset in range(block)
        )
    return indices[:length]


def confidence_block_bootstrap_ci(
    rows: list[dict],
    *,
    metric: str,
    expected: float,
    samples: int,
    block: int,
    seed: str,
) -> dict:
    """以完整時間序列 block 重抽 high-null 與 high-low 平均差。"""
    if samples < 100:
        raise ValueError("confidence bootstrap samples 至少為 100")
    if block < 1:
        raise ValueError("confidence bootstrap block 至少為 1")
    if not any(row["confidence_group"] == "high" for row in rows):
        raise ValueError("confidence bootstrap 缺少 high 群")
    if not any(row["confidence_group"] == "low" for row in rows):
        raise ValueError("confidence bootstrap 缺少 low 群")
    rng = random.Random(
        int.from_bytes(
            hashlib.sha256(seed.encode("utf-8")).digest()[:8],
            "big",
        )
    )
    high_null_values = []
    interaction_values = []
    attempts = 0
    maximum_attempts = samples * 20
    while (
        len(high_null_values) < samples
        and attempts < maximum_attempts
    ):
        attempts += 1
        sampled = [
            rows[index]
            for index in _circular_block_indices(
                len(rows), block=block, rng=rng
            )
        ]
        high = [
            float(row[metric])
            for row in sampled
            if row["confidence_group"] == "high"
        ]
        low = [
            float(row[metric])
            for row in sampled
            if row["confidence_group"] == "low"
        ]
        if not high or not low:
            continue
        high_mean = statistics.fmean(high)
        high_null_values.append(high_mean - expected)
        interaction_values.append(
            high_mean - statistics.fmean(low)
        )
    if len(high_null_values) != samples:
        raise RuntimeError("confidence bootstrap 無法取得足夠有效樣本")
    return {
        "samples": samples,
        "block_draws": block,
        "high_vs_null_ci_low": _quantile(
            high_null_values, 0.025
        ),
        "high_vs_null_ci_high": _quantile(
            high_null_values, 0.975
        ),
        "high_minus_low_ci_low": _quantile(
            interaction_values, 0.025
        ),
        "high_minus_low_ci_high": _quantile(
            interaction_values, 0.975
        ),
    }


def _group_effect(
    rows: list[dict],
    *,
    metric: str,
    expected: float,
) -> dict:
    high = [
        float(row[metric])
        for row in rows
        if row["confidence_group"] == "high"
    ]
    low = [
        float(row[metric])
        for row in rows
        if row["confidence_group"] == "low"
    ]
    if not high or not low:
        return {
            "draws": len(rows),
            "high_draws": len(high),
            "low_draws": len(low),
            "high_mean_hits": None,
            "low_mean_hits": None,
            "exact_null_mean_hits": expected,
            "high_delta_vs_null": None,
            "high_minus_low": None,
        }
    high_mean = statistics.fmean(high)
    low_mean = statistics.fmean(low)
    return {
        "draws": len(rows),
        "high_draws": len(high),
        "low_draws": len(low),
        "high_total_hits": round(sum(high)),
        "low_total_hits": round(sum(low)),
        "high_mean_hits": high_mean,
        "low_mean_hits": low_mean,
        "exact_null_mean_hits": expected,
        "high_delta_vs_null": high_mean - expected,
        "high_minus_low": high_mean - low_mean,
    }


def _cutoff_result(
    game: str,
    cutoff: int,
    rows: list[dict],
    *,
    split: str,
    config: DebateConfidenceConfig,
    exact_tests: bool,
) -> dict:
    metric = f"top_{cutoff}_hits"
    expected = PICK_N * cutoff / POOL[game]
    result = _group_effect(rows, metric=metric, expected=expected)
    midpoint = len(rows) // 2
    result["first_half"] = _group_effect(
        rows[:midpoint], metric=metric, expected=expected
    )
    result["second_half"] = _group_effect(
        rows[midpoint:], metric=metric, expected=expected
    )
    if exact_tests:
        if result["high_draws"] < 1 or result["low_draws"] < 1:
            raise ValueError("holdout high／low 群不足以執行精確檢定")
        result["high_vs_null_one_sided_p_value"] = (
            _upper_tail_total(
                pool=POOL[game],
                selected=cutoff,
                periods=result["high_draws"],
                observed=result["high_total_hits"],
            )
        )
        result["high_minus_low_one_sided_p_value"] = (
            _interaction_upper_tail(
                pool=POOL[game],
                selected=cutoff,
                high_periods=result["high_draws"],
                low_periods=result["low_draws"],
                high_observed=result["high_total_hits"],
                low_observed=result["low_total_hits"],
            )
        )
        result["block_bootstrap"] = confidence_block_bootstrap_ci(
            rows,
            metric=metric,
            expected=expected,
            samples=config.bootstrap_samples,
            block=config.bootstrap_block,
            seed=(
                f"{EXPERIMENT_ID}|{game}|{split}|top-{cutoff}"
            ),
        )
        result["sequential_safe"] = {
            contrast: sequential_safe_evidence(
                game,
                cutoff,
                rows,
                metric=metric,
                contrast=contrast,
            )
            for contrast in (
                "high_vs_null",
                "high_minus_low",
            )
        }
    return result


def _candidate_gate(
    development: dict,
    holdout: dict,
    *,
    distribution_gate_passed: bool,
) -> tuple[bool, list[str]]:
    failures = []
    if development["high_delta_vs_null"] <= 0:
        failures.append("development_high_vs_null_not_positive")
    if development["high_minus_low"] <= 0:
        failures.append("development_high_minus_low_not_positive")
    if (
        holdout["holm_high_vs_null_one_sided_p_value"]
        >= 0.05
    ):
        failures.append("holdout_high_vs_null_holm")
    if (
        holdout["holm_high_minus_low_one_sided_p_value"]
        >= 0.05
    ):
        failures.append("holdout_high_minus_low_holm")
    safe = holdout["sequential_safe"]
    if (
        safe["high_vs_null"]["holm_anytime_valid_p_value"]
        >= 0.05
    ):
        failures.append("holdout_high_vs_null_safe_holm")
    if (
        safe["high_minus_low"]["holm_anytime_valid_p_value"]
        >= 0.05
    ):
        failures.append("holdout_high_minus_low_safe_holm")
    bootstrap = holdout["block_bootstrap"]
    if bootstrap["high_vs_null_ci_low"] <= 0:
        failures.append("holdout_high_vs_null_ci")
    if bootstrap["high_minus_low_ci_low"] <= 0:
        failures.append("holdout_high_minus_low_ci")
    for half in ("first_half", "second_half"):
        if holdout[half]["high_delta_vs_null"] is None or (
            holdout[half]["high_delta_vs_null"] <= 0
        ):
            failures.append(f"{half}_high_vs_null")
        if holdout[half]["high_minus_low"] is None or (
            holdout[half]["high_minus_low"] <= 0
        ):
            failures.append(f"{half}_high_minus_low")
    if not distribution_gate_passed:
        failures.append("confidence_distribution_gate")
    return not failures, failures


def _future_candidate(
    *,
    game: str,
    cutoff: int,
    model: dict,
    last_development_date: str,
) -> dict:
    content = {
        "experiment_id": EXPERIMENT_ID,
        "game": game,
        "cutoff": cutoff,
        "fitted_through": last_development_date,
        "confidence_model": model,
        "high_policy": "debate_ranking",
        "non_high_policy": (
            "sha256_uniform_ranking("
            "experiment_id|game|date|period)"
        ),
        "use": "future_forward_shadow_only",
        "no_backfill": True,
    }
    canonical = json.dumps(
        content,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        **content,
        "candidate_hash": hashlib.sha256(canonical).hexdigest(),
    }


def run_debate_confidence_study(
    ledger_paths: dict[str, Path],
    *,
    base: Path,
    config: DebateConfidenceConfig | None = None,
    verify_ledgers: bool = True,
) -> dict:
    config = config or DebateConfidenceConfig()
    config.validate()
    base = Path(base)
    protocol_path = base / PROTOCOL_FILE
    if not protocol_path.exists():
        raise RuntimeError("缺少 AI 辯論逐期信心預註冊文件")
    protocol_hash = hashlib.sha256(
        protocol_path.read_bytes()
    ).hexdigest()
    records_before = tree_sha256(base / "records")
    game_results = {}
    raw_p_values = {}
    raw_safe_p_values = {}

    for game in GAMES:
        path = Path(ledger_paths[game])
        verification = (
            verify_replay(path)
            if verify_ledgers
            else {
                "lines": sum(
                    1 for _ in path.open(encoding="utf-8")
                )
            }
        )
        events = []
        feature_rows = []
        quality_rows = []
        with path.open(encoding="utf-8") as handle:
            for sequence, line in enumerate(handle, 1):
                event = json.loads(line)
                _validate_event(event, game, sequence)
                events.append(event)
                if sequence <= config.warmup_draws:
                    continue
                features, ranking, quality = (
                    build_confidence_features(
                        game, event["decision"]
                    )
                )
                feature_rows.append(
                    {
                        "date": event["reveal"]["date"],
                        "period": int(event["reveal"]["period"]),
                        "features": features,
                        "ranking": ranking,
                        "actual_numbers": list(
                            event["reveal"]["numbers"]
                        ),
                    }
                )
                quality_rows.append(quality)
        profile = _profile_events(game, events)
        if profile["quality_status"] != "pass":
            raise RuntimeError(f"{game} 辯論信心來源資料品質失敗")
        split = _split_profile(len(events), config)
        if len(feature_rows) != split["eligible_draws"]:
            raise AssertionError("辯論信心 feature row 數不符")
        development_count = split["development_draws"]
        development_features = [
            row["features"]
            for row in feature_rows[:development_count]
        ]
        model = fit_confidence_model(
            development_features,
            low_quantile=config.low_quantile,
            high_quantile=config.high_quantile,
        )

        # 所有 group 都在 outcome 評分前由凍結 development model 指派。
        for row in feature_rows:
            score, group = score_confidence(
                row["features"], model
            )
            row["confidence_index"] = score
            row["confidence_group"] = group
        for row in feature_rows:
            metrics = ranking_metrics(
                game,
                row.pop("ranking"),
                row.pop("actual_numbers"),
            )
            row.update(metrics)

        development_rows = feature_rows[:development_count]
        holdout_rows = feature_rows[development_count:]
        development_profile = _feature_profile(development_rows)
        holdout_profile = _feature_profile(holdout_rows)
        holdout_groups = holdout_profile["groups"]
        midpoint = len(holdout_rows) // 2
        half_groups_nonempty = all(
            any(row["confidence_group"] == group for row in half)
            for half in (
                holdout_rows[:midpoint],
                holdout_rows[midpoint:],
            )
            for group in ("high", "low")
        )
        group_share_gate = all(
            holdout_groups[group]["share"]
            >= config.minimum_holdout_group_share
            for group in ("high", "low")
        )
        mean_drift_gate = (
            abs(holdout_profile["confidence_index"]["mean"])
            <= config.maximum_holdout_mean_drift
        )
        distribution_gate_passed = (
            group_share_gate
            and mean_drift_gate
            and half_groups_nonempty
        )

        development = {}
        holdout = {}
        for cutoff in CUTOFFS:
            metric = f"top_{cutoff}_hits"
            development[metric] = _cutoff_result(
                game,
                cutoff,
                development_rows,
                split="development",
                config=config,
                exact_tests=False,
            )
            holdout[metric] = _cutoff_result(
                game,
                cutoff,
                holdout_rows,
                split="holdout",
                config=config,
                exact_tests=True,
            )
            raw_p_values[
                f"{game}:{metric}:high_vs_null"
            ] = holdout[metric][
                "high_vs_null_one_sided_p_value"
            ]
            raw_p_values[
                f"{game}:{metric}:high_minus_low"
            ] = holdout[metric][
                "high_minus_low_one_sided_p_value"
            ]
            for contrast in (
                "high_vs_null",
                "high_minus_low",
            ):
                raw_safe_p_values[
                    f"{game}:{metric}:{contrast}"
                ] = holdout[metric]["sequential_safe"][
                    contrast
                ]["anytime_valid_p_value"]

        game_results[game] = {
            "game_name": GAME_NAMES[game],
            "data_quality": {
                "status": "pass",
                "profile": profile,
                "ledger_verification": verification,
                "split_profile": split,
                "feature_rows": len(feature_rows),
                "ranking_size_min": min(
                    row["ranking_size"] for row in quality_rows
                ),
                "ranking_size_max": max(
                    row["ranking_size"] for row in quality_rows
                ),
                "unique_numbers_min": min(
                    row["unique_numbers"] for row in quality_rows
                ),
                "proposals_min": min(
                    row["proposals"] for row in quality_rows
                ),
                "candidate_scores_min": min(
                    row["candidate_scores"] for row in quality_rows
                ),
                "critiques_min": min(
                    row["critiques"] for row in quality_rows
                ),
                "unique_critique_pairs_min": min(
                    row["unique_critique_pairs"]
                    for row in quality_rows
                ),
                "proposal_appearances_total_min": min(
                    row["proposal_appearances_total"]
                    for row in quality_rows
                ),
                "development_feature_profile": (
                    development_profile
                ),
                "holdout_feature_profile": holdout_profile,
                "distribution_checks": {
                    "minimum_group_share": (
                        config.minimum_holdout_group_share
                    ),
                    "high_share": holdout_groups["high"]["share"],
                    "low_share": holdout_groups["low"]["share"],
                    "group_share_gate_passed": group_share_gate,
                    "maximum_absolute_mean_drift": (
                        config.maximum_holdout_mean_drift
                    ),
                    "holdout_confidence_mean": (
                        holdout_profile["confidence_index"]["mean"]
                    ),
                    "mean_drift_gate_passed": mean_drift_gate,
                    "half_groups_nonempty": half_groups_nonempty,
                    "distribution_gate_passed": (
                        distribution_gate_passed
                    ),
                },
            },
            "confidence_model": model,
            "development": development,
            "holdout": holdout,
            "last_development_date": development_rows[-1]["date"],
        }

    adjusted = _holm_adjust(raw_p_values)
    safe_adjusted = _holm_adjust(raw_safe_p_values)
    candidates = []
    for game in GAMES:
        game_result = game_results[game]
        distribution_gate_passed = game_result["data_quality"][
            "distribution_checks"
        ]["distribution_gate_passed"]
        for cutoff in CUTOFFS:
            metric = f"top_{cutoff}_hits"
            holdout = game_result["holdout"][metric]
            holdout[
                "holm_high_vs_null_one_sided_p_value"
            ] = adjusted[f"{game}:{metric}:high_vs_null"]
            holdout[
                "holm_high_minus_low_one_sided_p_value"
            ] = adjusted[f"{game}:{metric}:high_minus_low"]
            for contrast in (
                "high_vs_null",
                "high_minus_low",
            ):
                holdout["sequential_safe"][contrast][
                    "holm_anytime_valid_p_value"
                ] = safe_adjusted[
                    f"{game}:{metric}:{contrast}"
                ]
            passed, failures = _candidate_gate(
                game_result["development"][metric],
                holdout,
                distribution_gate_passed=distribution_gate_passed,
            )
            holdout["candidate_gate_passed"] = passed
            holdout["candidate_gate_failures"] = failures
            if passed:
                candidates.append(
                    _future_candidate(
                        game=game,
                        cutoff=cutoff,
                        model=game_result["confidence_model"],
                        last_development_date=game_result[
                            "last_development_date"
                        ],
                    )
                )

    records_after = tree_sha256(base / "records")
    if records_before != records_after:
        raise RuntimeError("辯論信心研究不得改動正式 records")
    return {
        "schema_version": "1",
        "experiment_id": EXPERIMENT_ID,
        "generated_at": max(
            game_results[game]["data_quality"]["profile"][
                "last_date"
            ]
            for game in GAMES
        )
        + "T23:59:59+08:00",
        "question": (
            "辯論支持 margin 高且 candidate disagreement 低的期數，"
            "其 top-10／top-30 是否比公平零模型與低信心期更高？"
        ),
        "protocol": {
            "file": PROTOCOL_FILE,
            "sha256": protocol_hash,
            "cutoffs": list(CUTOFFS),
            "holm_family": sorted(raw_p_values),
            "sequential_safe_holm_family": sorted(
                raw_safe_p_values
            ),
            "statistical_unit": "one_draw",
            "direction": "one_sided_positive_only",
        },
        "methodology": {
            "warmup_draws": config.warmup_draws,
            "development_fraction": (
                config.development_fraction
            ),
            "primary_components": list(PRIMARY_COMPONENTS),
            "profile_only_features": [
                "proposal_hhi",
                "mean_critique_confidence",
            ],
            "confidence_formula": (
                "(z(support_margin)-"
                "z(mean_candidate_disagreement))/sqrt(2)"
            ),
            "low_quantile": config.low_quantile,
            "high_quantile": config.high_quantile,
            "bootstrap_samples": config.bootstrap_samples,
            "bootstrap_block_draws": config.bootstrap_block,
            "sequential_safe_lambdas": list(SAFE_LAMBDAS),
            "post_unblinding_qa_amendment": (
                "fixed-realized-group convolution 保留為敏感度；"
                "candidate gate 另要求 predictable-weight mixture "
                "e-value 的 anytime-valid Holm p。"
            ),
            "exact_null": (
                "single-draw Hypergeometric(pool, cutoff, 6); "
                "complete convolution for high-vs-null and exact "
                "enumeration of high mean minus low mean"
            ),
            "no_lookahead": (
                "build_confidence_features 只接收 decision；"
                "development model 指派完所有 group 後才以另一函式評分。"
            ),
        },
        "games": game_results,
        "future_forward_shadow_candidates": candidates,
        "conclusion": {
            "status": (
                "future_confidence_gated_shadow_candidates_created"
                if candidates
                else "stop_new_historical_confidence_hypotheses"
            ),
            "historical_gate_passed": bool(candidates),
            "candidate_count": len(candidates),
            "decision": (
                "future_shadow_only_no_backfill"
                if candidates
                else "wait_for_existing_forward_evidence"
            ),
            "honesty_note": (
                "完整歷史已被重複研究；任何通過也只是假說產生，"
                "不得直接更換正式號碼。"
            ),
        },
        "records_integrity": {
            "before_sha256": records_before,
            "after_sha256": records_after,
            "unchanged": records_before == records_after,
        },
        "limitations": [
            "本研究在整體辯論排名未校準後提出，完整歷史不是全新確認性資料。",
            "條件式 association 不代表開獎機制會讀取或回應 Agent 信心。",
            "middle 群未進入 high-low 對比，不能把條件差直接當全期 lift。",
            "公平模型下所有合法號碼標籤的理論開出機率相同。",
            "純模擬，不構成購買或下注建議。",
        ],
    }


def write_results(result: dict, output_dir: Path) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "debate_confidence.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return path
