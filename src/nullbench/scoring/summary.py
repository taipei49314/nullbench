"""Aggregate score snippets for reports."""

from __future__ import annotations

from nullbench.core.models import Draw, GameSpec, Ticket
from nullbench.scoring.brier import brier_for_main_balls


def period_score_summary(
    game: GameSpec,
    tickets: list[Ticket],
    draw: Draw,
) -> dict:
    b = brier_for_main_balls(tickets, draw, game.main_max, game.main_count)
    return {
        "period": draw.period,
        "brier_marginal_mse": b["brier_marginal_mse"],
        "brier_uniform_mse": b["brier_uniform_mse"],
        "regret_vs_uniform": b["regret_vs_uniform"],
        "scoring_backend": b.get("backend_name", "numpy"),
    }
