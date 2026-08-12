"""nullbench — pre-register decisions, score against chance, never backfill."""

__version__ = "0.2.0"

# Public surface for library users
from nullbench.core.models import (
    Draw,
    ExperimentSpec,
    FreezeRecord,
    GameSpec,
    ReportSummary,
    SettleRecord,
    StrategySpec,
    Ticket,
)
from nullbench.core.pipeline import freeze_period, init_study, settle_period

__all__ = [
    "__version__",
    "Draw",
    "ExperimentSpec",
    "FreezeRecord",
    "GameSpec",
    "ReportSummary",
    "SettleRecord",
    "StrategySpec",
    "Ticket",
    "freeze_period",
    "init_study",
    "settle_period",
]
