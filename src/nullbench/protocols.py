"""Stable extension contracts for domains and strategies.

Implementers can type-check against these Protocols without importing
pipeline internals. Entry points still use callables with the same signature.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from nullbench.core.models import Draw, GameSpec, StrategySpec, Ticket


@runtime_checkable
class DomainPack(Protocol):
    """A domain provides a GameSpec and optional data bootstrap."""

    DOMAIN_ID: str
    GAME: GameSpec

    def prepare_data(self, study_data_dir: Path, *, max_months: int | None = None) -> int:
        """Fetch/write draws; return count. Optional for offline domains."""
        ...


@runtime_checkable
class OfflineDomainPack(Protocol):
    DOMAIN_ID: str
    GAME: GameSpec

    def write_demo_data(self, path: Path, n: int = 120, seed: int = 2026) -> Path: ...


@runtime_checkable
class StrategyFn(Protocol):
    """Propose tickets using only history strictly before the target period."""

    def __call__(
        self,
        game: GameSpec,
        spec: StrategySpec,
        history: list[Draw],
        period_seed: int,
    ) -> list[Ticket]: ...


class DomainInfo:
    """Registry metadata for product discovery (CLI domains --verbose)."""

    __slots__ = ("id", "name", "network", "description", "module")

    def __init__(
        self,
        *,
        id: str,
        name: str,
        network: bool,
        description: str,
        module: Any,
    ) -> None:
        self.id = id
        self.name = name
        self.network = network
        self.description = description
        self.module = module
