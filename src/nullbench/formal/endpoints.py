"""Alpha-spending formal endpoint (26 / 52 settled periods).

Design aligned with classic two-look spending (lotto-lab PREREG lineage):

- H0: strategy cumulative virtual P&L distribution equals equal-cost null cloud
- Two-sided empirical p against the null portfolio cum-P&L cloud
- Looks only at fixed sample sizes n ∈ checkpoints (default 26, 52)
- Between looks: descriptive only — no α spent, no reject/accept claims
- At a look: spend the pre-registered α slice; reject if p ≤ α_spent

This does **not** license real-money conclusions. Virtual simulation only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

# Default alpha-spending schedule (per primary comparison family)
DEFAULT_CHECKPOINTS: dict[int, float] = {
    26: 0.005,
    52: 0.020,
}


class FormalEndpointConfig(BaseModel):
    """Attach to ExperimentSpec to enable formal looks."""

    enabled: bool = False
    primary_strategy_id: str | None = None  # if None: evaluate all strategies at look
    checkpoints: dict[int, float] = Field(default_factory=lambda: dict(DEFAULT_CHECKPOINTS))
    # If True, only primary_strategy_id may trigger claim_status=formal_endpoint
    primary_only_for_claim: bool = True

    def alpha_at(self, n: int) -> float | None:
        return self.checkpoints.get(n)


@dataclass
class StrategyFormalResult:
    strategy_id: str
    cum_pnl: float
    empirical_p: float
    alpha_spent: float
    reject_h0: bool
    n_null: int


@dataclass
class FormalEvaluation:
    n_settled: int
    endpoint_open: bool
    alpha_spent: float | None
    primary_strategy: str | None
    strategies: dict[str, StrategyFormalResult] = field(default_factory=dict)
    reject_h0: bool = False
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "n_settled": self.n_settled,
            "endpoint_open": self.endpoint_open,
            "alpha_spent": self.alpha_spent,
            "primary_strategy": self.primary_strategy,
            "reject_h0": self.reject_h0,
            "note": self.note,
            "strategies": {
                k: {
                    "cum_pnl": v.cum_pnl,
                    "empirical_p": v.empirical_p,
                    "alpha_spent": v.alpha_spent,
                    "reject_h0": v.reject_h0,
                    "n_null": v.n_null,
                }
                for k, v in self.strategies.items()
            },
        }


def two_sided_empirical_p(value: float, cloud: list[float]) -> float:
    """Two-sided Monte Carlo p-value against an empirical null cloud."""
    if not cloud:
        return 1.0
    n = len(cloud)
    # more extreme in either direction relative to null center
    ge = sum(1 for x in cloud if x >= value)
    le = sum(1 for x in cloud if x <= value)
    # standard two-sided MC: 2 * min(tail) / n
    p = 2.0 * min(ge, le) / n
    # ensure p >= 1/n (never report exact 0)
    return min(1.0, max(p, 1.0 / n))


def evaluate_formal_endpoint(
    *,
    config: FormalEndpointConfig,
    strategy_cum_pnl: dict[str, float],
    null_cum_pnl_cloud: list[float],
    n_settled: int,
) -> FormalEvaluation:
    """
    Evaluate formal endpoint at current settled count.

    endpoint_open=True only when n_settled is an exact checkpoint key.
    """
    if not config.enabled:
        return FormalEvaluation(
            n_settled=n_settled,
            endpoint_open=False,
            alpha_spent=None,
            primary_strategy=config.primary_strategy_id,
            note="Formal endpoint disabled on this experiment.",
        )
    if config.primary_only_for_claim and not config.primary_strategy_id:
        return FormalEvaluation(
            n_settled=n_settled,
            endpoint_open=False,
            alpha_spent=None,
            primary_strategy=None,
            note="Formal endpoint closed: no primary strategy was pre-specified.",
        )

    alpha = config.alpha_at(n_settled)
    if alpha is None:
        upcoming = sorted(config.checkpoints)
        next_look = next((k for k in upcoming if k > n_settled), None)
        note = f"Between looks (n={n_settled}). Descriptive only. " + (
            f"Next formal look at n={next_look}." if next_look else "Past final look."
        )
        return FormalEvaluation(
            n_settled=n_settled,
            endpoint_open=False,
            alpha_spent=None,
            primary_strategy=config.primary_strategy_id,
            note=note,
        )

    targets = (
        [config.primary_strategy_id]
        if config.primary_strategy_id and config.primary_only_for_claim
        else list(strategy_cum_pnl.keys())
    )
    if config.primary_strategy_id and config.primary_strategy_id not in strategy_cum_pnl:
        return FormalEvaluation(
            n_settled=n_settled,
            endpoint_open=False,
            alpha_spent=None,
            primary_strategy=config.primary_strategy_id,
            note=f"Primary strategy {config.primary_strategy_id!r} missing from results.",
        )

    results: dict[str, StrategyFormalResult] = {}
    any_reject = False
    for sid in targets:
        if sid is None:
            continue
        if sid not in strategy_cum_pnl:
            continue
        pnl = strategy_cum_pnl[sid]
        p = two_sided_empirical_p(pnl, null_cum_pnl_cloud)
        reject = p <= alpha
        any_reject = any_reject or reject
        results[sid] = StrategyFormalResult(
            strategy_id=sid,
            cum_pnl=pnl,
            empirical_p=p,
            alpha_spent=alpha,
            reject_h0=reject,
            n_null=len(null_cum_pnl_cloud),
        )

    # Also report non-primary strategies as informational when primary_only
    if config.primary_only_for_claim and config.primary_strategy_id:
        for sid, pnl in strategy_cum_pnl.items():
            if sid in results:
                continue
            p = two_sided_empirical_p(pnl, null_cum_pnl_cloud)
            results[sid] = StrategyFormalResult(
                strategy_id=sid,
                cum_pnl=pnl,
                empirical_p=p,
                alpha_spent=alpha,
                reject_h0=False,  # not authorized to reject without primary budget
                n_null=len(null_cum_pnl_cloud),
            )

    note = (
        f"Formal look at n={n_settled} with α={alpha}. "
        "H0: strategy cum P&L indistinct from equal-cost null cloud (two-sided empirical p). "
        "Simulation only — not betting advice."
    )
    return FormalEvaluation(
        n_settled=n_settled,
        endpoint_open=True,
        alpha_spent=alpha,
        primary_strategy=config.primary_strategy_id,
        strategies=results,
        reject_h0=any_reject,
        note=note,
    )
