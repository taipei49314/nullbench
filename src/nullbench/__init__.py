"""nullbench — null-first decision lab (pre-register, score vs chance)."""

__version__ = "0.9.0"

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
    build_report,
    freeze_latest,
    freeze_period,
    freeze_prospective,
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
    "build_report",
    "freeze_latest",
    "freeze_period",
    "freeze_prospective",
    "init_study",
    "settle_period",
]
