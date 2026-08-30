"""Pydantic contracts — stable surface for freeze / settle / report."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class ClaimStatus(str, Enum):
    """How strong a claim the report is allowed to make."""

    DESCRIPTIVE_ONLY = "descriptive_only"
    FORMAL_ENDPOINT = "formal_endpoint"


class RegistrationMode(str, Enum):
    """How a v3 freeze relates to the target outcome."""

    PRE_OUTCOME = "pre_outcome"
    BACKTEST = "backtest"


class SettlementMode(str, Enum):
    """Registration evidence attached to a settlement."""

    PRE_OUTCOME = "pre_outcome"
    BACKTEST = "backtest"
    LEGACY_BACKTEST = "legacy_backtest"
    LEGACY_UNKNOWN = "legacy_unknown"


class HistoryBoundary(BaseModel):
    """Last draw inside an ordered-prefix history commitment."""

    date: str | None = None
    period: str


class HistoryAnchor(BaseModel):
    """Causal history boundary sealed by a v3 freeze."""

    algorithm: Literal["ordered_prefix_v1"] = "ordered_prefix_v1"
    count: int = Field(ge=0)
    through: HistoryBoundary | None = None

    @model_validator(mode="after")
    def boundary_matches_count(self) -> HistoryAnchor:
        if self.count == 0 and self.through is not None:
            raise ValueError("empty history anchor cannot have a through boundary")
        if self.count > 0 and self.through is None:
            raise ValueError("non-empty history anchor requires a through boundary")
        return self


class Ticket(BaseModel):
    """One discrete decision (e.g. one lottery line)."""

    numbers: list[int]
    special: int | None = None
    label: str | None = None

    @field_validator("numbers")
    @classmethod
    def sorted_unique(cls, v: list[int]) -> list[int]:
        if len(v) != len(set(v)):
            raise ValueError("numbers must be unique")
        return sorted(v)


class Draw(BaseModel):
    """One revealed outcome for a period."""

    period: str
    numbers: list[int]
    special: int | None = None
    date: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)

    @field_validator("numbers")
    @classmethod
    def sorted_unique(cls, v: list[int]) -> list[int]:
        if len(v) != len(set(v)):
            raise ValueError("numbers must be unique")
        return sorted(v)


class SpecialMode(str, Enum):
    """How the special ball interacts with tickets."""

    NONE = "none"  # no special
    SEPARATE = "separate"  # ticket picks special from special_max (e.g. 威力彩第二區)
    FROM_MAIN_POOL = "from_main_pool"  # draw has special from main pool; ticket does not pick it


class GameSpec(BaseModel):
    """Domain-agnostic game rules for k-of-n style selections."""

    id: str
    name: str
    main_count: int = Field(ge=1)
    main_max: int = Field(ge=2)
    special_max: int | None = None  # pool size for SEPARATE mode
    special_mode: SpecialMode = SpecialMode.NONE
    ticket_cost: float = Field(gt=0)
    # prize_table: hits_main (+ optional special flag key) -> payout
    # keys like "3", "3+s", "6", "6+s"
    prize_table: dict[str, float] = Field(default_factory=dict)
    description: str = ""

    @model_validator(mode="after")
    def bounds(self) -> GameSpec:
        if self.main_count > self.main_max:
            raise ValueError("main_count cannot exceed main_max")
        if self.special_mode == SpecialMode.SEPARATE and (
            self.special_max is None or self.special_max < 1
        ):
            raise ValueError("SEPARATE mode requires special_max >= 1")
        if self.special_mode == SpecialMode.NONE:
            self.special_max = None
        return self


class StrategySpec(BaseModel):
    """Registered strategy instance inside a study."""

    id: str
    kind: str  # e.g. "random", "frequency"
    tickets_per_period: int = Field(default=5, ge=1)
    params: dict[str, Any] = Field(default_factory=dict)
    seed: int = 0


class FormalEndpointSpec(BaseModel):
    """Serializable formal endpoint config (alpha-spending)."""

    enabled: bool = False
    primary_strategy_id: str | None = None
    checkpoints: dict[int, float] = Field(default_factory=lambda: {26: 0.005, 52: 0.020})
    primary_only_for_claim: bool = True


class ExperimentSpec(BaseModel):
    """Immutable experiment identity. Change params → new experiment_id."""

    experiment_id: str
    domain: str
    game: GameSpec
    strategies: list[StrategySpec] = Field(default_factory=list)
    null_portfolios: int = Field(default=200, ge=1)
    null_seed: int = 42
    formal: FormalEndpointSpec = Field(default_factory=FormalEndpointSpec)
    created_at: datetime = Field(default_factory=utc_now)
    notes: str = (
        "Negative expected value domain. Formal question: "
        "is any strategy distinguishable from pure chance at equal cost?"
    )

    def strategy_ids(self) -> list[str]:
        return [s.id for s in self.strategies]


class FreezeRecord(BaseModel):
    """Pre-outcome lock. Outcomes after freeze must not rewrite this row."""

    schema_version: str = "3"
    type: str = "freeze"
    experiment_id: str
    period: str
    strategy_id: str
    tickets: list[Ticket]
    content_hash: str
    code_fingerprint: str
    experiment_hash: str = ""
    history_hash: str = ""
    registration_mode: RegistrationMode | None = None
    history_anchor: HistoryAnchor | None = None
    outcome_hash: str | None = None
    frozen_at: datetime = Field(default_factory=utc_now)
    late: bool = False
    meta: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def registration_evidence(self) -> FreezeRecord:
        if self.schema_version != "3":
            return self
        if self.registration_mode is None or self.history_anchor is None:
            raise ValueError("v3 freeze requires registration_mode and history_anchor")
        if self.registration_mode == RegistrationMode.PRE_OUTCOME:
            if self.outcome_hash is not None or self.late:
                raise ValueError("pre_outcome freeze cannot seal an outcome or be late")
        elif self.outcome_hash is None or not self.late:
            raise ValueError("backtest freeze requires outcome_hash and late=true")
        return self


class PortfolioResult(BaseModel):
    """P&L for one portfolio (strategy arm or one null clone)."""

    portfolio_id: str
    kind: str  # "strategy" | "null"
    cost: float
    payout: float
    hits: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def pnl(self) -> float:
        return self.payout - self.cost


class SettleRecord(BaseModel):
    """Post-outcome settlement for one period."""

    schema_version: str = "2"
    type: str = "settle"
    experiment_id: str
    period: str
    draw: Draw
    strategy_results: list[PortfolioResult]
    null_results: list[PortfolioResult]
    registration_mode: SettlementMode | None = None
    freeze_content_hashes: list[str] = Field(default_factory=list)
    settled_at: datetime = Field(default_factory=utc_now)
    content_hash: str

    @model_validator(mode="after")
    def settlement_evidence(self) -> SettleRecord:
        if self.schema_version == "2":
            if self.registration_mode is None:
                raise ValueError("v2 settle requires registration_mode")
            if not self.freeze_content_hashes:
                raise ValueError("v2 settle requires freeze_content_hashes")
            if self.freeze_content_hashes != sorted(self.freeze_content_hashes):
                raise ValueError("freeze_content_hashes must be sorted")
        return self


class ReportSummary(BaseModel):
    """Human-facing summary; claim language is constrained."""

    experiment_id: str
    periods_settled: int
    claim_status: ClaimStatus = ClaimStatus.DESCRIPTIVE_ONLY
    strategy_cum_pnl: dict[str, float]
    null_mean_cum_pnl: float
    strategy_percentiles: dict[str, float]  # empirical percentile vs null cum PnL
    # strategy_id -> sequential evidence dict
    sequential_evidence: dict[str, dict[str, Any]] = Field(default_factory=dict)
    formal_endpoint: dict[str, Any] = Field(default_factory=dict)
    registration_counts: dict[str, int] = Field(default_factory=dict)
    formal_eligible_periods: int = 0
    warnings: list[str] = Field(default_factory=list)
    forbidden_hits: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=utc_now)
    disclaimer: str = (
        "Descriptive only unless a pre-registered formal endpoint is open. "
        "This tool does not forecast outcomes or encourage real-money wagering."
    )
