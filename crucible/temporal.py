"""Small, deterministic temporal-property declarations.

The checker owns the graph search.  This module deliberately only describes
properties and fairness constraints so it does not introduce a second source
of exploration order.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .state import State


Predicate = Callable[[State], bool]


class TemporalProperty:
    """Base class for properties accepted by :class:`crucible.Checker`."""

    __slots__ = ("name", "predicate", "kind")

    def __init__(self, name: str, predicate: Predicate, kind: str) -> None:
        if not isinstance(name, str) or not name:
            raise ValueError("temporal property name must be a non-empty str")
        if not callable(predicate):
            raise TypeError("temporal property predicate must be callable")
        self.name = name
        self.predicate = predicate
        self.kind = kind

    def holds(self, state: State) -> bool:
        return bool(self.predicate(state))

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.name!r})"


class Always(TemporalProperty):
    def __init__(self, name: str, predicate: Predicate) -> None:
        super().__init__(name, predicate, "always")


class Eventually(TemporalProperty):
    def __init__(self, name: str, predicate: Predicate) -> None:
        super().__init__(name, predicate, "eventually")


class LeadsTo(TemporalProperty):
    def __init__(self, name: str, trigger: Predicate, goal: Predicate) -> None:
        super().__init__(name, trigger, "leads_to")
        self.goal = goal


@dataclass(frozen=True)
class WeakFairness:
    """A weak-fairness assumption for one named action."""

    action: str

    def __post_init__(self) -> None:
        if not isinstance(self.action, str) or not self.action:
            raise ValueError("fairness action must be a non-empty str")


def weak_fair(action: str) -> WeakFairness:
    return WeakFairness(action)


__all__ = [
    "Always",
    "Eventually",
    "LeadsTo",
    "TemporalProperty",
    "WeakFairness",
    "weak_fair",
]
