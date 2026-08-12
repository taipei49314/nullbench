"""nullbench — pre-register decisions, score against chance, never backfill."""

__version__ = "0.4.0"

from nullbench.core.models import (
    Draw,
    ExperimentSpec,
    FreezeRecord,
    GameSpec,
    ReportSummary,
    SettleRecord,
    SpecialMode,
    StrategySpec,
    Ticket,
)
from nullbench.core.pipeline import (
    add_strategy,
    freeze_latest,
    freeze_period,
    init_study,
    settle_period,
)
from nullbench.errors import NullbenchError
from nullbench.protocols import DomainInfo, StrategyFn

__all__ = [
    "__version__",
    "Draw",
    "ExperimentSpec",
    "FreezeRecord",
    "GameSpec",
    "ReportSummary",
    "SettleRecord",
    "SpecialMode",
    "StrategySpec",
    "Ticket",
    "DomainInfo",
    "StrategyFn",
    "NullbenchError",
    "add_strategy",
    "freeze_latest",
    "freeze_period",
    "init_study",
    "settle_period",
]
