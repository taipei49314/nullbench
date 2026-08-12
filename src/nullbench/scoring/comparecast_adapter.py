"""Comparecast-compatible sequential CS + e-process (pure Python/NumPy/SciPy).

On Windows, the official `comparecast` package pulls `confseq`, which currently
requires MSVC to build. This module re-implements the algorithms nullbench needs
from Choe & Ramdas (2023) / Howard et al., under MIT lineage of comparecast:

- asymptotic confidence sequences (Waudby-Smith et al.)
- gamma-exponential mixture e-process for H0: mean(delta) <= 0

When real `comparecast` + `confseq` import cleanly, prefer those instead
(see sequential.py).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.special import gammainc, loggamma


@dataclass
class ComparecastResult:
    backend: str
    n: int
    mean_delta: float
    lcb: float
    ucb: float
    e_pq: float  # evidence that p beats q (delta > 0)
    e_qp: float  # evidence that q beats p
    alpha: float
    note: str


def confseq_asymptotic(
    xs: np.ndarray,
    alpha: float = 0.05,
    t_star: int = 100,
    assume_iid: bool = False,
) -> tuple[np.ndarray, np.ndarray]:
    """Asymptotic (1-alpha) CS (Waudby-Smith et al.); pure NumPy port."""
    xs = np.asarray(xs, dtype=float)
    t = len(xs)
    if t == 0:
        return np.array([]), np.array([])
    rhosq = (2 * np.log(1 / alpha) + np.log(1 + 2 * np.log(1 / alpha))) / t_star
    times = np.arange(1, t + 1)
    mus = np.cumsum(xs) / times
    gammas = mus.copy()
    gammas[1:], gammas[0] = mus[:-1], 0.0
    vs = np.maximum(1.0, np.cumsum((xs - gammas) ** 2)) / times
    if assume_iid:
        radii = np.sqrt(
            vs
            * 2
            * (rhosq * times + 1)
            / (rhosq * times**2)
            * np.log(np.sqrt(rhosq * times + 1) / alpha)
        )
    else:
        radii = np.sqrt(
            2
            * (rhosq * times * vs + 1)
            / (rhosq * times**2)
            * np.log(np.sqrt(rhosq * times * vs + 1) / alpha)
        )
    return mus - radii, mus + radii


def confseq_pm_eb(
    xs: np.ndarray,
    alpha: float = 0.05,
    lo: float = -1.0,
    hi: float = 1.0,
    c: float = 0.5,
) -> tuple[np.ndarray, np.ndarray]:
    """Predictably-mixed empirical Bernstein CS (Waudby-Smith & Ramdas 2020)."""
    xs = np.asarray(xs, dtype=float)
    if len(xs) == 0:
        return np.array([]), np.array([])
    # scale to [0,1]
    zs = (xs - lo) / (hi - lo)
    t = len(zs)
    init_mean, init_var = 0.5, 0.25
    mus = (init_mean + np.cumsum(zs)) / np.arange(2, t + 2)
    sigmas = (init_var + np.cumsum((zs - mus) ** 2)) / np.arange(2, t + 2)
    lambdas = np.sqrt(
        2 * np.log(2.0 / alpha) / (sigmas * np.arange(2, t + 2) * np.log(np.arange(3, t + 3)))
    )
    lambdas = np.minimum(lambdas, c)
    lambdas[1:], lambdas[0] = lambdas[:-1], c
    psis = -0.25 * (np.log(1.0 - lambdas) + lambdas)
    mus[1:], mus[0] = mus[:-1], 0.5
    vs = 4 * (zs - mus) ** 2
    lambdas_sum = np.cumsum(lambdas)
    centers = np.cumsum(zs * lambdas) / lambdas_sum
    radii = (np.log(2.0 / alpha) + np.cumsum(vs * psis)) / lambdas_sum
    centers = centers * (hi - lo) + lo
    radii = (hi - lo) * radii
    return centers - radii, centers + radii


def _gamma_exponential_log_mixture(
    sums: np.ndarray,
    vs: np.ndarray,
    rho: float,
    c: float,
) -> np.ndarray:
    """Port of comparecast.eprocess.gamma_exponential_log_mixture."""
    csq = c**2
    rho_csq = rho / csq
    v_rho_csq = (vs + rho) / csq
    cs_v_csq = (c * sums + vs) / csq
    cs_v_rho_csq = cs_v_csq + rho_csq
    leading_constant = (
        rho_csq * np.log(rho_csq) - loggamma(rho_csq) - np.log(gammainc(rho_csq, rho_csq))
    )
    return np.where(
        cs_v_rho_csq > 0,
        (
            leading_constant
            + loggamma(v_rho_csq)
            + np.log(gammainc(v_rho_csq, np.maximum(1e-8, cs_v_rho_csq)))
            - v_rho_csq * np.log(np.maximum(cs_v_rho_csq, 1e-16))
            + cs_v_csq
        ),
        leading_constant - rho_csq - np.log(v_rho_csq),
    )


def eprocess_expm(
    xs: np.ndarray,
    *,
    v_opt: float = 10.0,
    c: float = 1.0,
    alpha_opt: float = 0.05,
    clip_max: float = 1e7,
) -> np.ndarray:
    """E-process for H0: mean(x) <= 0 (gamma-exp mixture). Port of comparecast."""
    xs = np.asarray(xs, dtype=float)
    t = len(xs)
    if t == 0:
        return np.array([])
    times = np.arange(1, t + 1)
    sums = np.cumsum(xs)
    means = sums / times
    pred_means = means.copy()
    pred_means[1:], pred_means[0] = means[:-1], 0.0
    vs = np.cumsum((xs - pred_means) ** 2)
    vs = np.maximum(vs, 1e-12)
    v_opt_use = v_opt if v_opt is not None else float(vs[-1])
    alpha_os = 2 * alpha_opt
    rho = v_opt_use / (2 * np.log(1 / alpha_os) + np.log(1 + 2 * np.log(1 / alpha_os)))
    log_e = _gamma_exponential_log_mixture(sums, vs, rho, c)
    log_e = np.clip(log_e, a_min=None, a_max=np.log(clip_max))
    return np.exp(log_e)


def compare_deltas(
    deltas: list[float] | np.ndarray,
    *,
    alpha: float = 0.05,
    lo: float | None = None,
    hi: float | None = None,
    method: str = "asymptotic",
) -> ComparecastResult:
    """
    Compare sequence of score/PnL differentials (higher = first arm better).

    Returns final CS for mean(delta) and e-processes e_pq / e_qp.
    """
    arr = np.asarray(deltas, dtype=float)
    n = len(arr)
    if n == 0:
        return ComparecastResult(
            "empty", 0, 0.0, 0.0, 0.0, 1.0, 1.0, alpha, "no data"
        )

    mean_delta = float(arr.mean())
    # Bound range for PM-EB; for PnL use empirical robust bounds
    if lo is None or hi is None:
        span = float(np.max(np.abs(arr))) + 1.0
        lo = -span if lo is None else lo
        hi = span if hi is None else hi
    c = max(hi - lo, 1e-6)

    if method == "pm_eb":
        lcbs, ucbs = confseq_pm_eb(arr, alpha=alpha, lo=lo, hi=hi, c=min(0.5, 0.9))
        backend = "comparecast_compat.pm_eb"
    else:
        lcbs, ucbs = confseq_asymptotic(arr, alpha=alpha)
        backend = "comparecast_compat.asymptotic"

    e_pq = eprocess_expm(arr, c=c, alpha_opt=alpha / 2)
    e_qp = eprocess_expm(-arr, c=c, alpha_opt=alpha / 2)

    return ComparecastResult(
        backend=backend,
        n=n,
        mean_delta=mean_delta,
        lcb=float(lcbs[-1]),
        ucb=float(ucbs[-1]),
        e_pq=float(e_pq[-1]),
        e_qp=float(e_qp[-1]),
        alpha=alpha,
        note=(
            "Pure-Python port of comparecast CS + gamma-exp e-process "
            "(Choe & Ramdas 2023 lineage). Diagnostic; not a formal discovery claim."
        ),
    )


def try_official_comparecast(deltas: list[float], alpha: float = 0.05) -> ComparecastResult | None:
    """Use installed comparecast if confseq is available."""
    try:
        from comparecast.confseq import confseq_asymptotic as cc_asymp  # type: ignore
        from comparecast.eprocess import eprocess_expm as cc_e  # type: ignore
    except Exception:
        return None
    arr = np.asarray(deltas, dtype=float)
    if len(arr) == 0:
        return None
    lcbs, ucbs = cc_asymp(arr, alpha=alpha)
    e_pq = cc_e(arr, c=float(np.ptp(arr) + 1.0), alpha_opt=alpha / 2)
    e_qp = cc_e(-arr, c=float(np.ptp(arr) + 1.0), alpha_opt=alpha / 2)
    return ComparecastResult(
        backend="comparecast+confseq",
        n=len(arr),
        mean_delta=float(arr.mean()),
        lcb=float(lcbs[-1]),
        ucb=float(ucbs[-1]),
        e_pq=float(e_pq[-1]),
        e_qp=float(e_qp[-1]),
        alpha=alpha,
        note="Official comparecast package",
    )
