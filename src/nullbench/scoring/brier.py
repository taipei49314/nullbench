"""Proper-score helpers with optional properscoring backend."""

from __future__ import annotations

import numpy as np

from nullbench.core.models import Draw, Ticket


def _uniform_main_probs(main_max: int, main_count: int) -> np.ndarray:
    """Marginal inclusion probability under uniform k-subset (exact)."""
    # P(number i is drawn) = C(n-1, k-1) / C(n, k) = k / n
    p = main_count / main_max
    return np.full(main_max, p, dtype=float)


def tickets_to_soft_presence(tickets: list[Ticket], main_max: int) -> np.ndarray:
    """Average one-hot presence across tickets → soft probability-like mass per ball."""
    mass = np.zeros(main_max, dtype=float)
    if not tickets:
        return mass
    for t in tickets:
        for n in t.numbers:
            mass[n - 1] += 1.0
    mass /= len(tickets)
    # Normalize to mean marginal scale for comparison (not a full joint model)
    return mass


def brier_for_main_balls(
    tickets: list[Ticket],
    draw: Draw,
    main_max: int,
    main_count: int,
) -> dict[str, float | str]:
    """
    Mean squared error of per-ball soft presence vs binary outcomes.

    This is a *diagnostic* proper-score style metric on marginals, not a claim
    that tickets define a calibrated joint distribution.
    """
    y = np.zeros(main_max, dtype=float)
    for n in draw.numbers:
        if 1 <= n <= main_max:
            y[n - 1] = 1.0

    pred = tickets_to_soft_presence(tickets, main_max)
    # Scale pred to sum to main_count so it is comparable to inclusion indicators
    s = pred.sum()
    if s > 0:
        pred = pred * (main_count / s)

    mse = float(np.mean((pred - y) ** 2))

    uni = _uniform_main_probs(main_max, main_count)
    mse_uni = float(np.mean((uni - y) ** 2))

    # Optional giant: properscoring binary Brier if installed
    backend = "numpy"
    try:
        import properscoring as ps  # type: ignore

        # binary Brier per ball then mean
        brier_ps = float(np.mean([ps.brier_score(y[i], pred[i]) for i in range(main_max)]))
        mse = brier_ps
        backend = "properscoring"
    except Exception:
        pass

    return {
        "brier_marginal_mse": mse,
        "brier_uniform_mse": mse_uni,
        "regret_vs_uniform": mse - mse_uni,
        "backend_name": backend,
    }
