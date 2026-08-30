"""nullbench — null-first decision lab (pre-register, score vs chance)."""

__version__ = "0.9.0"

from nullbench.core.models import (
    Draw,
    ExperimentSpec,
    FreezeRecord,
    GameSpec,
    HistoryAnchor,
    HistoryBoundary,
    RegistrationMode,
    ReportSummary,
    SettlementMode,
    SettleRecord,
    SpecialMode,
    StrategySpec,
    Ticket,
)
from nullbench.core.pipeline import (
    add_strategy,
    build_report,
    freeze_last_n,
    freeze_latest,
    freeze_period,
    init_study,
    settle_period,
)
from nullbench.errors import NullbenchError, OutcomePendingError
from nullbench.protocols import DomainInfo, StrategyFn

__all__ = [
    "__version__",
    "Draw",
    "ExperimentSpec",
    "FreezeRecord",
    "GameSpec",
    "HistoryAnchor",
    "HistoryBoundary",
    "RegistrationMode",
    "ReportSummary",
    "SettlementMode",
    "SettleRecord",
    "SpecialMode",
    "StrategySpec",
    "Ticket",
    "DomainInfo",
    "StrategyFn",
    "NullbenchError",
    "OutcomePendingError",
    "add_strategy",
    "build_report",
    "freeze_latest",
    "freeze_last_n",
    "freeze_period",
    "init_study",
    "settle_period",
]
