"""Built-in + entry-point strategy implementations."""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import Callable

from nullbench.core.models import Draw, GameSpec, StrategySpec, Ticket
from nullbench.errors import StrategyError
from nullbench.strategies.frequency import propose_frequency
from nullbench.strategies.random_uniform import propose_random

ProposeFn = Callable[[GameSpec, StrategySpec, list[Draw], int], list[Ticket]]

_BUILTIN: dict[str, ProposeFn] = {
    "random": propose_random,
    "frequency": propose_frequency,
}

_BUILTIN_META: dict[str, str] = {
    "random": "Uniform random tickets (live null persona)",
    "frequency": "Laplace-smoothed frequency sampler (no look-ahead)",
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
        eps = entry_points().get("nullbench.strategies", [])  # type: ignore[assignment]
    for ep in eps:
        try:
            found[ep.name] = ep.load()
        except Exception:
            continue
    _PLUGIN_CACHE = found
    return found


def list_strategies() -> list[str]:
    return sorted(set(_BUILTIN) | set(_load_plugins()))


def list_strategy_infos() -> list[dict[str, str]]:
    plugins = _load_plugins()
    rows = []
    for name in list_strategies():
        if name in _BUILTIN:
            rows.append({"id": name, "source": "builtin", "description": _BUILTIN_META.get(name, "")})
        else:
            rows.append({"id": name, "source": "plugin", "description": "entry-point plugin"})
    return rows


def get_strategy(kind: str) -> ProposeFn:
    if kind in _BUILTIN:
        return _BUILTIN[kind]
    plugins = _load_plugins()
    if kind in plugins:
        return plugins[kind]
    known = ", ".join(list_strategies())
    raise StrategyError(
        f"unknown strategy kind {kind!r}",
        hint=f"known: {known}. Run: nullbench strategies",
    )


def register_strategy(kind: str, fn: ProposeFn) -> None:
    """Runtime registration (tests / notebooks)."""
    _BUILTIN[kind] = fn
    global _PLUGIN_CACHE
    _PLUGIN_CACHE = None
