"""AI 辯論主號完整排名的時間校準與 multiplicity 映射稽核。"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import statistics

from engine.agent_loop import verify_replay
from engine.games import GAME_NAMES, LOTTO649, PICK_N, POOL, SUPER
from research.agent_ablation import _validate_event, block_bootstrap_ci
from research.gates import tree_sha256
from research.label_signal import _holm_adjust
from research.max_coverage import _support_rows
from research.mechanism_signal import _profile_events


EXPERIMENT_ID = "debate-main-rank-calibration-audit-v1"
PROTOCOL_FILE = "DEBATE_RANK_CALIBRATION_PROTOCOL.md"
GAMES = (SUPER, LOTTO649)
CUTOFFS = (10, 20, 30)


@dataclass(frozen=True)
class DebateRankCalibrationConfig:
    warmup_draws: int = 60
    development_fraction: float = 0.70
    bootstrap_samples: int = 2_000
    bootstrap_block: int = 13

    def validate(self) -> None:
        if self.warmup_draws < 1:
            raise ValueError("辯論排名校準 warmup 至少為 1")
        if not 0.5 <= self.development_fraction < 1:
            raise ValueError(
                "development_fraction 必須介於 0.5 與 1"
            )
        if self.bootstrap_samples < 100:
            raise ValueError("bootstrap_samples 至少為 100")
        if self.bootstrap_block < 1:
            raise ValueError("bootstrap_block 至少為 1")


def _split_profile(
    total_draws: int,
    config: DebateRankCalibrationConfig,
) -> dict:
    eligible = total_draws - config.warmup_draws
    if eligible < 20:
        raise ValueError("辯論排名校準暖機後資料不足")
    development = math.floor(
        eligible * config.development_fraction
    )
    holdout = eligible - development
    if min(development, holdout) < 5:
        raise ValueError("辯論排名校準切分資料不足")
    return {
        "total_draws": total_draws,
        "warmup_draws": config.warmup_draws,
        "eligible_draws": eligible,
        "development_draws": development,
        "holdout_draws": holdout,
    }


def build_debate_ranking(
    game: str,
    decision: dict,
) -> tuple[list[int], dict]:
    """只用開獎前 decision 建立完整排名，不接受當期開獎答案。"""
    proposals = list(decision.get("proposals", ()))
    candidate_scores = list(
        decision.get("adjudication", {}).get(
            "candidate_scores", ()
        )
    )
    proposal_ids = [
        str(proposal.get("proposal_id")) for proposal in proposals
    ]
    score_ids = [
        str(row.get("proposal_id")) for row in candidate_scores
    ]
    if (
        len(proposals) != 15
        or len(set(proposal_ids)) != 15
        or len(candidate_scores) != 15
        or len(set(score_ids)) != 15
        or set(score_ids) != set(proposal_ids)
    ):
        raise ValueError("辯論排名需要 15 個唯一提案與一對一辯論分數")
    if any(
        len(proposal.get("numbers", ())) != PICK_N
        or len({int(number) for number in proposal["numbers"]})
        != PICK_N
        or any(
            not 1 <= int(number) <= POOL[game]
            for number in proposal["numbers"]
        )
        for proposal in proposals
    ):
        raise ValueError("辯論提案主號必須是六個唯一合法號碼")

    rows = _support_rows(game, decision)
    ranking = [int(row["number"]) for row in rows]
    expected = list(range(1, POOL[game] + 1))
    if sorted(ranking) != expected:
        raise RuntimeError("辯論排名沒有完整涵蓋號碼池")
    quality = {
        "ranking_size": len(ranking),
        "unique_numbers": len(set(ranking)),
        "zero_support_numbers": sum(
            float(row["debate_support"]) == 0.0 for row in rows
        ),
        "distinct_support_scores": len(
            {float(row["debate_support"]) for row in rows}
        ),
        "proposal_appearances_total": sum(
            int(row["proposal_appearances"]) for row in rows
        ),
    }
    if (
        quality["ranking_size"] != POOL[game]
        or quality["unique_numbers"] != POOL[game]
        or quality["proposal_appearances_total"] != 15 * PICK_N
    ):
        raise RuntimeError("辯論排名資料品質契約未通過")
    return ranking, quality


def ranking_metrics(
    game: str,
    ranking: list[int] | tuple[int, ...],
    actual_numbers: list[int] | tuple[int, ...],
) -> dict[str, float]:
    """在排名封存後才用當期答案評分。"""
    if (
        len(ranking) != POOL[game]
        or sorted(int(number) for number in ranking)
        != list(range(1, POOL[game] + 1))
    ):
        raise ValueError("評分需要完整且唯一的辯論排名")
    actual = {int(number) for number in actual_numbers}
    if (
        len(actual_numbers) != PICK_N
        or len(actual) != PICK_N
        or any(not 1 <= number <= POOL[game] for number in actual)
    ):
        raise ValueError("評分答案必須是六個唯一合法主號")
    top_10_hits = len(set(ranking[:10]) & actual)
    next_10_hits = len(set(ranking[10:20]) & actual)
    metrics = {
        f"top_{cutoff}_hits": float(
            len(set(ranking[:cutoff]) & actual)
        )
        for cutoff in CUTOFFS
    }
    metrics["top_10_minus_next_10_hits"] = float(
        top_10_hits - next_10_hits
    )
    return metrics


def _single_hypergeometric(
    pool: int,
    selected: int,
) -> list[float]:
    denominator = math.comb(pool, PICK_N)
    return [
        (
            math.comb(selected, hits)
            * math.comb(pool - selected, PICK_N - hits)
            / denominator
        )
        if 0 <= PICK_N - hits <= pool - selected
        else 0.0
        for hits in range(PICK_N + 1)
    ]


def _total_hit_distribution(
    *,
    pool: int,
    selected: int,
    periods: int,
) -> list[float]:
    if periods < 1:
        raise ValueError("精確總命中分布期數至少為 1")
    single = _single_hypergeometric(pool, selected)
    distribution = [1.0]
    for _ in range(periods):
        next_distribution = [0.0] * (
            len(distribution) + PICK_N
        )
        for total, probability in enumerate(distribution):
            if probability == 0:
                continue
            for hits, hit_probability in enumerate(single):
                next_distribution[total + hits] += (
                    probability * hit_probability
                )
        distribution = next_distribution
    normalization = math.fsum(distribution)
    return [value / normalization for value in distribution]


def _two_sided_exact_p(
    *,
    pool: int,
    selected: int,
    periods: int,
    observed: int,
) -> dict:
    distribution = _total_hit_distribution(
        pool=pool,
        selected=selected,
        periods=periods,
    )
    lower = min(1.0, math.fsum(distribution[: observed + 1]))
    upper = min(1.0, math.fsum(distribution[observed:]))
    return {
        "lower_tail_p_value": lower,
        "upper_tail_p_value": upper,
        "two_sided_p_value": min(1.0, 2 * min(lower, upper)),
    }


def _mean(values: list[float]) -> float:
    return statistics.fmean(values)


def _cutoff_result(
    game: str,
    cutoff: int,
    values: list[float],
    *,
    split: str,
    config: DebateRankCalibrationConfig,
    exact_p: bool,
) -> dict:
    expected = PICK_N * cutoff / POOL[game]
    deltas = [value - expected for value in values]
    ci_low, ci_high = block_bootstrap_ci(
        deltas,
        samples=config.bootstrap_samples,
        block=config.bootstrap_block,
        seed=(
            f"{EXPERIMENT_ID}|{game}|{split}|top-{cutoff}"
        ),
    )
    midpoint = len(values) // 2
    result = {
        "draws": len(values),
        "observed_total_hits": round(sum(values)),
        "observed_mean_hits": _mean(values),
        "exact_null_mean_hits": expected,
        "mean_delta_vs_exact_null": _mean(deltas),
        "delta_ci_low": ci_low,
        "delta_ci_high": ci_high,
        "first_half_mean_delta": _mean(deltas[:midpoint]),
        "second_half_mean_delta": _mean(deltas[midpoint:]),
    }
    if exact_p:
        result.update(
            _two_sided_exact_p(
                pool=POOL[game],
                selected=cutoff,
                periods=len(values),
                observed=result["observed_total_hits"],
            )
        )
    return result


def _contrast_result(
    game: str,
    values: list[float],
    *,
    split: str,
    config: DebateRankCalibrationConfig,
) -> dict:
    ci_low, ci_high = block_bootstrap_ci(
        values,
        samples=config.bootstrap_samples,
        block=config.bootstrap_block,
        seed=(
            f"{EXPERIMENT_ID}|{game}|{split}|"
            "top-10-minus-next-10"
        ),
    )
    midpoint = len(values) // 2
    return {
        "draws": len(values),
        "mean_delta": _mean(values),
        "delta_ci_low": ci_low,
        "delta_ci_high": ci_high,
        "first_half_mean_delta": _mean(values[:midpoint]),
        "second_half_mean_delta": _mean(values[midpoint:]),
    }


def _direction(
    development: dict,
    holdout: dict,
) -> str:
    adjusted = holdout["holm_adjusted_two_sided_p_value"]
    if (
        development["mean_delta_vs_exact_null"] > 0
        and adjusted < 0.05
        and holdout["delta_ci_low"] > 0
        and holdout["first_half_mean_delta"] > 0
        and holdout["second_half_mean_delta"] > 0
    ):
        return "positive_calibration"
    if (
        development["mean_delta_vs_exact_null"] < 0
        and adjusted < 0.05
        and holdout["delta_ci_high"] < 0
        and holdout["first_half_mean_delta"] < 0
        and holdout["second_half_mean_delta"] < 0
    ):
        return "negative_calibration"
    return "not_calibrated"


def run_debate_rank_calibration(
    ledger_paths: dict[str, Path],
    *,
    base: Path,
    config: DebateRankCalibrationConfig | None = None,
    verify_ledgers: bool = True,
) -> dict:
    config = config or DebateRankCalibrationConfig()
    config.validate()
    base = Path(base)
    protocol_path = base / PROTOCOL_FILE
    if not protocol_path.exists():
        raise RuntimeError("缺少 AI 辯論排名校準預註冊文件")
    protocol_hash = hashlib.sha256(
        protocol_path.read_bytes()
    ).hexdigest()
    records_before = tree_sha256(base / "records")
    game_results = {}
    raw_p_values = {}

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
        with path.open(encoding="utf-8") as handle:
            for sequence, line in enumerate(handle, 1):
                event = json.loads(line)
                _validate_event(event, game, sequence)
                events.append(event)
        profile = _profile_events(game, events)
        if profile["quality_status"] != "pass":
            raise RuntimeError(f"{game} 辯論排名資料品質失敗")
        split = _split_profile(len(events), config)
        metric_rows = []
        quality_rows = []
        for event in events[config.warmup_draws :]:
            ranking, quality = build_debate_ranking(
                game,
                event["decision"],
            )
            metrics = ranking_metrics(
                game,
                ranking,
                event["reveal"]["numbers"],
            )
            metric_rows.append(metrics)
            quality_rows.append(quality)
        development_count = split["development_draws"]
        development_rows = metric_rows[:development_count]
        holdout_rows = metric_rows[development_count:]
        development = {}
        holdout = {}
        for cutoff in CUTOFFS:
            metric = f"top_{cutoff}_hits"
            development[metric] = _cutoff_result(
                game,
                cutoff,
                [row[metric] for row in development_rows],
                split="development",
                config=config,
                exact_p=False,
            )
            holdout[metric] = _cutoff_result(
                game,
                cutoff,
                [row[metric] for row in holdout_rows],
                split="holdout",
                config=config,
                exact_p=True,
            )
            raw_p_values[f"{game}:{metric}"] = holdout[metric][
                "two_sided_p_value"
            ]
        contrast_metric = "top_10_minus_next_10_hits"
        development[contrast_metric] = _contrast_result(
            game,
            [row[contrast_metric] for row in development_rows],
            split="development",
            config=config,
        )
        holdout[contrast_metric] = _contrast_result(
            game,
            [row[contrast_metric] for row in holdout_rows],
            split="holdout",
            config=config,
        )
        game_results[game] = {
            "game_name": GAME_NAMES[game],
            "data_quality": {
                "status": profile["quality_status"],
                "profile": profile,
                "ledger_verification": verification,
                "split_profile": split,
                "ranking_rows": len(quality_rows),
                "ranking_size_min": min(
                    row["ranking_size"] for row in quality_rows
                ),
                "ranking_size_max": max(
                    row["ranking_size"] for row in quality_rows
                ),
                "unique_numbers_min": min(
                    row["unique_numbers"] for row in quality_rows
                ),
                "proposal_appearances_total_min": min(
                    row["proposal_appearances_total"]
                    for row in quality_rows
                ),
                "proposal_appearances_total_max": max(
                    row["proposal_appearances_total"]
                    for row in quality_rows
                ),
                "mean_zero_support_numbers": statistics.fmean(
                    row["zero_support_numbers"]
                    for row in quality_rows
                ),
                "mean_distinct_support_scores": statistics.fmean(
                    row["distinct_support_scores"]
                    for row in quality_rows
                ),
            },
            "development": development,
            "holdout": holdout,
        }

    adjusted = _holm_adjust(raw_p_values)
    for game in GAMES:
        for cutoff in CUTOFFS:
            metric = f"top_{cutoff}_hits"
            holdout = game_results[game]["holdout"][metric]
            holdout["holm_adjusted_two_sided_p_value"] = adjusted[
                f"{game}:{metric}"
            ]
            holdout["calibration"] = _direction(
                game_results[game]["development"][metric],
                holdout,
            )

    super_result = game_results[SUPER]
    top_10_direction = super_result["holdout"][
        "top_10_hits"
    ]["calibration"]
    contrast_dev = super_result["development"][
        "top_10_minus_next_10_hits"
    ]
    contrast_holdout = super_result["holdout"][
        "top_10_minus_next_10_hits"
    ]
    guarded_supported = (
        top_10_direction == "positive_calibration"
        and contrast_dev["mean_delta"] > 0
        and contrast_holdout["delta_ci_low"] > 0
        and contrast_holdout["first_half_mean_delta"] > 0
        and contrast_holdout["second_half_mean_delta"] > 0
    )
    unconstrained_supported = (
        top_10_direction == "positive_calibration"
    )
    negative_candidate = (
        top_10_direction == "negative_calibration"
    )
    records_after = tree_sha256(base / "records")
    if records_before != records_after:
        raise RuntimeError("辯論排名校準不得改動正式 records")
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
            "AI 辯論支持排名的前 10／20／30 名，是否在封存 holdout "
            "穩定偏離公平標籤零模型，足以支持高 multiplicity 映射？"
        ),
        "protocol": {
            "file": PROTOCOL_FILE,
            "sha256": protocol_hash,
            "cutoffs": list(CUTOFFS),
            "holm_family": [
                f"{game}:top_{cutoff}_hits"
                for game in GAMES
                for cutoff in CUTOFFS
            ],
            "statistical_unit": "one_draw",
            "historical_reuse": (
                "完整歷史已被其他研究使用；任何新方向只能建立未來"
                "不可回填 shadow。"
            ),
        },
        "methodology": {
            "warmup_draws": config.warmup_draws,
            "development_fraction": config.development_fraction,
            "bootstrap_samples": config.bootstrap_samples,
            "bootstrap_block_draws": config.bootstrap_block,
            "exact_null": (
                "每期 Hypergeometric(pool, cutoff, 6)，跨期完整"
                " convolution；六項雙尾 p 使用 Holm 校正。"
            ),
            "no_lookahead": (
                "_support_rows 只接收開獎前 decision；actual numbers "
                "只在完整排名重建後用於評分。"
            ),
        },
        "games": game_results,
        "mapping_decision": {
            "guarded_profit_high_support_mapping_supported": (
                guarded_supported
            ),
            "unconstrained_profit_high_support_mapping_supported": (
                unconstrained_supported
            ),
            "negative_calibration_shadow_candidate": (
                negative_candidate
            ),
            "decision": (
                "retain_high_support_mapping_as_supported_signal"
                if guarded_supported and unconstrained_supported
                else "future_reverse_mapping_shadow_only"
                if negative_candidate
                else "retain_mapping_as_deterministic_tie_break_only"
            ),
            "honesty_note": (
                "未通過校準時，現行映射不改變公平模型的精確結構"
                "機率，但不得宣稱高支持標籤較可能開出。"
            ),
        },
        "records_integrity": {
            "before_sha256": records_before,
            "after_sha256": records_after,
            "unchanged": records_before == records_after,
        },
        "limitations": [
            "完整歷史已被先前研究查看，不是全新的確認性資料。",
            "辯論 support 是決策分數，不是物理開獎機率。",
            "所有合法號碼標籤在公平模型下理論機率相同。",
            "純模擬，不構成購買或下注建議。",
        ],
    }


def write_results(result: dict, output_dir: Path) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "debate_rank_calibration.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return path
