"""Sequential evidence: comparecast-first, then expectation, then fallback."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from nullbench.scoring.comparecast_adapter import (
    ComparecastResult,
    compare_deltas,
    try_official_comparecast,
)


@dataclass
class SequentialEvidence:
    backend: str
    n: int
    mean_delta: float
    e_value: float
    log_e: float
    note: str
    lcb: float | None = None
    ucb: float | None = None
    e_pq: float | None = None
    e_qp: float | None = None
    alpha: float = 0.05


def _from_comparecast(cc: ComparecastResult) -> SequentialEvidence:
    # Primary e-value: evidence strategy beats null (e_pq)
    e = max(cc.e_pq, 1e-12)
    return SequentialEvidence(
        backend=cc.backend,
        n=cc.n,
        mean_delta=cc.mean_delta,
        e_value=e,
        log_e=float(np.log(e)),
        note=cc.note,
        lcb=cc.lcb,
        ucb=cc.ucb,
        e_pq=cc.e_pq,
        e_qp=cc.e_qp,
        alpha=cc.alpha,
    )


def e_process_from_deltas(deltas: list[float], *, wealth0: float = 1.0) -> SequentialEvidence:
    """Build sequential evidence on mean(delta) > 0."""
    del wealth0  # kept for API compatibility
    if not deltas:
        return SequentialEvidence("empty", 0, 0.0, 1.0, 0.0, "no periods")

    # 1) official comparecast if importable
    official = try_official_comparecast(deltas)
    if official is not None:
        return _from_comparecast(official)

    # 2) pure-Python comparecast algorithms (default path on Windows)
    try:
        return _from_comparecast(compare_deltas(deltas, method="asymptotic"))
    except Exception:
        pass

    # 3) last-resort betting score
    arr = np.asarray(deltas, dtype=float)
    mean_delta = float(arr.mean())
    lam = 0.25
    wealth = 1.0
    for d in arr:
        edge = float(np.tanh(d / (np.std(arr) + 1e-6)))
        wealth *= max(1e-12, 1.0 + lam * edge)
    e_val = max(wealth, 1e-12)
    return SequentialEvidence(
        backend="numpy_betting",
        n=len(arr),
        mean_delta=mean_delta,
        e_value=float(e_val),
        log_e=float(np.log(e_val)),
        note="Fallback betting e-process; comparecast path unavailable.",
    )


def compare_strategy_to_null(
    strategy_period_pnl: list[float],
    null_mean_period_pnl: list[float],
) -> SequentialEvidence:
    """delta_t = strategy_pnl_t - mean_null_pnl_t each period."""
    if len(strategy_period_pnl) != len(null_mean_period_pnl):
        raise ValueError("length mismatch")
    deltas = [s - n for s, n in zip(strategy_period_pnl, null_mean_period_pnl)]
    return e_process_from_deltas(deltas)
