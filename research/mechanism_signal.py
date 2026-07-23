"""開獎機制的號碼、星期、序列與第二區訊號稽核。

外層 development/holdout 之外，development 再切成 inner train/validation。
所有候選先由 inner train 擬合、在 inner validation 決定是否值得帶入外層
holdout；外層 holdout 不得反向改選。完整歷史已被其他研究使用，因此即使
外層結果顯著，也只能建立未來 forward shadow，不能直接宣稱可預測。
"""
from __future__ import annotations

import csv
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
import hashlib
import json
import math
import os
from pathlib import Path
import statistics

from engine.agent_loop import (
    LOOP_EXPERIMENT_ID,
    SELECTED_TICKETS,
    canonical_hash,
    verify_replay,
)
from engine.games import (
    DRAW_WEEKDAYS,
    GAME_NAMES,
    LOTTO649,
    PICK_N,
    POOL,
    SPECIAL_POOL,
    SUPER,
    Draw,
    match_tier,
)
from research.agent_ablation import (
    _validate_event,
    block_bootstrap_ci,
)
from research.gates import tree_sha256
from research.label_signal import (
    _binomial_upper_tail,
    _holm_adjust,
)
from research.max_coverage import (
    select_consensus_disjoint_portfolio,
)
from research.profit_portfolio_forward import (
    COMMON_SPECIAL_CANDIDATE_HASH,
    COMMON_SPECIAL_FITTED_THROUGH,
    COMMON_SPECIAL_SELECTED,
    EMPIRICAL_FLOOR_NTD,
    FIVE_TICKET_COST_NTD,
    GUARDED_PROOF,
    PORTFOLIO_IDS as PROFIT_PORTFOLIO_IDS,
    UNCONSTRAINED_PROOF,
    build_profit_portfolio_shadows,
)
from research.structural_optimum import structural_proof_reference


EXPERIMENT_ID = "draw-mechanism-signal-audit-v1"
SELECTED_MAIN_NUMBERS = SELECTED_TICKETS * PICK_N
MAIN_CANDIDATES = {
    SUPER: (
        "main_frequency",
        "weekday_main_frequency",
    ),
    LOTTO649: (
        "main_frequency",
        "weekday_main_frequency",
        "total_ball_frequency",
    ),
}


@dataclass(frozen=True)
class MechanismSignalConfig:
    warmup_draws: int = 60
    development_fraction: float = 0.70
    inner_training_fraction: float = 0.70
    bootstrap_samples: int = 2_000
    bootstrap_block: int = 13

    def validate(self) -> None:
        if self.warmup_draws < 1:
            raise ValueError("mechanism signal warmup 至少為 1")
        if not 0.5 <= self.development_fraction < 1:
            raise ValueError("development_fraction 必須介於 0.5 與 1")
        if not 0.5 <= self.inner_training_fraction < 1:
            raise ValueError(
                "inner_training_fraction 必須介於 0.5 與 1"
            )
        if self.bootstrap_samples < 100:
            raise ValueError("bootstrap_samples 至少為 100")
        if self.bootstrap_block < 1:
            raise ValueError("bootstrap_block 至少為 1")


def _regularized_gamma_q(a: float, x: float) -> float:
    """Numerical Recipes 的 regularized upper incomplete gamma。"""
    if a <= 0 or x < 0:
        raise ValueError("gamma 參數不合法")
    if x == 0:
        return 1.0
    epsilon = 3e-14
    tiny = 1e-300
    maximum_iterations = 10_000
    log_scale = -x + a * math.log(x) - math.lgamma(a)
    if x < a + 1:
        total = term = 1.0 / a
        ap = a
        for _ in range(maximum_iterations):
            ap += 1
            term *= x / ap
            total += term
            if abs(term) <= abs(total) * epsilon:
                lower = total * math.exp(log_scale)
                return min(1.0, max(0.0, 1.0 - lower))
        raise RuntimeError("gamma series 未收斂")

    b = x + 1 - a
    c = 1 / tiny
    d = 1 / max(b, tiny)
    fraction = d
    for iteration in range(1, maximum_iterations + 1):
        coefficient = -iteration * (iteration - a)
        b += 2
        d = coefficient * d + b
        if abs(d) < tiny:
            d = tiny
        c = b + coefficient / c
        if abs(c) < tiny:
            c = tiny
        d = 1 / d
        delta = d * c
        fraction *= delta
        if abs(delta - 1) <= epsilon:
            return min(
                1.0,
                max(0.0, math.exp(log_scale) * fraction),
            )
    raise RuntimeError("gamma continued fraction 未收斂")


def _chi_square_sf(statistic: float, degrees_of_freedom: int) -> float:
    if statistic < 0 or degrees_of_freedom < 1:
        raise ValueError("chi-square 參數不合法")
    return _regularized_gamma_q(
        degrees_of_freedom / 2,
        statistic / 2,
    )


def _split_profile(
    total_draws: int,
    config: MechanismSignalConfig,
) -> dict:
    eligible = total_draws - config.warmup_draws
    if eligible < 20:
        raise ValueError("mechanism signal 暖機後資料不足")
    development = math.floor(
        eligible * config.development_fraction
    )
    inner_train = math.floor(
        development * config.inner_training_fraction
    )
    inner_validation = development - inner_train
    holdout = eligible - development
    if min(inner_train, inner_validation, holdout) < 5:
        raise ValueError("mechanism signal 時間切分資料不足")
    return {
        "total_draws": total_draws,
        "warmup_draws": config.warmup_draws,
        "eligible_draws": eligible,
        "development_draws": development,
        "inner_training_draws": inner_train,
        "inner_validation_draws": inner_validation,
        "holdout_draws": holdout,
    }


def _reveal(event: dict) -> dict:
    return event["reveal"]


def _main_counts(events: list[dict]) -> Counter:
    return Counter(
        int(number)
        for event in events
        for number in _reveal(event)["numbers"]
    )


def _total_ball_counts(events: list[dict]) -> Counter:
    counts = _main_counts(events)
    counts.update(int(_reveal(event)["special"]) for event in events)
    return counts


def _ordered_numbers(counts: Counter, pool: int) -> tuple[int, ...]:
    return tuple(
        sorted(
            range(1, pool + 1),
            key=lambda number: (-counts[number], number),
        )
    )


def fit_main_model(
    game: str,
    candidate: str,
    training_events: list[dict],
) -> dict:
    """只讀訓練期，產生固定或逐星期的 30 號選擇模型。"""
    if candidate not in MAIN_CANDIDATES[game]:
        raise ValueError(f"{game} 不支援候選 {candidate}")
    pool = POOL[game]
    if candidate == "main_frequency":
        ranking = _ordered_numbers(
            _main_counts(training_events), pool
        )
        return {
            "candidate": candidate,
            "selected_by_weekday": {
                **{
                    str(weekday): list(
                        ranking[:SELECTED_MAIN_NUMBERS]
                    )
                    for weekday in DRAW_WEEKDAYS[game]
                },
                "fallback": list(ranking[:SELECTED_MAIN_NUMBERS]),
            },
        }
    if candidate == "total_ball_frequency":
        if game != LOTTO649:
            raise ValueError("total_ball_frequency 僅適用大樂透")
        ranking = _ordered_numbers(
            _total_ball_counts(training_events), pool
        )
        return {
            "candidate": candidate,
            "selected_by_weekday": {
                **{
                    str(weekday): list(
                        ranking[:SELECTED_MAIN_NUMBERS]
                    )
                    for weekday in DRAW_WEEKDAYS[game]
                },
                "fallback": list(ranking[:SELECTED_MAIN_NUMBERS]),
            },
        }

    selected_by_weekday = {}
    global_ranking = _ordered_numbers(
        _main_counts(training_events), pool
    )
    for weekday in DRAW_WEEKDAYS[game]:
        rows = [
            event
            for event in training_events
            if date.fromisoformat(_reveal(event)["date"]).weekday()
            == weekday
        ]
        if not rows:
            raise ValueError("星期分組沒有訓練資料")
        ranking = _ordered_numbers(_main_counts(rows), pool)
        selected_by_weekday[str(weekday)] = list(
            ranking[:SELECTED_MAIN_NUMBERS]
        )
    selected_by_weekday["fallback"] = list(
        global_ranking[:SELECTED_MAIN_NUMBERS]
    )
    return {
        "candidate": candidate,
        "selected_by_weekday": selected_by_weekday,
    }


def _selected_for_event(model: dict, event: dict) -> set[int]:
    weekday = date.fromisoformat(_reveal(event)["date"]).weekday()
    rows = model["selected_by_weekday"]
    selected = set(
        rows.get(str(weekday), rows.get("fallback", ()))
    )
    if len(selected) != SELECTED_MAIN_NUMBERS:
        raise RuntimeError("mechanism main model 未選出 30 個不同主號")
    return selected


def _main_hits(model: dict, events: list[dict]) -> list[float]:
    return [
        float(
            len(
                _selected_for_event(model, event)
                & set(int(number) for number in _reveal(event)["numbers"])
            )
        )
        for event in events
    ]


@lru_cache(maxsize=8)
def _total_hit_distribution(
    pool: int,
    selected: int,
    drawn: int,
    periods: int,
) -> tuple[float, ...]:
    denominator = math.comb(pool, drawn)
    single = tuple(
        (
            math.comb(selected, hits)
            * math.comb(pool - selected, drawn - hits)
            / denominator
        )
        if 0 <= drawn - hits <= pool - selected
        else 0.0
        for hits in range(drawn + 1)
    )
    distribution = [1.0]
    for _ in range(periods):
        next_distribution = [0.0] * (
            len(distribution) + drawn
        )
        for total, probability in enumerate(distribution):
            for hits, hit_probability in enumerate(single):
                next_distribution[total + hits] += (
                    probability * hit_probability
                )
        distribution = next_distribution
    return tuple(distribution)


def _exact_total_hit_upper_tail(
    game: str,
    periods: int,
    observed: int,
) -> float:
    distribution = _total_hit_distribution(
        POOL[game],
        SELECTED_MAIN_NUMBERS,
        PICK_N,
        periods,
    )
    return min(1.0, math.fsum(distribution[observed:]))


def _candidate_row(
    game: str,
    candidate: str,
    inner_training: list[dict],
    inner_validation: list[dict],
    development: list[dict],
    holdout: list[dict],
    config: MechanismSignalConfig,
) -> tuple[dict, dict]:
    inner_model = fit_main_model(
        game, candidate, inner_training
    )
    inner_hits = _main_hits(inner_model, inner_validation)
    outer_model = fit_main_model(game, candidate, development)
    holdout_hits = _main_hits(outer_model, holdout)
    expected = PICK_N * SELECTED_MAIN_NUMBERS / POOL[game]
    deltas = [value - expected for value in holdout_hits]
    ci = block_bootstrap_ci(
        deltas,
        samples=config.bootstrap_samples,
        block=config.bootstrap_block,
        seed=f"{EXPERIMENT_ID}|{game}|{candidate}|holdout",
    )
    midpoint = len(holdout_hits) // 2
    observed_total = round(sum(holdout_hits))
    row = {
        "game": game,
        "game_name": GAME_NAMES[game],
        "candidate": candidate,
        "inner_validation_draws": len(inner_hits),
        "inner_validation_mean_main_hits": statistics.fmean(
            inner_hits
        ),
        "inner_validation_delta_vs_exact_null": (
            statistics.fmean(inner_hits) - expected
        ),
        "holdout_draws": len(holdout_hits),
        "holdout_observed_total_main_hits": observed_total,
        "holdout_mean_main_hits": statistics.fmean(holdout_hits),
        "exact_null_mean_main_hits": expected,
        "holdout_delta_vs_exact_null": statistics.fmean(deltas),
        "holdout_delta_ci_low": ci[0],
        "holdout_delta_ci_high": ci[1],
        "holdout_first_half_delta": statistics.fmean(
            deltas[:midpoint]
        ),
        "holdout_second_half_delta": statistics.fmean(
            deltas[midpoint:]
        ),
        "holdout_raw_one_sided_p_value": (
            _exact_total_hit_upper_tail(
                game, len(holdout_hits), observed_total
            )
        ),
    }
    return row, outer_model


def _main_uniformity(events: list[dict], game: str) -> dict:
    pool = POOL[game]
    counts = _main_counts(events)
    expected = len(events) * PICK_N / pool
    raw = math.fsum(
        (counts[number] - expected) ** 2 / expected
        for number in range(1, pool + 1)
    )
    corrected = raw * (pool - 1) / (pool - PICK_N)
    return {
        "statistic": corrected,
        "degrees_of_freedom": pool - 1,
        "raw_p_value": _chi_square_sf(corrected, pool - 1),
        "minimum_count": min(
            counts[number] for number in range(1, pool + 1)
        ),
        "maximum_count": max(
            counts[number] for number in range(1, pool + 1)
        ),
        "expected_count": expected,
    }


def _extra_uniformity(events: list[dict], game: str) -> dict:
    pool = SPECIAL_POOL[SUPER] if game == SUPER else POOL[LOTTO649]
    counts = Counter(int(_reveal(event)["special"]) for event in events)
    expected = len(events) / pool
    statistic = math.fsum(
        (counts[number] - expected) ** 2 / expected
        for number in range(1, pool + 1)
    )
    return {
        "statistic": statistic,
        "degrees_of_freedom": pool - 1,
        "raw_p_value": _chi_square_sf(statistic, pool - 1),
        "counts": [counts[number] for number in range(1, pool + 1)],
        "expected_count": expected,
    }


def _weekday_main_difference(events: list[dict], game: str) -> dict:
    weekdays = DRAW_WEEKDAYS[game]
    groups = [
        [
            event
            for event in events
            if date.fromisoformat(_reveal(event)["date"]).weekday()
            == weekday
        ]
        for weekday in weekdays
    ]
    if any(not group for group in groups):
        raise ValueError("星期效果檢定缺少分組")
    counts = [_main_counts(group) for group in groups]
    pool = POOL[game]
    base_probability = PICK_N / pool
    scale = (
        base_probability
        * (1 - base_probability)
        * pool
        / (pool - 1)
        * (1 / len(groups[0]) + 1 / len(groups[1]))
    )
    statistic = math.fsum(
        (
            counts[0][number] / len(groups[0])
            - counts[1][number] / len(groups[1])
        )
        ** 2
        / scale
        for number in range(1, pool + 1)
    )
    return {
        "statistic": statistic,
        "degrees_of_freedom": pool - 1,
        "raw_p_value": _chi_square_sf(statistic, pool - 1),
        "weekday_draws": {
            str(weekday): len(group)
            for weekday, group in zip(weekdays, groups)
        },
    }


def _serial_overlap(events: list[dict], game: str) -> dict:
    overlaps = [
        len(
            set(_reveal(previous)["numbers"])
            & set(_reveal(current)["numbers"])
        )
        for previous, current in zip(events, events[1:])
    ]
    pool = POOL[game]
    expected = PICK_N * PICK_N / pool
    variance = (
        PICK_N
        * (PICK_N / pool)
        * (1 - PICK_N / pool)
        * ((pool - PICK_N) / (pool - 1))
    )
    mean = statistics.fmean(overlaps)
    z_score = (mean - expected) / math.sqrt(
        variance / len(overlaps)
    )
    return {
        "pairs": len(overlaps),
        "observed_mean_overlap": mean,
        "exact_null_mean_overlap": expected,
        "z_score": z_score,
        "raw_p_value": math.erfc(abs(z_score) / math.sqrt(2)),
    }


def _residual_correlation(
    development: list[dict],
    holdout: list[dict],
    game: str,
) -> dict:
    pool = POOL[game]
    development_counts = _main_counts(development)
    holdout_counts = _main_counts(holdout)
    left = [
        development_counts[number]
        - len(development) * PICK_N / pool
        for number in range(1, pool + 1)
    ]
    right = [
        holdout_counts[number] - len(holdout) * PICK_N / pool
        for number in range(1, pool + 1)
    ]
    # statistics.correlation 是 3.10+；此環境以 3.9 為準，手算 Pearson（fsum 保決定性）
    pool_n = len(left)
    mean_left = math.fsum(left) / pool_n
    mean_right = math.fsum(right) / pool_n
    cov = math.fsum((a - mean_left) * (b - mean_right) for a, b in zip(left, right))
    var_left = math.fsum((a - mean_left) ** 2 for a in left)
    var_right = math.fsum((b - mean_right) ** 2 for b in right)
    correlation = cov / math.sqrt(var_left * var_right)
    clipped = min(0.999999999, max(-0.999999999, correlation))
    z_score = math.atanh(clipped) * math.sqrt(pool - 3)
    return {
        "correlation": correlation,
        "fisher_z": z_score,
        "raw_p_value": math.erfc(abs(z_score) / math.sqrt(2)),
    }


def _winning_any_prize(
    game: str,
    tickets: list[dict],
    reveal: dict,
) -> int:
    drawn = set(int(number) for number in reveal["numbers"])
    bonus = int(reveal["special"])
    for ticket in tickets:
        hits = len(set(ticket["numbers"]) & drawn)
        if game == SUPER:
            won = hits >= 3 or (
                hits in (1, 2) and ticket["special"] == bonus
            )
        else:
            won = hits >= 3 or (
                hits == 2 and bonus in set(ticket["numbers"])
            )
        if won:
            return 1
    return 0


def historical_special_portfolio(
    decision: dict,
    ordered_specials: tuple[int, ...] | list[int],
) -> list[dict]:
    """保留 30 主號與分組，只替換五個互異第二區。"""
    specials = tuple(int(value) for value in ordered_specials)
    if (
        len(specials) != SELECTED_TICKETS
        or len(set(specials)) != SELECTED_TICKETS
        or any(not 1 <= value <= SPECIAL_POOL[SUPER] for value in specials)
    ):
        raise ValueError("歷史第二區候選必須是五個互異合法號碼")
    tickets, metadata = select_consensus_disjoint_portfolio(
        SUPER, decision
    )
    bin_order = sorted(
        range(SELECTED_TICKETS),
        key=lambda index: (
            -metadata["ticket_debate_support"][index],
            index,
        ),
    )
    special_by_bin = {
        bin_index: specials[rank]
        for rank, bin_index in enumerate(bin_order)
    }
    return [
        {**ticket, "special": special_by_bin[index]}
        for index, ticket in enumerate(tickets)
    ]


def _floor_profit_result(
    tickets: list[dict],
    reveal: dict,
) -> dict:
    draw = Draw(
        game=SUPER,
        period=int(reveal["period"]),
        date=str(reveal["date"]),
        numbers=tuple(int(value) for value in reveal["numbers"]),
        special=int(reveal["special"]),
    )
    payout = 0
    for ticket in tickets:
        tier = match_tier(
            SUPER,
            ticket["numbers"],
            ticket["special"],
            draw,
        )
        if tier is not None:
            payout += EMPIRICAL_FLOOR_NTD[tier.api_key]
    return {
        "empirical_floor_stress_payout_ntd": payout,
        "empirical_floor_stress_net_ntd": (
            payout - FIVE_TICKET_COST_NTD
        ),
        "empirical_floor_stress_strict_profit": (
            payout > FIVE_TICKET_COST_NTD
        ),
    }


def _profit_common_special_comparison(
    events: list[dict],
    selected_special: int,
    *,
    config: MechanismSignalConfig,
    split: str,
) -> dict:
    if not 1 <= selected_special <= SPECIAL_POOL[SUPER]:
        raise ValueError("共同第二區候選不合法")
    values = {
        portfolio_id: {
            "strict_profit_deltas": [],
            "net_deltas_ntd": [],
            "candidate_strict_profit": [],
            "control_strict_profit": [],
        }
        for portfolio_id in PROFIT_PORTFOLIO_IDS
    }
    for event in events:
        decision = event["decision"]
        coverage_tickets, selection = (
            select_consensus_disjoint_portfolio(SUPER, decision)
        )
        top_ticket_index = min(
            range(SELECTED_TICKETS),
            key=lambda index: (
                -float(
                    selection["ticket_debate_support"][index]
                ),
                index,
            ),
        )
        baseline_special = coverage_tickets[top_ticket_index][
            "special"
        ]
        baseline_shadow = build_profit_portfolio_shadows(
            source_decision_hash=decision["decision_hash"],
            support_evidence_hash=selection[
                "support_evidence_hash"
            ],
            ranked_main_numbers=selection[
                "selected_main_numbers"
            ],
            selected_special=baseline_special,
        )
        for portfolio_id in PROFIT_PORTFOLIO_IDS:
            baseline_tickets = baseline_shadow["portfolios"][
                portfolio_id
            ]["tickets"]
            candidate_tickets = [
                {**ticket, "special": selected_special}
                for ticket in baseline_tickets
            ]
            control = _floor_profit_result(
                baseline_tickets, event["reveal"]
            )
            candidate = _floor_profit_result(
                candidate_tickets, event["reveal"]
            )
            row = values[portfolio_id]
            candidate_profit = int(
                candidate[
                    "empirical_floor_stress_strict_profit"
                ]
            )
            control_profit = int(
                control["empirical_floor_stress_strict_profit"]
            )
            row["strict_profit_deltas"].append(
                candidate_profit - control_profit
            )
            row["net_deltas_ntd"].append(
                candidate["empirical_floor_stress_net_ntd"]
                - control["empirical_floor_stress_net_ntd"]
            )
            row["candidate_strict_profit"].append(candidate_profit)
            row["control_strict_profit"].append(control_profit)

    midpoint = len(events) // 2
    result = {}
    for portfolio_id, row in values.items():
        deltas = row["strict_profit_deltas"]
        ci_low, ci_high = block_bootstrap_ci(
            deltas,
            samples=config.bootstrap_samples,
            block=config.bootstrap_block,
            seed=(
                f"{EXPERIMENT_ID}|super|profit-common-special|"
                f"{split}|{portfolio_id}"
            ),
        )
        result[portfolio_id] = {
            "draws": len(events),
            "candidate_strict_profit_rate": statistics.fmean(
                row["candidate_strict_profit"]
            ),
            "control_strict_profit_rate": statistics.fmean(
                row["control_strict_profit"]
            ),
            "strict_profit_delta": statistics.fmean(deltas),
            "strict_profit_delta_ci_low": ci_low,
            "strict_profit_delta_ci_high": ci_high,
            "first_half_strict_profit_delta": statistics.fmean(
                deltas[:midpoint]
            ),
            "second_half_strict_profit_delta": statistics.fmean(
                deltas[midpoint:]
            ),
            "candidate_wins": sum(value > 0 for value in deltas),
            "ties": sum(value == 0 for value in deltas),
            "control_wins": sum(value < 0 for value in deltas),
            "mean_net_delta_ntd": statistics.fmean(
                row["net_deltas_ntd"]
            ),
        }
    return result


def _special_candidate(
    inner_training: list[dict],
    inner_validation: list[dict],
    development: list[dict],
    holdout: list[dict],
    config: MechanismSignalConfig,
) -> dict:
    def ranking(events: list[dict]) -> tuple[int, ...]:
        counts = Counter(
            int(_reveal(event)["special"]) for event in events
        )
        return tuple(
            sorted(
                range(1, SPECIAL_POOL[SUPER] + 1),
                key=lambda value: (-counts[value], value),
            )
        )

    inner_ranking = ranking(inner_training)
    inner_selected = set(inner_ranking[:SELECTED_TICKETS])
    inner_hits = [
        int(int(_reveal(event)["special"]) in inner_selected)
        for event in inner_validation
    ]
    outer_ranking = ranking(development)
    ordered_specials = outer_ranking[:SELECTED_TICKETS]
    selected = set(ordered_specials)
    special_hits = [
        int(int(_reveal(event)["special"]) in selected)
        for event in holdout
    ]
    inner_top_one = int(inner_ranking[0])
    inner_top_one_hits = [
        int(int(_reveal(event)["special"]) == inner_top_one)
        for event in inner_validation
    ]
    outer_top_one = int(outer_ranking[0])
    outer_top_one_hits = [
        int(int(_reveal(event)["special"]) == outer_top_one)
        for event in holdout
    ]
    inner_profit_common_special = (
        _profit_common_special_comparison(
            inner_validation,
            inner_top_one,
            config=config,
            split="inner-validation",
        )
    )
    holdout_profit_common_special = (
        _profit_common_special_comparison(
            holdout,
            outer_top_one,
            config=config,
            split="holdout",
        )
    )
    paired_any_prize = []
    candidate_wins = []
    control_wins = []
    for event in holdout:
        control, _ = select_consensus_disjoint_portfolio(
            SUPER, event["decision"]
        )
        candidate = historical_special_portfolio(
            event["decision"], ordered_specials
        )
        reveal = _reveal(event)
        control_win = _winning_any_prize(
            SUPER, control, reveal
        )
        candidate_win = _winning_any_prize(
            SUPER, candidate, reveal
        )
        control_wins.append(control_win)
        candidate_wins.append(candidate_win)
        paired_any_prize.append(candidate_win - control_win)
    ci = block_bootstrap_ci(
        paired_any_prize,
        samples=config.bootstrap_samples,
        block=config.bootstrap_block,
        seed=f"{EXPERIMENT_ID}|super|special-top-five|holdout",
    )
    midpoint = len(holdout) // 2
    return {
        "candidate": "development_top_five_specials",
        "inner_training_ranking": list(inner_ranking),
        "inner_selected_specials": list(inner_ranking[:5]),
        "inner_validation_draws": len(inner_validation),
        "inner_validation_special_coverage": statistics.fmean(
            inner_hits
        ),
        "inner_validation_delta_vs_exact_null": (
            statistics.fmean(inner_hits)
            - SELECTED_TICKETS / SPECIAL_POOL[SUPER]
        ),
        "development_ranking": list(outer_ranking),
        "selected_specials": list(ordered_specials),
        "holdout_draws": len(holdout),
        "holdout_special_hits": sum(special_hits),
        "holdout_special_coverage": statistics.fmean(special_hits),
        "exact_null_special_coverage": (
            SELECTED_TICKETS / SPECIAL_POOL[SUPER]
        ),
        "holdout_special_coverage_raw_one_sided_p_value": (
            _binomial_upper_tail(
                len(holdout),
                sum(special_hits),
                SELECTED_TICKETS / SPECIAL_POOL[SUPER],
            )
        ),
        "holdout_first_half_special_coverage": statistics.fmean(
            special_hits[:midpoint]
        ),
        "holdout_second_half_special_coverage": statistics.fmean(
            special_hits[midpoint:]
        ),
        "control_any_prize_rate": statistics.fmean(control_wins),
        "candidate_any_prize_rate": statistics.fmean(
            candidate_wins
        ),
        "paired_any_prize_delta": statistics.fmean(
            paired_any_prize
        ),
        "paired_any_prize_ci_low": ci[0],
        "paired_any_prize_ci_high": ci[1],
        "theoretical_structural_probability_unchanged": True,
        "profit_common_special_candidate": {
            "candidate": "development_top_one_special",
            "inner_selected_special": inner_top_one,
            "inner_validation_draws": len(inner_validation),
            "inner_validation_special_hits": sum(
                inner_top_one_hits
            ),
            "inner_validation_special_rate": statistics.fmean(
                inner_top_one_hits
            ),
            "inner_validation_delta_vs_exact_null": (
                statistics.fmean(inner_top_one_hits)
                - 1 / SPECIAL_POOL[SUPER]
            ),
            "inner_validation_portfolios": (
                inner_profit_common_special
            ),
            "selected_special": outer_top_one,
            "holdout_draws": len(holdout),
            "holdout_special_hits": sum(outer_top_one_hits),
            "holdout_special_rate": statistics.fmean(
                outer_top_one_hits
            ),
            "exact_null_special_rate": 1 / SPECIAL_POOL[SUPER],
            "holdout_raw_one_sided_p_value": (
                _binomial_upper_tail(
                    len(holdout),
                    sum(outer_top_one_hits),
                    1 / SPECIAL_POOL[SUPER],
                )
            ),
            "holdout_first_half_special_rate": statistics.fmean(
                outer_top_one_hits[:midpoint]
            ),
            "holdout_second_half_special_rate": statistics.fmean(
                outer_top_one_hits[midpoint:]
            ),
            "holdout_portfolios": holdout_profit_common_special,
            "theoretical_structural_probability_unchanged": True,
        },
    }


def _profile_events(game: str, events: list[dict]) -> dict:
    dates = [_reveal(event)["date"] for event in events]
    periods = [int(_reveal(event)["period"]) for event in events]
    valid = all(
        len(_reveal(event)["numbers"]) == PICK_N
        and len(set(_reveal(event)["numbers"])) == PICK_N
        and all(
            1 <= int(number) <= POOL[game]
            for number in _reveal(event)["numbers"]
        )
        and (
            1
            <= int(_reveal(event)["special"])
            <= (
                SPECIAL_POOL[SUPER]
                if game == SUPER
                else POOL[LOTTO649]
            )
        )
        and (
            game == SUPER
            or int(_reveal(event)["special"])
            not in set(_reveal(event)["numbers"])
        )
        for event in events
    )
    off_schedule_draws = sum(
        date.fromisoformat(value).weekday()
        not in DRAW_WEEKDAYS[game]
        for value in dates
    )
    canonical = [
        {
            "period": int(_reveal(event)["period"]),
            "date": _reveal(event)["date"],
            "numbers": list(_reveal(event)["numbers"]),
            "special": int(_reveal(event)["special"]),
        }
        for event in events
    ]
    failures = []
    if len(dates) != len(set(dates)):
        failures.append("duplicate_dates")
    if len(periods) != len(set(periods)):
        failures.append("duplicate_periods")
    if dates != sorted(dates):
        failures.append("not_chronological")
    if not valid:
        failures.append("invalid_draw")
    return {
        "draws": len(events),
        "first_date": dates[0],
        "last_date": dates[-1],
        "duplicate_dates": len(dates) - len(set(dates)),
        "duplicate_periods": len(periods) - len(set(periods)),
        "ordered_chronologically": dates == sorted(dates),
        "legal_draws": valid,
        "regular_schedule_draws": len(events) - off_schedule_draws,
        "off_schedule_draws": off_schedule_draws,
        "off_schedule_treatment": (
            "weekday candidate 使用全訓練期 fallback；大樂透春節"
            "加開屬合法資料，不視為品質失敗。"
        ),
        "dataset_sha256": hashlib.sha256(
            json.dumps(
                canonical,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        "quality_status": "pass" if not failures else "fail",
        "quality_failures": failures,
    }


def run_mechanism_signal_study(
    ledger_paths: dict[str, Path],
    *,
    base: Path,
    config: MechanismSignalConfig | None = None,
    verify_ledgers: bool = True,
) -> dict:
    config = config or MechanismSignalConfig()
    config.validate()
    base = Path(base)
    records_before = tree_sha256(base / "records")
    profiles = {}
    verifications = {}
    splits = {}
    source_last_dates = {}
    candidate_rows = []
    candidate_models = {}
    diagnostics = {}
    diagnostic_raw = {}
    events_by_game = {}

    for game in (SUPER, LOTTO649):
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
        verifications[game] = verification
        events = []
        with path.open(encoding="utf-8") as handle:
            for sequence, line in enumerate(handle, 1):
                event = json.loads(line)
                _validate_event(event, game, sequence)
                events.append(event)
        events_by_game[game] = events
        profile = _profile_events(game, events)
        profiles[game] = profile
        if profile["quality_status"] != "pass":
            raise RuntimeError(f"{game} mechanism data quality 失敗")
        source_last_dates[game] = profile["last_date"]
        split = _split_profile(len(events), config)
        splits[game] = split
        eligible = events[config.warmup_draws :]
        development = eligible[: split["development_draws"]]
        holdout = eligible[split["development_draws"] :]
        inner_training = development[
            : split["inner_training_draws"]
        ]
        inner_validation = development[
            split["inner_training_draws"] :
        ]

        game_rows = []
        for candidate in MAIN_CANDIDATES[game]:
            row, model = _candidate_row(
                game,
                candidate,
                inner_training,
                inner_validation,
                development,
                holdout,
                config,
            )
            game_rows.append(row)
            candidate_rows.append(row)
            candidate_models[(game, candidate)] = model
        expected = PICK_N * SELECTED_MAIN_NUMBERS / POOL[game]
        eligible_rows = [
            row
            for row in game_rows
            if row["inner_validation_mean_main_hits"] > expected
        ]
        selected = (
            max(
                eligible_rows,
                key=lambda row: (
                    row["inner_validation_delta_vs_exact_null"],
                    row["candidate"],
                ),
            )["candidate"]
            if eligible_rows
            else "uniform_null"
        )

        holdout_diagnostics = {
            "main_label_uniformity": _main_uniformity(
                holdout, game
            ),
            "extra_number_uniformity": _extra_uniformity(
                holdout, game
            ),
            "weekday_main_difference": _weekday_main_difference(
                holdout, game
            ),
            "serial_main_overlap": _serial_overlap(holdout, game),
        }
        diagnostics[game] = {
            "development": {
                "main_label_uniformity": _main_uniformity(
                    development, game
                ),
                "extra_number_uniformity": _extra_uniformity(
                    development, game
                ),
                "weekday_main_difference": (
                    _weekday_main_difference(development, game)
                ),
                "serial_main_overlap": _serial_overlap(
                    development, game
                ),
            },
            "holdout": holdout_diagnostics,
            "development_holdout_main_residual_correlation": (
                _residual_correlation(
                    development, holdout, game
                )
            ),
            "development_selected_main_candidate": selected,
        }
        for name, row in holdout_diagnostics.items():
            diagnostic_raw[f"{game}:{name}"] = row["raw_p_value"]

    special = _special_candidate(
        events_by_game[SUPER][
            config.warmup_draws :
            config.warmup_draws
            + splits[SUPER]["inner_training_draws"]
        ],
        events_by_game[SUPER][
            config.warmup_draws
            + splits[SUPER]["inner_training_draws"] :
            config.warmup_draws
            + splits[SUPER]["development_draws"]
        ],
        events_by_game[SUPER][
            config.warmup_draws :
            config.warmup_draws
            + splits[SUPER]["development_draws"]
        ],
        events_by_game[SUPER][
            config.warmup_draws
            + splits[SUPER]["development_draws"] :
        ],
        config,
    )

    strategy_raw = {
        f"{row['game']}:{row['candidate']}": row[
            "holdout_raw_one_sided_p_value"
        ]
        for row in candidate_rows
    }
    strategy_raw["super:development_top_five_specials"] = special[
        "holdout_special_coverage_raw_one_sided_p_value"
    ]
    common_special = special["profit_common_special_candidate"]
    strategy_raw["super:development_top_one_special"] = (
        common_special["holdout_raw_one_sided_p_value"]
    )
    strategy_adjusted = _holm_adjust(strategy_raw)
    for row in candidate_rows:
        key = f"{row['game']}:{row['candidate']}"
        row["holm_adjusted_one_sided_p_value"] = (
            strategy_adjusted[key]
        )
    special["holm_adjusted_special_coverage_p_value"] = (
        strategy_adjusted[
            "super:development_top_five_specials"
        ]
    )
    common_special["holm_adjusted_one_sided_p_value"] = (
        strategy_adjusted[
            "super:development_top_one_special"
        ]
    )
    diagnostic_adjusted = _holm_adjust(diagnostic_raw)
    for game in (SUPER, LOTTO649):
        for name, row in diagnostics[game]["holdout"].items():
            row["holm_adjusted_p_value"] = diagnostic_adjusted[
                f"{game}:{name}"
            ]

    main_decisions = {}
    for game in (SUPER, LOTTO649):
        selected = diagnostics[game][
            "development_selected_main_candidate"
        ]
        selected_row = next(
            (
                row
                for row in candidate_rows
                if row["game"] == game
                and row["candidate"] == selected
            ),
            None,
        )
        eligible = bool(
            selected_row
            and selected_row["holm_adjusted_one_sided_p_value"]
            < 0.05
            and selected_row["holdout_delta_ci_low"] > 0
            and selected_row["holdout_first_half_delta"] > 0
            and selected_row["holdout_second_half_delta"] > 0
        )
        main_decisions[game] = {
            "development_selected_candidate": selected,
            "promotion_eligible": eligible,
            "decision": (
                f"promote_{selected}"
                if eligible
                else "retain_consensus_main_labels"
            ),
        }

    special_eligible = (
        special["inner_validation_delta_vs_exact_null"] > 0
        and special["holm_adjusted_special_coverage_p_value"] < 0.05
        and special["paired_any_prize_ci_low"] > 0
        and special["holdout_first_half_special_coverage"]
        > special["exact_null_special_coverage"]
        and special["holdout_second_half_special_coverage"]
        > special["exact_null_special_coverage"]
    )
    special["promotion_eligible"] = special_eligible
    special["decision"] = (
        "promote_historical_specials"
        if special_eligible
        else "retain_consensus_special_ranking"
    )
    common_special_eligible = (
        common_special["inner_validation_delta_vs_exact_null"] > 0
        and common_special["holm_adjusted_one_sided_p_value"] < 0.05
        and common_special["holdout_first_half_special_rate"]
        > common_special["exact_null_special_rate"]
        and common_special["holdout_second_half_special_rate"]
        > common_special["exact_null_special_rate"]
        and all(
            row["strict_profit_delta_ci_low"] > 0
            and row["first_half_strict_profit_delta"] >= 0
            and row["second_half_strict_profit_delta"] >= 0
            and row["mean_net_delta_ntd"] >= 0
            for row in common_special[
                "holdout_portfolios"
            ].values()
        )
    )
    common_special["promotion_eligible"] = (
        common_special_eligible
    )
    common_special["decision"] = (
        "promote_profit_common_special"
        if common_special_eligible
        else "retain_consensus_profit_common_special"
    )
    candidate_payload = {
        "experiment_id": "special-frequency-forward-shadow-v1",
        "source_experiment_id": EXPERIMENT_ID,
        "game": SUPER,
        "fitted_through": (
            events_by_game[SUPER][
                config.warmup_draws
                + splits[SUPER]["development_draws"]
                - 1
            ]["reveal"]["date"]
        ),
        "selected_specials": special["selected_specials"],
        "assignment": (
            "依 ticket_debate_support 由高至低配對 development "
            "第二區頻率排序"
        ),
        "promotion_eligible": False,
        "use": "future_forward_shadow_only",
        "structural_optimum_proof": structural_proof_reference(),
    }
    forward_candidate = {
        **candidate_payload,
        "candidate_hash": canonical_hash(candidate_payload),
    }
    common_special_candidate_payload = {
        "experiment_id": "profit-common-special-forward-shadow-v1",
        "source_experiment_id": EXPERIMENT_ID,
        "game": SUPER,
        "fitted_through": COMMON_SPECIAL_FITTED_THROUGH,
        "selected_special": COMMON_SPECIAL_SELECTED,
        "source_candidate": common_special["candidate"],
        "promotion_eligible": False,
        "use": "future_forward_shadow_only",
        "guarded_profit_proof": deepcopy(GUARDED_PROOF),
        "unconstrained_profit_proof": deepcopy(
            UNCONSTRAINED_PROOF
        ),
    }
    profit_common_special_forward_candidate = None
    if source_last_dates[SUPER] >= COMMON_SPECIAL_FITTED_THROUGH:
        candidate_hash = canonical_hash(
            common_special_candidate_payload
        )
        if candidate_hash != COMMON_SPECIAL_CANDIDATE_HASH:
            raise RuntimeError("共同第二區 v1 凍結候選 hash 漂移")
        profit_common_special_forward_candidate = {
            **common_special_candidate_payload,
            "candidate_hash": candidate_hash,
        }

    records_after = tree_sha256(base / "records")
    if records_before != records_after:
        raise RuntimeError("mechanism signal 研究不應改動正式 records")
    any_promotion = any(
        row["promotion_eligible"] for row in main_decisions.values()
    ) or special_eligible or common_special_eligible
    return {
        "schema_version": "1",
        "experiment_id": EXPERIMENT_ID,
        "source_experiment_id": LOOP_EXPERIMENT_ID,
        "generated_at": max(source_last_dates.values())
        + "T23:59:59+08:00",
        "question": (
            "歷史開獎是否存在跨時間可重現的主號標籤、星期、序列"
            "或第二區偏差，足以在完全分散結構內改變號碼排序？"
        ),
        "methodology": {
            "warmup_draws": config.warmup_draws,
            "development_fraction": config.development_fraction,
            "inner_training_fraction": config.inner_training_fraction,
            "bootstrap_samples": config.bootstrap_samples,
            "bootstrap_block_draws": config.bootstrap_block,
            "main_candidates": {
                game: list(candidates)
                for game, candidates in MAIN_CANDIDATES.items()
            },
            "nested_selection": (
                "inner train 擬合、inner validation 選唯一候選；"
                "外層 holdout 不得改選。"
            ),
            "multiple_testing": (
                "五個主號候選、威力彩前五第二區與共同第二區"
                "各一項，共七項，"
                "使用 Holm family-wise correction；四類機制診斷"
                "跨兩款遊戲另成八項 Holm family。"
            ),
            "promotion_gate": (
                "inner validation 正向、Holm p<0.05、holdout "
                "13 期區塊 bootstrap 下界>0、前後半皆正向；"
                "前五第二區另要求配對任一獎差區間下界>0；"
                "共同第二區另要求兩個獲利結構的配對嚴格獲利"
                "區間下界皆>0且平均壓力淨額不下降。"
            ),
            "historical_reuse": (
                "完整歷史先前已被其他研究檢視；外層 holdout 僅為"
                "嚴格探索證據，任何新候選仍需未來 forward 確認。"
            ),
            "structural_optimum_proof": structural_proof_reference(),
        },
        "data_quality": {
            "status": (
                "pass"
                if all(
                    profile["quality_status"] == "pass"
                    for profile in profiles.values()
                )
                else "fail"
            ),
            "profiles": profiles,
            "ledger_verification": verifications,
            "split_profiles": splits,
            "source_last_dates": source_last_dates,
        },
        "mechanism_diagnostics": diagnostics,
        "main_candidate_holdout": candidate_rows,
        "main_decisions": main_decisions,
        "super_special_candidate": special,
        "future_forward_shadow_candidate": forward_candidate,
        "future_profit_common_special_shadow_candidate": (
            profit_common_special_forward_candidate
        ),
        "conclusion": {
            "status": (
                "eligible_for_mechanism_upgrade"
                if any_promotion
                else "retain_current_label_and_special_ranking"
            ),
            "any_historical_promotion_eligible": any_promotion,
            "important_exploratory_result": (
                "威力彩 development 前五第二區在外層 holdout 的"
                "覆蓋率高於 5/8；共同第二區在兩個獲利結構的"
                "外層 holdout 嚴格獲利差皆為正。但兩者的 inner "
                "validation 均未重現，七項 Holm 校正與配對區間"
                "也未通過升級門檻。"
            ),
            "forward_action": (
                "前五 coverage 第二區與共同獲利第二區都只凍結為"
                "未來 forward shadow 候選；不替換現行 Agent "
                "共識第二區，不改既有登記。"
            ),
        },
        "records_integrity": {
            "before_sha256": records_before,
            "after_sha256": records_after,
            "unchanged": records_before == records_after,
        },
        "limitations": [
            "所有歷史期數已被多個研究使用，不是全新的確認性樣本。",
            "漸近卡方與 Fisher z 只作機制診斷；策略門檻另用精確尾端與區塊 bootstrap。",
            "候選標籤不改變公平模型下的精確結構機率。",
            "純模擬，不構成購買或下注建議。",
        ],
    }


def write_results(result: dict, output_dir: Path) -> dict[str, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "json": output_dir / "mechanism_signal.json",
        "candidates": output_dir / "mechanism_signal_candidates.csv",
    }
    temporary = paths["json"].with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, paths["json"])
    rows = result["main_candidate_holdout"]
    with paths["candidates"].open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return paths
