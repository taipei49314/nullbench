"""Built-in + entry-point strategy implementations."""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import Callable

from nullbench.core.models import Draw, GameSpec, StrategySpec, Ticket
from nullbench.strategies.frequency import propose_frequency
from nullbench.strategies.random_uniform import propose_random

ProposeFn = Callable[[GameSpec, StrategySpec, list[Draw], int], list[Ticket]]

_BUILTIN: dict[str, ProposeFn] = {
    "random": propose_random,
    "frequency": propose_frequency,
}

_PLUGIN_CACHE: dict[str, ProposeFn] | None = None


def _load_plugins() -> dict[str, ProposeFn]:
    global _PLUGIN_CACHE
    if _PLUGIN_CACHE is not None:
        return _PLUGIN_CACHE
    found: dict[str, ProposeFn] = {}
    try:
        eps = entry_points(group="nullbench.strategies")
    except TypeError:
        # Python <3.12 older API
        eps = entry_points().get("nullbench.strategies", [])  # type: ignore[assignment]
    for ep in eps:
        try:
            fn = ep.load()
            found[ep.name] = fn
        except Exception:
            continue
    _PLUGIN_CACHE = found
    return found


def list_strategies() -> list[str]:
    names = set(_BUILTIN) | set(_load_plugins())
    return sorted(names)


def get_strategy(kind: str) -> ProposeFn:
    if kind in _BUILTIN:
        return _BUILTIN[kind]
    plugins = _load_plugins()
    if kind in plugins:
        return plugins[kind]
    known = ", ".join(list_strategies())
    raise KeyError(f"unknown strategy kind {kind!r}; known: {known}")


def register_strategy(kind: str, fn: ProposeFn) -> None:
    """Runtime registration (tests / notebooks)."""
    _BUILTIN[kind] = fn
    global _PLUGIN_CACHE
    _PLUGIN_CACHE = None
