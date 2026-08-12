"""Sequential evidence: e-process style diagnostics.

Prefers the `expectation` package when installed; otherwise a conservative
stdlib/numpy betting-score e-process on period-level score differentials.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class SequentialEvidence:
    backend: str
    n: int
    mean_delta: float
    e_value: float
    log_e: float
    note: str


def e_process_from_deltas(deltas: list[float], *, wealth0: float = 1.0) -> SequentialEvidence:
    """
    Build an anytime-valid-style e-process on mean(delta) > 0 using a simple
    test martingale: each step multiplies wealth by (1 + λ * tanh(d)).

    This is a *diagnostic* e-value, not a full substitute for a paper-grade
    e-process. When `expectation` is installed we prefer its capital process.
    """
    if not deltas:
        return SequentialEvidence("empty", 0, 0.0, 1.0, 0.0, "no periods")

    arr = np.asarray(deltas, dtype=float)
    mean_delta = float(arr.mean())

    # Try giant: expectation
    try:
        return _via_expectation(arr)
    except Exception:
        pass

    # Fallback: bounded betting score
    lam = 0.25
    wealth = float(wealth0)
    for d in arr:
        # map delta to (-1,1) then bet
        edge = float(np.tanh(d / (np.std(arr) + 1e-6)))
        wealth *= max(1e-12, 1.0 + lam * edge)
    e_val = max(wealth, 1e-12)
    return SequentialEvidence(
        backend="numpy_betting",
        n=len(arr),
        mean_delta=mean_delta,
        e_value=float(e_val),
        log_e=float(np.log(e_val)),
        note=(
            "Diagnostic e-process on period PnL deltas vs null mean. "
            "Install optional 'expectation' for library-backed sequential tests."
        ),
    )


def _via_expectation(arr: np.ndarray) -> SequentialEvidence:
    """Best-effort adapter — API may vary across expectation versions."""
    import expectation  # type: ignore

    mean_delta = float(arr.mean())
    # Common patterns: try a few entry points without hard-coding one forever
    e_val = None
    backend = "expectation"
    if hasattr(expectation, "eprocess"):
        mod = expectation.eprocess
        if hasattr(mod, "EProcess"):
            ep = mod.EProcess()
            for x in arr:
                if hasattr(ep, "update"):
                    ep.update(float(x))
                elif hasattr(ep, "add"):
                    ep.add(float(x))
            e_val = float(getattr(ep, "wealth", getattr(ep, "e_value", np.nan)))
    if e_val is None or not np.isfinite(e_val):
        raise RuntimeError("expectation installed but no compatible e-process API found")
    return SequentialEvidence(
        backend=backend,
        n=len(arr),
        mean_delta=mean_delta,
        e_value=max(e_val, 1e-12),
        log_e=float(np.log(max(e_val, 1e-12))),
        note="e-process via expectation package",
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
