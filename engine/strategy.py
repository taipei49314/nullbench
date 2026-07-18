"""權重系統：replay weights.jsonl 推導當前權重（無可變狀態檔），排名分數更新。

誠實註記（裁決書強制）：理論預期權重長期呈無趨勢隨機漫步；
權重系統是被研究的展品，不是引擎。
"""
from __future__ import annotations

import math

from .config import ADAPTIVE_PERSONAS, BURN_IN_WEEKS, ETA, MIX_EPS, WEIGHT_CLAMP
from .ledger import Ledger

UNIFORM = {p: 1.0 / len(ADAPTIVE_PERSONAS) for p in ADAPTIVE_PERSONAS}


def weight_events(weights_ledger: Ledger, game: str) -> list[dict]:
    return [e for e in weights_ledger.events_of("weights") if e["game"] == game]


def current_weights(weights_ledger: Ledger, game: str) -> dict[str, float]:
    events = weight_events(weights_ledger, game)
    return dict(events[-1]["after"]) if events else dict(UNIFORM)


def settled_week_count(weights_ledger: Ledger, game: str) -> int:
    return len(weight_events(weights_ledger, game))


def percentile_rank(value: float, population: list[float]) -> float:
    """value 在 population 中的百分位 r∈[0,1]，同分取平均名次。"""
    if not population:
        return 0.5
    less = sum(1 for x in population if x < value)
    equal = sum(1 for x in population if x == value)
    return (less + (equal + 1) / 2) / (len(population) + 1)


def update_weights(before: dict[str, float], scores: dict[str, float],
                   burn_in: bool) -> dict[str, float]:
    """w ← w·exp(η·s) → 正規化 → 與均勻混合 ε → clamp → 重正規化。

    burn_in=True 時分數照記但不套用，回傳均勻。
    """
    if burn_in:
        return dict(UNIFORM)
    w = {p: before.get(p, UNIFORM[p]) * math.exp(ETA * scores.get(p, 0.0))
         for p in ADAPTIVE_PERSONAS}
    total = sum(w.values())
    w = {p: v / total for p, v in w.items()}
    n = len(ADAPTIVE_PERSONAS)
    w = {p: (1 - MIX_EPS) * v + MIX_EPS / n for p, v in w.items()}
    lo, hi = WEIGHT_CLAMP
    w = {p: min(max(v, lo), hi) for p, v in w.items()}
    total = sum(w.values())
    return {p: v / total for p, v in w.items()}


def allocate_seats(weights: dict[str, float], seats: int = 4) -> dict[str, int]:
    """最大餘數法（Hamilton）：floor 先給、餘席按小數餘額降序、平手依 persona_id 字典序。"""
    total = sum(weights.values())
    shares = {p: weights[p] / total * seats for p in sorted(weights)}
    alloc = {p: int(shares[p]) for p in shares}
    remaining = seats - sum(alloc.values())
    order = sorted(shares, key=lambda p: (-(shares[p] - alloc[p]), p))
    for p in order[:remaining]:
        alloc[p] += 1
    return alloc


def record_weights(weights_ledger: Ledger, game: str, week_id: str,
                   before: dict, after: dict, scores: dict,
                   null_portfolio_pnl: list[int], extras: dict | None = None) -> dict | None:
    """冪等：同 (game, week_id) 已存在即跳過。null_portfolio_pnl 一併落檔供主要終點累計。"""
    for e in weight_events(weights_ledger, game):
        if e["week"] == week_id:
            return None
    payload = {
        "game": game, "week": week_id,
        "before": before, "after": after, "scores": scores, "eta": ETA,
        "null_portfolio_pnl": null_portfolio_pnl,
    }
    if extras:
        payload.update(extras)
    return weights_ledger.append("weights", payload)
