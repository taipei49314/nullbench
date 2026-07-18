"""全歷史走步回測與封存外驗。

研究紀律：

* 每一週只能看該週週一以前的開獎資料。
* 粗搜尋與細調只看 training。
* 投資組合只用 validation 選一次。
* holdout 只在最終決策時開封，不再用來調參。
* v1 正式帳本與凍結票完全不在本模組的寫入範圍。

回測仍是負期望值的純模擬。研究同時回答兩個不同問題：

1. 經濟決策：參與或不參與。
2. 條件式研究：如果固定模擬 5 注，哪個政策在未見資料最穩健。
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import random
import statistics
import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

from engine.games import (
    GAME_NAMES,
    LOTTO649,
    POOL,
    SPECIAL_POOL,
    SUPER,
    TICKET_PRICE,
    TIERS,
    Draw,
    match_tier,
    prize_value,
    validate_pick,
)
from engine.picker import GAMES
from engine.stats import gaps, special_gaps
from engine.store import week_id_of
from research.gates import (
    build_data_quality_gate,
    build_strategy_search_gate,
    require_gate,
)


RESEARCH_ID = "walkforward-v1"
SPLITS = ("train", "validation", "holdout")


def _stable_int(text: str) -> int:
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:16], 16)


def _median(values: Iterable[float]) -> float:
    values = list(values)
    return statistics.median(values) if values else 0.0


def _mean(values: Iterable[float]) -> float:
    values = list(values)
    return statistics.fmean(values) if values else 0.0


def _quantile(values: Iterable[float], q: float) -> float:
    xs = sorted(values)
    if not xs:
        return 0.0
    if len(xs) == 1:
        return float(xs[0])
    pos = (len(xs) - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return float(xs[lo])
    frac = pos - lo
    return float(xs[lo] * (1 - frac) + xs[hi] * frac)


@dataclass(frozen=True)
class Candidate:
    """單一選號人格與一組固定參數。"""

    candidate_id: str
    family: str
    params: tuple[tuple[str, float | int], ...] = ()

    def get(self, name: str, default=None):
        return dict(self.params).get(name, default)

    def as_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "family": self.family,
            "params": dict(self.params),
        }


@dataclass(frozen=True)
class Policy:
    """每週 5 個模擬席位的固定組合。"""

    policy_id: str
    slots: tuple[Candidate, ...]

    def __post_init__(self):
        if len(self.slots) != 5:
            raise ValueError("每個研究政策必須恰好有 5 個席位")

    def as_dict(self) -> dict:
        return {
            "policy_id": self.policy_id,
            "slots": [c.as_dict() for c in self.slots],
        }


@dataclass(frozen=True)
class WeekContext:
    game: str
    week: str
    split: str
    history: tuple[Draw, ...]
    draws: tuple[Draw, ...]
    floor_table: dict[str, int]
    main_gaps: dict[int, int]
    special_gap_map: dict[int, int]


@dataclass(frozen=True)
class WeekResult:
    game: str
    week: str
    split: str
    policy_id: str
    replicate: int
    draws: int
    cost: int
    raw_prize: int
    robust_prize: int
    fixed_prize: int
    hits: int
    top2_hits: int

    @property
    def raw_pnl(self) -> int:
        return self.raw_prize - self.cost

    @property
    def robust_pnl(self) -> int:
        return self.robust_prize - self.cost


def candidate(
    candidate_id: str,
    family: str,
    **params: float | int,
) -> Candidate:
    return Candidate(candidate_id, family, tuple(sorted(params.items())))


UNIFORM = candidate("uniform", "uniform")
CURRENT = {
    "uniform": UNIFORM,
    "hot": candidate("hot_w50_d097", "hot", window=50, decay=0.97),
    "cold": candidate("cold_g150_c4", "cold", gamma=1.5, cap_mult=4),
    "balance": candidate(
        "balance_standard",
        "balance",
        sum_pad=0,
        odd_lo=2,
        odd_hi=4,
        max_pairs=1,
        min_tails=4,
        min_range=15,
    ),
    "antipop": candidate(
        "antipop_m060_d075", "antipop", beta_month=0.60, beta_day=0.75
    ),
}


def coarse_candidates() -> list[Candidate]:
    """第一輪候選；只允許 training 決定後續細調中心。"""
    out = [UNIFORM]
    for window in (20, 50, 100):
        for decay in (0.94, 0.97, 0.99):
            out.append(
                candidate(
                    f"hot_w{window}_d{int(round(decay * 100)):03d}",
                    "hot",
                    window=window,
                    decay=decay,
                )
            )
    for gamma in (0.75, 1.5, 2.25):
        for cap_mult in (2, 4, 8):
            out.append(
                candidate(
                    f"cold_g{int(round(gamma * 100)):03d}_c{cap_mult}",
                    "cold",
                    gamma=gamma,
                    cap_mult=cap_mult,
                )
            )
    out.extend(
        [
            candidate(
                "balance_loose",
                "balance",
                sum_pad=15,
                odd_lo=1,
                odd_hi=5,
                max_pairs=2,
                min_tails=3,
                min_range=10,
            ),
            CURRENT["balance"],
            candidate(
                "balance_tight",
                "balance",
                sum_pad=-5,
                odd_lo=2,
                odd_hi=4,
                max_pairs=0,
                min_tails=5,
                min_range=20,
            ),
        ]
    )
    for beta_month in (0.35, 0.60, 0.85):
        for beta_day in (0.55, 0.75, 0.90):
            out.append(
                candidate(
                    f"antipop_m{int(round(beta_month * 100)):03d}"
                    f"_d{int(round(beta_day * 100)):03d}",
                    "antipop",
                    beta_month=beta_month,
                    beta_day=beta_day,
                )
            )
    ids = [c.candidate_id for c in out]
    if len(ids) != len(set(ids)):
        raise AssertionError("候選 ID 重複")
    return out


def _float_token(value: float) -> str:
    return f"{int(round(value * 100)):03d}"


def refine_candidates(winners: dict[str, Candidate]) -> list[Candidate]:
    """只沿 training 粗搜尋冠軍附近做第二輪細調。"""
    out: list[Candidate] = [UNIFORM]
    hot = winners["hot"]
    for window in sorted(
        {
            max(10, int(hot.get("window")) - 20),
            max(10, int(hot.get("window")) - 10),
            int(hot.get("window")),
            int(hot.get("window")) + 10,
            int(hot.get("window")) + 20,
        }
    ):
        for decay in sorted(
            {
                max(0.85, round(float(hot.get("decay")) - 0.01, 3)),
                round(float(hot.get("decay")), 3),
                min(0.999, round(float(hot.get("decay")) + 0.01, 3)),
            }
        ):
            out.append(
                candidate(
                    f"hot_ref_w{window}_d{_float_token(decay)}",
                    "hot",
                    window=window,
                    decay=decay,
                )
            )

    cold = winners["cold"]
    for gamma in sorted(
        {
            max(0.25, round(float(cold.get("gamma")) - 0.25, 2)),
            round(float(cold.get("gamma")), 2),
            round(float(cold.get("gamma")) + 0.25, 2),
        }
    ):
        for cap_mult in sorted(
            {
                max(1, int(cold.get("cap_mult")) - 1),
                int(cold.get("cap_mult")),
                int(cold.get("cap_mult")) + 1,
            }
        ):
            out.append(
                candidate(
                    f"cold_ref_g{_float_token(gamma)}_c{cap_mult}",
                    "cold",
                    gamma=gamma,
                    cap_mult=cap_mult,
                )
            )

    balance = winners["balance"]
    for sum_pad in sorted(
        {
            int(balance.get("sum_pad")) - 5,
            int(balance.get("sum_pad")),
            int(balance.get("sum_pad")) + 5,
        }
    ):
        out.append(
            candidate(
                f"balance_ref_p{sum_pad:+d}",
                "balance",
                sum_pad=sum_pad,
                odd_lo=int(balance.get("odd_lo")),
                odd_hi=int(balance.get("odd_hi")),
                max_pairs=int(balance.get("max_pairs")),
                min_tails=int(balance.get("min_tails")),
                min_range=int(balance.get("min_range")),
            )
        )

    anti = winners["antipop"]
    for beta_month in sorted(
        {
            max(0.10, round(float(anti.get("beta_month")) - 0.10, 2)),
            round(float(anti.get("beta_month")), 2),
            min(1.00, round(float(anti.get("beta_month")) + 0.10, 2)),
        }
    ):
        for beta_day in sorted(
            {
                max(0.10, round(float(anti.get("beta_day")) - 0.10, 2)),
                round(float(anti.get("beta_day")), 2),
                min(1.00, round(float(anti.get("beta_day")) + 0.10, 2)),
            }
        ):
            out.append(
                candidate(
                    f"antipop_ref_m{_float_token(beta_month)}"
                    f"_d{_float_token(beta_day)}",
                    "antipop",
                    beta_month=beta_month,
                    beta_day=beta_day,
                )
            )

    dedup = {c.candidate_id: c for c in out}
    return [dedup[k] for k in sorted(dedup)]


def _weighted_sample(
    rng: random.Random, weights: dict[int, float], k: int
) -> list[int]:
    pool = dict(weights)
    chosen = []
    for _ in range(k):
        keys = sorted(pool)
        total = sum(pool.values())
        x = rng.random() * total
        acc = 0.0
        picked = keys[-1]
        for number in keys:
            acc += pool[number]
            if x < acc:
                picked = number
                break
        chosen.append(picked)
        del pool[picked]
    return sorted(chosen)


def _arithmetic(numbers: list[int]) -> bool:
    return len({b - a for a, b in zip(numbers, numbers[1:])}) == 1


def _prepare(candidate_: Candidate, context: WeekContext):
    game = context.game
    if candidate_.family in ("uniform", "balance"):
        return None
    if candidate_.family == "hot":
        window = int(candidate_.get("window"))
        decay = float(candidate_.get("decay"))
        recent = context.history[-window:]
        main = {n: 1.0 for n in range(1, POOL[game] + 1)}
        for age, draw in enumerate(reversed(recent)):
            increment = decay**age
            for number in draw.numbers:
                main[number] += increment
        special = None
        if game == SUPER:
            special = {n: 1.0 for n in range(1, SPECIAL_POOL[SUPER] + 1)}
            for age, draw in enumerate(reversed(context.history[-30:])):
                special[draw.special] += decay**age
        return main, special
    if candidate_.family == "cold":
        gamma = float(candidate_.get("gamma"))
        cap_mult = int(candidate_.get("cap_mult"))
        median_gap = _median(context.main_gaps.values())
        cap = (median_gap * cap_mult + 1) ** gamma
        main = {
            n: min((gap + 1) ** gamma, cap)
            for n, gap in context.main_gaps.items()
        }
        special = None
        if game == SUPER:
            special_gamma = max(0.25, gamma * 0.8)
            median_special = _median(context.special_gap_map.values())
            special_cap = (median_special * cap_mult + 1) ** special_gamma
            special = {
                n: min((gap + 1) ** special_gamma, special_cap)
                for n, gap in context.special_gap_map.items()
            }
        return main, special
    if candidate_.family == "antipop":
        beta_month = float(candidate_.get("beta_month"))
        beta_day = float(candidate_.get("beta_day"))
        main = {
            n: beta_month if n <= 12 else (beta_day if n <= 31 else 1.0)
            for n in range(1, POOL[game] + 1)
        }
        return main, None
    raise ValueError(f"未知候選家族：{candidate_.family}")


def _balance_ok(numbers: list[int], game: str, candidate_: Candidate) -> bool:
    base_band = {SUPER: (96, 138), LOTTO649: (122, 178)}[game]
    pad = int(candidate_.get("sum_pad"))
    lo = base_band[0] - pad
    hi = base_band[1] + pad
    if not (lo <= sum(numbers) <= hi):
        return False
    odd = sum(number % 2 for number in numbers)
    if not (int(candidate_.get("odd_lo")) <= odd <= int(candidate_.get("odd_hi"))):
        return False
    pairs = sum(1 for a, b in zip(numbers, numbers[1:]) if b - a == 1)
    if pairs > int(candidate_.get("max_pairs")):
        return False
    if len({n % 10 for n in numbers}) < int(candidate_.get("min_tails")):
        return False
    return numbers[-1] - numbers[0] >= int(candidate_.get("min_range"))


def _draw_ticket(
    candidate_: Candidate,
    context: WeekContext,
    prepared,
    rng: random.Random,
) -> dict:
    game = context.game
    if candidate_.family == "uniform":
        numbers = sorted(rng.sample(range(1, POOL[game] + 1), 6))
    elif candidate_.family in ("hot", "cold"):
        numbers = _weighted_sample(rng, prepared[0], 6)
    elif candidate_.family == "antipop":
        numbers = []
        for _ in range(100):
            numbers = _weighted_sample(rng, prepared[0], 6)
            if not (all(n <= 31 for n in numbers) or _arithmetic(numbers)):
                break
    elif candidate_.family == "balance":
        numbers = []
        for _ in range(5_000):
            numbers = sorted(rng.sample(range(1, POOL[game] + 1), 6))
            if _balance_ok(numbers, game, candidate_):
                break
        else:
            # 防止極端研究參數卡住；退回合法均勻票並由結果中的策略 ID 留痕。
            numbers = sorted(rng.sample(range(1, POOL[game] + 1), 6))
    else:
        raise ValueError(candidate_.family)

    special = None
    if game == SUPER:
        if candidate_.family in ("hot", "cold"):
            special = _weighted_sample(rng, prepared[1], 1)[0]
        else:
            special = rng.randrange(1, SPECIAL_POOL[SUPER] + 1)
    validate_pick(game, numbers, special)
    return {"numbers": numbers, "special": special}


def _rng(context: WeekContext, replicate: int, slot: int, retry: int) -> random.Random:
    # 候選 ID 刻意不進種子：不同策略共享同一組底層均勻亂數，降低比較噪音。
    seed = (
        f"lotto-lab-research|{RESEARCH_ID}|{context.game}|{context.week}"
        f"|rep{replicate}|slot{slot}|retry{retry}"
    )
    return random.Random(_stable_int(seed))


def generate_policy_tickets(
    policy: Policy,
    context: WeekContext,
    replicate: int,
    prepared: dict[Candidate, object] | None = None,
) -> list[dict]:
    prepared = prepared or {
        candidate_: _prepare(candidate_, context) for candidate_ in set(policy.slots)
    }
    tickets = []
    seen: set[frozenset[int]] = set()
    for slot, candidate_ in enumerate(policy.slots, 1):
        retry = 0
        while True:
            ticket = _draw_ticket(
                candidate_, context, prepared[candidate_], _rng(context, replicate, slot, retry)
            )
            key = frozenset(ticket["numbers"])
            if key not in seen or retry >= 20:
                break
            retry += 1
        seen.add(key)
        tickets.append(ticket)
    return tickets


def _update_floors(floors: dict[str, int], draws: Iterable[Draw]) -> None:
    for draw in draws:
        for key, info in draw.prizes.items():
            per_prize = int(info.get("per_prize", 0))
            if int(info.get("winner_count", 0)) > 0 and per_prize > 0:
                floors[key] = min(floors.get(key, per_prize), per_prize)


def build_contexts(game: str, draws: list[Draw]) -> list[WeekContext]:
    """建立逐週切片；history 與估值下界都只包含該週以前的資料。"""
    by_week: dict[str, list[Draw]] = defaultdict(list)
    for draw in sorted(draws, key=lambda item: (item.date, item.period)):
        by_week[week_id_of(date.fromisoformat(draw.date))].append(draw)
    ordered = sorted(by_week, key=lambda week: min(d.date for d in by_week[week]))
    contexts: list[WeekContext] = []
    history: list[Draw] = []
    floors: dict[str, int] = {}
    for week in ordered:
        history_tuple = tuple(history)
        context = WeekContext(
            game=game,
            week=week,
            split="",
            history=history_tuple,
            draws=tuple(sorted(by_week[week], key=lambda item: (item.date, item.period))),
            floor_table=dict(floors),
            main_gaps=gaps(list(history_tuple), game),
            special_gap_map=(
                special_gaps(list(history_tuple), game) if game == SUPER else {}
            ),
        )
        contexts.append(context)
        _update_floors(floors, context.draws)
        history.extend(context.draws)

    n = len(contexts)
    train_end = n // 2
    validation_end = train_end + n // 4
    return [
        replace(
            context,
            split=(
                "train"
                if i < train_end
                else "validation"
                if i < validation_end
                else "holdout"
            ),
        )
        for i, context in enumerate(contexts)
    ]


def _settle_policy(
    policy: Policy,
    context: WeekContext,
    replicate: int,
    prepared: dict[Candidate, object] | None = None,
) -> WeekResult:
    tickets = generate_policy_tickets(policy, context, replicate, prepared)
    raw_prize = robust_prize = fixed_prize = hits = top2_hits = 0
    for draw in context.draws:
        for ticket in tickets:
            tier = match_tier(
                context.game, ticket["numbers"], ticket.get("special"), draw
            )
            if not tier:
                continue
            value, basis, _ = prize_value(tier, draw, context.floor_table)
            hits += 1
            raw_prize += value
            if tier.rank > 2:
                robust_prize += value
            else:
                top2_hits += 1
            if basis == "fixed":
                fixed_prize += value
    cost = len(tickets) * len(context.draws) * TICKET_PRICE[context.game]
    return WeekResult(
        game=context.game,
        week=context.week,
        split=context.split,
        policy_id=policy.policy_id,
        replicate=replicate,
        draws=len(context.draws),
        cost=cost,
        raw_prize=raw_prize,
        robust_prize=robust_prize,
        fixed_prize=fixed_prize,
        hits=hits,
        top2_hits=top2_hits,
    )


def evaluate_policies(
    contexts: list[WeekContext],
    policies: list[Policy],
    replicates: int,
) -> list[WeekResult]:
    results = []
    for context in contexts:
        for policy in policies:
            prepared = {
                candidate_: _prepare(candidate_, context)
                for candidate_ in set(policy.slots)
            }
            for replicate in range(replicates):
                results.append(
                    _settle_policy(policy, context, replicate, prepared)
                )
    return results


def _max_drawdown(rows: list[WeekResult], attr: str = "raw_pnl") -> int:
    equity = peak = drawdown = 0
    for row in sorted(rows, key=lambda item: item.week):
        equity += int(getattr(row, attr))
        peak = max(peak, equity)
        drawdown = min(drawdown, equity - peak)
    return drawdown


def _block_bootstrap_ci(
    values: list[float],
    seed_text: str,
    samples: int,
    block: int = 13,
) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    if samples <= 0:
        value = _mean(values)
        return value, value
    rng = random.Random(_stable_int(seed_text))
    n = len(values)
    estimates = []
    for _ in range(samples):
        sample = []
        while len(sample) < n:
            start = rng.randrange(n)
            sample.extend(values[(start + offset) % n] for offset in range(block))
        estimates.append(_mean(sample[:n]))
    return _quantile(estimates, 0.025), _quantile(estimates, 0.975)


def summarize(
    results: list[WeekResult],
    baseline_policy_id: str = "random_5",
    bootstrap_samples: int = 1_000,
) -> list[dict]:
    """彙總政策表現，並以同週、同 replica 的 random_5 作配對基準。"""
    grouped: dict[tuple[str, str, str], list[WeekResult]] = defaultdict(list)
    index: dict[tuple[str, str, str, int, str], WeekResult] = {}
    for row in results:
        grouped[(row.policy_id, row.game, row.split)].append(row)
        index[(row.game, row.split, row.week, row.replicate, row.policy_id)] = row

    output = []
    for (policy_id, game, split), rows in sorted(grouped.items()):
        by_rep: dict[int, list[WeekResult]] = defaultdict(list)
        for row in rows:
            by_rep[row.replicate].append(row)
        raw_rois = []
        robust_rois = []
        fixed_rois = []
        delta_rois = []
        delta_fixed_rois = []
        drawdowns = []
        positive_replicates = 0
        week_deltas: dict[str, list[float]] = defaultdict(list)
        week_fixed_deltas: dict[str, list[float]] = defaultdict(list)
        for replicate, rep_rows in by_rep.items():
            cost = sum(row.cost for row in rep_rows)
            raw_rois.append(sum(row.raw_prize for row in rep_rows) / cost - 1)
            robust_rois.append(sum(row.robust_prize for row in rep_rows) / cost - 1)
            fixed_rois.append(sum(row.fixed_prize for row in rep_rows) / cost - 1)
            drawdowns.append(_max_drawdown(rep_rows))
            baseline_rows = [
                index[
                    (
                        game,
                        split,
                        row.week,
                        replicate,
                        baseline_policy_id,
                    )
                ]
                for row in rep_rows
            ]
            delta = sum(
                row.robust_prize - baseline.robust_prize
                for row, baseline in zip(rep_rows, baseline_rows)
            )
            delta_roi = delta / cost
            delta_rois.append(delta_roi)
            delta_fixed = sum(
                row.fixed_prize - baseline.fixed_prize
                for row, baseline in zip(rep_rows, baseline_rows)
            )
            delta_fixed_rois.append(delta_fixed / cost)
            if delta_roi > 0:
                positive_replicates += 1
            for row, baseline in zip(rep_rows, baseline_rows):
                week_deltas[row.week].append(
                    (row.robust_prize - baseline.robust_prize) / row.cost
                )
                week_fixed_deltas[row.week].append(
                    (row.fixed_prize - baseline.fixed_prize) / row.cost
                )
        paired_week_values = [
            _mean(values) for _, values in sorted(week_deltas.items())
        ]
        ci_low, ci_high = _block_bootstrap_ci(
            paired_week_values,
            f"{RESEARCH_ID}|{policy_id}|{game}|{split}",
            bootstrap_samples,
        )
        paired_fixed_values = [
            _mean(values) for _, values in sorted(week_fixed_deltas.items())
        ]
        fixed_ci_low, fixed_ci_high = _block_bootstrap_ci(
            paired_fixed_values,
            f"{RESEARCH_ID}|fixed|{policy_id}|{game}|{split}",
            bootstrap_samples,
        )
        active_week_deltas = [
            value for value in paired_week_values if value != 0
        ]
        first_rep = by_rep[min(by_rep)]
        output.append(
            {
                "policy_id": policy_id,
                "game": game,
                "game_name": GAME_NAMES[game],
                "split": split,
                "weeks": len(first_rep),
                "draws": sum(row.draws for row in first_rep),
                "replicates": len(by_rep),
                "cost_per_replicate": sum(row.cost for row in first_rep),
                "raw_roi_mean": _mean(raw_rois),
                "raw_roi_median": _median(raw_rois),
                "robust_roi_mean": _mean(robust_rois),
                "fixed_roi_mean": _mean(fixed_rois),
                "delta_robust_roi_mean": _mean(delta_rois),
                "delta_robust_roi_median": _median(delta_rois),
                "delta_ci_low": ci_low,
                "delta_ci_high": ci_high,
                "delta_fixed_roi_mean": _mean(delta_fixed_rois),
                "delta_fixed_ci_low": fixed_ci_low,
                "delta_fixed_ci_high": fixed_ci_high,
                "positive_replicate_rate": positive_replicates / len(by_rep),
                "active_week_rate": (
                    len(active_week_deltas) / len(paired_week_values)
                ),
                "active_week_win_rate": (
                    sum(value > 0 for value in active_week_deltas)
                    / len(active_week_deltas)
                    if active_week_deltas
                    else 0.5
                ),
                "median_max_drawdown": _median(drawdowns),
                "hits_per_replicate": _mean(
                    sum(row.hits for row in rep_rows)
                    for rep_rows in by_rep.values()
                ),
                "top2_hits_all_replicates": sum(row.top2_hits for row in rows),
            }
        )
    return output


def _summary_lookup(
    summaries: list[dict], policy_id: str, game: str, split: str
) -> dict:
    return next(
        row
        for row in summaries
        if row["policy_id"] == policy_id
        and row["game"] == game
        and row["split"] == split
    )


def _rank_family(
    summaries: list[dict],
    candidates: list[Candidate],
    game: str,
    family: str,
) -> list[Candidate]:
    family_candidates = [c for c in candidates if c.family == family]
    return sorted(
        family_candidates,
        key=lambda item: (
            -_summary_lookup(
                summaries, f"candidate__{item.candidate_id}", game, "train"
            )["delta_robust_roi_mean"],
            item.candidate_id,
        ),
    )


def homogeneous_policies(candidates: list[Candidate]) -> list[Policy]:
    policies = [Policy("random_5", (UNIFORM,) * 5)]
    for candidate_ in candidates:
        if candidate_.family == "uniform":
            continue
        policies.append(
            Policy(f"candidate__{candidate_.candidate_id}", (candidate_,) * 5)
        )
    return policies


def build_final_policies(
    winners: dict[str, Candidate],
    train_ranked: list[Candidate],
) -> list[Policy]:
    top = train_ranked[0]
    next_best = train_ranked[1:3]
    while len(next_best) < 2:
        next_best.append(UNIFORM)
    return [
        Policy("random_5", (UNIFORM,) * 5),
        Policy(
            "current_ensemble",
            (
                CURRENT["uniform"],
                CURRENT["antipop"],
                CURRENT["balance"],
                CURRENT["cold"],
                CURRENT["hot"],
            ),
        ),
        Policy(
            "trained_family_ensemble",
            (
                UNIFORM,
                winners["antipop"],
                winners["balance"],
                winners["cold"],
                winners["hot"],
            ),
        ),
        Policy("trained_best_5", (top,) * 5),
        Policy(
            "trained_blend",
            (UNIFORM, UNIFORM, top, next_best[0], next_best[1]),
        ),
    ]


def strategy_determinism_probe(
    contexts_by_game: dict[str, list[WeekContext]],
    policies_by_game: dict[str, list[Policy]],
) -> dict:
    """以固定代表週重播每個最終政策，產生可稽核的決定性證據。"""
    comparisons = 0
    digests = {}
    passed = True
    for game in GAMES:
        contexts = contexts_by_game[game]
        context = contexts[min(10, len(contexts) - 1)]
        for policy in policies_by_game[game]:
            first = generate_policy_tickets(policy, context, replicate=0)
            second = generate_policy_tickets(policy, context, replicate=0)
            comparisons += 1
            passed = passed and first == second
            digests[f"{game}:{policy.policy_id}"] = hashlib.sha256(
                json.dumps(
                    first,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
    return {
        "passed": passed,
        "comparisons": comparisons,
        "ticket_sha256": digests,
    }


def profile_data(game: str, draws: list[Draw]) -> dict:
    periods = [draw.period for draw in draws]
    draw_dates = [draw.date for draw in draws]
    expected_weekdays = {0, 3} if game == SUPER else {1, 4}
    parsed_dates = []
    invalid_dates = 0
    for draw in draws:
        try:
            parsed_dates.append(date.fromisoformat(draw.date))
        except (TypeError, ValueError):
            parsed_dates.append(None)
            invalid_dates += 1
    off_schedule = [
        draw
        for draw, parsed in zip(draws, parsed_dates)
        if parsed is not None and parsed.weekday() not in expected_weekdays
    ]
    by_week = Counter(
        week_id_of(parsed) for parsed in parsed_dates if parsed is not None
    )
    invalid_numbers = sum(
        not isinstance(draw.numbers, (tuple, list))
        or len(draw.numbers) != 6
        or len(set(draw.numbers)) != 6
        or any(
            not isinstance(number, int)
            or isinstance(number, bool)
            or number < 1
            or number > POOL[game]
            for number in draw.numbers
        )
        for draw in draws
    )
    invalid_special = sum(
        not isinstance(draw.special, int)
        or isinstance(draw.special, bool)
        or not (1 <= draw.special <= (8 if game == SUPER else 49))
        or (
            game == LOTTO649
            and isinstance(draw.numbers, (tuple, list))
            and draw.special in draw.numbers
        )
        for draw in draws
    )
    missing_prize_fields = {
        tier.api_key: sum(tier.api_key not in draw.prizes for draw in draws)
        for tier in TIERS[game]
    }
    invalid_prize_records = 0
    for draw in draws:
        for tier in TIERS[game]:
            info = draw.prizes.get(tier.api_key)
            if info is None:
                continue
            if not isinstance(info, dict):
                invalid_prize_records += 1
                continue
            for field in ("winner_count", "per_prize", "pool", "last_pool"):
                value = info.get(field, 0)
                if (
                    not isinstance(value, (int, float))
                    or isinstance(value, bool)
                    or value < 0
                ):
                    invalid_prize_records += 1
                    break
    game_mismatches = sum(draw.game != game for draw in draws)
    invalid_periods = sum(
        not isinstance(draw.period, int)
        or isinstance(draw.period, bool)
        or draw.period <= 0
        for draw in draws
    )
    ordered_chronologically = bool(draws) and not (
        invalid_dates or invalid_periods
    )
    if ordered_chronologically:
        ordered_chronologically = all(
            (draws[i].date, draws[i].period)
            <= (draws[i + 1].date, draws[i + 1].period)
            for i in range(len(draws) - 1)
        )
    canonical = [
        {
            "game": draw.game,
            "period": draw.period,
            "date": draw.date,
            "numbers": list(draw.numbers),
            "special": draw.special,
            "prizes": draw.prizes,
            "sell_amount": draw.sell_amount,
            "total_amount": draw.total_amount,
        }
        for draw in draws
    ]
    dataset_sha256 = hashlib.sha256(
        json.dumps(
            canonical,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    quality_failures = []
    conditions = {
        "empty_dataset": not draws,
        "duplicate_periods": len(periods) - len(set(periods)) > 0,
        "duplicate_dates": len(draw_dates) - len(set(draw_dates)) > 0,
        "invalid_dates": invalid_dates > 0,
        "not_chronological": not ordered_chronologically,
        "game_mismatches": game_mismatches > 0,
        "invalid_periods": invalid_periods > 0,
        "invalid_numbers": invalid_numbers > 0,
        "invalid_special": invalid_special > 0,
        "missing_prize_fields": any(missing_prize_fields.values()),
        "invalid_prize_records": invalid_prize_records > 0,
    }
    quality_failures.extend(name for name, failed in conditions.items() if failed)
    valid_date_strings = [
        parsed.isoformat() for parsed in parsed_dates if parsed is not None
    ]
    return {
        "game": game,
        "game_name": GAME_NAMES[game],
        "draws": len(draws),
        "weeks": len(by_week),
        "date_min": min(valid_date_strings) if valid_date_strings else None,
        "date_max": max(valid_date_strings) if valid_date_strings else None,
        "period_min": min(periods) if periods else None,
        "period_max": max(periods) if periods else None,
        "duplicate_periods": len(periods) - len(set(periods)),
        "duplicate_dates": len(draw_dates) - len(set(draw_dates)),
        "invalid_dates": invalid_dates,
        "ordered_chronologically": ordered_chronologically,
        "game_mismatches": game_mismatches,
        "invalid_periods": invalid_periods,
        "invalid_numbers": invalid_numbers,
        "invalid_special": invalid_special,
        "missing_prize_fields": missing_prize_fields,
        "invalid_prize_records": invalid_prize_records,
        "off_regular_schedule_draws": len(off_schedule),
        "weeks_with_extra_draws": sum(count > 2 for count in by_week.values()),
        "draws_per_week": dict(sorted(Counter(by_week.values()).items())),
        "dataset_sha256": dataset_sha256,
        "quality_failures": quality_failures,
        "quality_status": "pass" if not quality_failures else "fail",
    }


def _git_commit(base: Path) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "-C", str(base), "rev-parse", "HEAD"],
            text=True,
            encoding="utf-8",
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _aggregate_weekly(results: list[WeekResult]) -> list[dict]:
    grouped: dict[tuple[str, str, str, str], list[WeekResult]] = defaultdict(list)
    for row in results:
        grouped[(row.game, row.week, row.split, row.policy_id)].append(row)
    output = []
    for (game, week, split, policy_id), rows in sorted(grouped.items()):
        output.append(
            {
                "game": game,
                "game_name": GAME_NAMES[game],
                "week": week,
                "split": split,
                "policy_id": policy_id,
                "replicates": len(rows),
                "draws": rows[0].draws,
                "cost_mean": _mean(row.cost for row in rows),
                "raw_prize_mean": _mean(row.raw_prize for row in rows),
                "robust_prize_mean": _mean(row.robust_prize for row in rows),
                "raw_pnl_mean": _mean(row.raw_pnl for row in rows),
                "robust_pnl_mean": _mean(row.robust_pnl for row in rows),
            }
        )
    return output


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _write_markdown_report(path: Path, study: dict) -> None:
    selected = study["selected"]
    lines = [
        "# 歷史策略研究決策",
        "",
        "## 結論",
        "",
        "**經濟決策維持不參與。** 所有購票政策都承擔負成本；只有在封存測試集對"
        "純隨機呈現穩定、可重複的正向差異時，才允許把條件式模擬政策換掉。",
        "",
        "## 封存測試結果",
        "",
        "| 遊戲 | 驗證集選定政策 | 測試集原始 ROI | 相對隨機穩健 ROI 差 | 95% 區間 | 判定 |",
        "|---|---|---:|---:|---:|---|",
    ]
    for game in GAMES:
        row = selected[game]
        holdout = row["holdout"]
        lines.append(
            f"| {GAME_NAMES[game]} | {row['policy_id']} | "
            f"{holdout['raw_roi_mean']:+.2%} | "
            f"{holdout['delta_robust_roi_mean']:+.2%} | "
            f"[{holdout['delta_ci_low']:+.2%}, {holdout['delta_ci_high']:+.2%}] | "
            f"{'通過' if row['edge_proven'] else '未證明優勢'} |"
        )
    lines.extend(
        [
            "",
            "## 決策規則",
            "",
            "- 訓練集只用於粗搜尋與細調。",
            "- 驗證集只用於五種投資組合政策的單次選擇。",
            "- 封存測試集只開封一次；測試結果不再回頭調參。",
            "- 頭獎與貳獎排除於主要穩健指標，避免單一極端獎金支配選擇。",
            "- 若測試集 95% 區間跨過 0，條件式政策回到 `random_5`。",
            "",
            "## 資料範圍",
            "",
        ]
    )
    for profile in study["data_quality"]:
        lines.append(
            f"- {profile['game_name']}：{profile['draws']:,} 期，"
            f"{profile['date_min']} 至 {profile['date_max']}；品質檢查 "
            f"`{profile['quality_status']}`。"
        )
    lines.extend(
        [
            "",
            "> 本報告是純模擬研究，不構成購買或下注建議。",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def run_study(
    store,
    base: Path,
    output_dir: Path,
    replicates: int = 8,
    bootstrap_samples: int = 1_000,
) -> dict:
    """執行粗搜 → training 細調 → validation 選政策 → holdout 決勝。"""
    if replicates < 2:
        raise ValueError("replicates 至少為 2")
    output_dir.mkdir(parents=True, exist_ok=True)
    contexts = {game: build_contexts(game, store.draws(game)) for game in GAMES}
    data_quality = [profile_data(game, store.draws(game)) for game in GAMES]
    data_quality_gate = build_data_quality_gate(data_quality)
    require_gate(data_quality_gate)

    coarse = coarse_candidates()
    coarse_summaries: list[dict] = []
    coarse_winners: dict[str, dict[str, Candidate]] = {}
    for game in GAMES:
        game_results = evaluate_policies(
            contexts[game], homogeneous_policies(coarse), replicates
        )
        game_summaries = summarize(
            game_results,
            baseline_policy_id="random_5",
            bootstrap_samples=0,
        )
        coarse_summaries.extend(game_summaries)
        coarse_winners[game] = {
            family: _rank_family(
                game_summaries, coarse, game, family
            )[0]
            for family in ("hot", "cold", "balance", "antipop")
        }

    refined_winners: dict[str, dict[str, Candidate]] = {}
    refined_summaries: list[dict] = []
    final_policies: dict[str, list[Policy]] = {}
    final_results: list[WeekResult] = []
    final_summaries: list[dict] = []
    for game in GAMES:
        refined = refine_candidates(coarse_winners[game])
        refined_results = evaluate_policies(
            contexts[game], homogeneous_policies(refined), replicates
        )
        summaries = summarize(
            refined_results,
            baseline_policy_id="random_5",
            bootstrap_samples=0,
        )
        refined_summaries.extend(summaries)
        refined_winners[game] = {
            family: _rank_family(summaries, refined, game, family)[0]
            for family in ("hot", "cold", "balance", "antipop")
        }
        all_ranked = sorted(
            [c for c in refined if c.family != "uniform"],
            key=lambda item: (
                -_summary_lookup(
                    summaries,
                    f"candidate__{item.candidate_id}",
                    game,
                    "train",
                )["delta_robust_roi_mean"],
                item.candidate_id,
            ),
        )
        policies = build_final_policies(refined_winners[game], all_ranked)
        final_policies[game] = policies
        game_final_results = evaluate_policies(contexts[game], policies, replicates)
        final_results.extend(game_final_results)
        final_summaries.extend(
            summarize(
                game_final_results,
                baseline_policy_id="random_5",
                bootstrap_samples=bootstrap_samples,
            )
        )

    determinism_probe = strategy_determinism_probe(contexts, final_policies)
    strategy_search_gate = build_strategy_search_gate(
        contexts,
        coarse,
        coarse_winners,
        refined_winners,
        final_policies,
        determinism_probe,
    )
    require_gate(strategy_search_gate)

    selected = {}
    for game in GAMES:
        validation_rows = [
            row
            for row in final_summaries
            if row["game"] == game and row["split"] == "validation"
        ]
        choice = sorted(
            validation_rows,
            key=lambda row: (
                -row["delta_robust_roi_mean"],
                row["policy_id"],
            ),
        )[0]
        holdout = _summary_lookup(
            final_summaries, choice["policy_id"], game, "holdout"
        )
        edge_proven = (
            holdout["delta_ci_low"] > 0
            and holdout["delta_fixed_roi_mean"] >= 0
            and holdout["positive_replicate_rate"] >= 0.75
            and holdout["active_week_win_rate"] > 0.50
        )
        selected[game] = {
            "policy_id": choice["policy_id"],
            "validation": choice,
            "holdout": holdout,
            "edge_proven": edge_proven,
            "conditional_decision": (
                choice["policy_id"] if edge_proven else "random_5"
            ),
        }

    study = {
        "schema_version": "1",
        "research_id": RESEARCH_ID,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "git_commit": _git_commit(base),
        "replicates": replicates,
        "bootstrap_samples": bootstrap_samples,
        "methodology": {
            "grain": "每遊戲、每 ISO 週、每政策、每 replica；同一週的 5 注套用該週所有實際開獎",
            "split": "前 50% 週為 training、接續 25% 為 validation、最後 25% 為 sealed holdout",
            "primary_metric": "排除頭獎與貳獎後，相對 random_5 的每週配對 ROI 差",
            "guardrails": [
                "所有特徵只使用當週週一以前資料",
                "浮動獎級下界只使用當時已知歷史",
                "holdout 不參與調參或政策選擇",
                "95% 區間、replica 一致性與週一致性必須同時通過",
            ],
        },
        "data_quality": data_quality,
        "stage_gates": {
            "data_quality": data_quality_gate,
            "strategy_search": strategy_search_gate,
        },
        "coarse_candidates": [c.as_dict() for c in coarse],
        "coarse_train_winners": {
            game: {
                family: candidate_.as_dict()
                for family, candidate_ in winners.items()
            }
            for game, winners in coarse_winners.items()
        },
        "refined_train_winners": {
            game: {
                family: candidate_.as_dict()
                for family, candidate_ in winners.items()
            }
            for game, winners in refined_winners.items()
        },
        "final_policies": {
            game: [policy.as_dict() for policy in policies]
            for game, policies in final_policies.items()
        },
        "selected": selected,
        "decision": {
            "economic": "no_play",
            "reason": "彩票成本為正且所有開獎組合等機率；未證明外驗優勢前，不參與支配任何購票政策",
            "conditional_simulation": {
                game: selected[game]["conditional_decision"] for game in GAMES
            },
        },
    }

    (output_dir / "strategy_research.json").write_text(
        json.dumps(study, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    all_summaries = []
    for stage, rows in (
        ("coarse", coarse_summaries),
        ("refined", refined_summaries),
        ("final_policy", final_summaries),
    ):
        all_summaries.extend({"stage": stage, **row} for row in rows)
    _write_csv(output_dir / "strategy_summary.csv", all_summaries)
    _write_csv(
        output_dir / "policy_weekly.csv", _aggregate_weekly(final_results)
    )
    _write_markdown_report(output_dir / "DECISION.md", study)
    from .artifact import write_artifact

    write_artifact(output_dir)
    return study
