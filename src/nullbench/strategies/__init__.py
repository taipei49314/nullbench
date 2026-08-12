"""Built-in + entry-point strategy implementations.

IC-09: entry-point *names* may be listed without import; ``ep.load()`` runs only
after ``assert_plugins_trusted`` (or explicit trust env / allowlist).
"""

from __future__ import annotations

from collections.abc import Callable
from importlib.metadata import entry_points

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

# Loaded plugins only (never populate by scanning EPs eagerly)
_PLUGIN_CACHE: dict[str, ProposeFn] = {}


def _strategy_entry_points():
    try:
        return list(entry_points(group="nullbench.strategies"))
    except TypeError:
        return list(entry_points().get("nullbench.strategies", []) or [])  # type: ignore[attr-defined]


def plugin_strategy_names() -> list[str]:
    """Entry-point names without importing plugin modules (IC-09)."""
    names: list[str] = []
    for ep in _strategy_entry_points():
        name = getattr(ep, "name", None)
        if name:
            names.append(str(name))
    return names


def _load_plugin_strategy(kind: str) -> ProposeFn:
    if kind in _PLUGIN_CACHE:
        return _PLUGIN_CACHE[kind]
    for ep in _strategy_entry_points():
        if getattr(ep, "name", None) != kind:
            continue
        fn = ep.load()
        _PLUGIN_CACHE[kind] = fn
        return fn
    raise StrategyError(
        f"unknown strategy kind {kind!r}",
        hint=f"known: {', '.join(list_strategies())}. Run: nullbench strategies",
    )


def list_strategies() -> list[str]:
    return sorted(set(_BUILTIN) | set(plugin_strategy_names()) | set(_PLUGIN_CACHE))


def list_strategy_infos() -> list[dict[str, str]]:
    rows = []
    for name in list_strategies():
        if name in _BUILTIN:
            rows.append(
                {"id": name, "source": "builtin", "description": _BUILTIN_META.get(name, "")}
            )
        else:
            rows.append({"id": name, "source": "plugin", "description": "entry-point plugin"})
    return rows


def get_strategy(kind: str) -> ProposeFn:
    if kind in _BUILTIN:
        return _BUILTIN[kind]
    # Trust gate before import (IC-09) — closes eager ep.load() RCE
    from nullbench.core.integrity import assert_plugins_trusted

    assert_plugins_trusted(kind, is_domain=False)
    return _load_plugin_strategy(kind)


def register_strategy(kind: str, fn: ProposeFn) -> None:
    """Runtime registration (tests / notebooks)."""
    _BUILTIN[kind] = fn
    _PLUGIN_CACHE.pop(kind, None)
