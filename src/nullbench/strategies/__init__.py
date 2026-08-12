"""Built-in strategy implementations."""

from __future__ import annotations

from typing import Callable

from nullbench.core.models import Draw, GameSpec, StrategySpec, Ticket
from nullbench.strategies.frequency import propose_frequency
from nullbench.strategies.random_uniform import propose_random

ProposeFn = Callable[[GameSpec, StrategySpec, list[Draw], int], list[Ticket]]

REGISTRY: dict[str, ProposeFn] = {
    "random": propose_random,
    "frequency": propose_frequency,
}


def get_strategy(kind: str) -> ProposeFn:
    try:
        return REGISTRY[kind]
    except KeyError as e:
        known = ", ".join(sorted(REGISTRY))
        raise KeyError(f"unknown strategy kind {kind!r}; known: {known}") from e
