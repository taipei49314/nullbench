"""Domain packs — built-in registry + entry-point plugins."""

from __future__ import annotations

from importlib.metadata import entry_points
from types import ModuleType
from typing import Any

from nullbench.core.models import GameSpec
from nullbench.domains import demo649, taiwan_lotto649, taiwan_super
from nullbench.errors import DomainError
from nullbench.protocols import DomainInfo

_BUILTIN: dict[str, DomainInfo] = {
    "demo649": DomainInfo(
        id="demo649",
        name=demo649.GAME.name,
        network=False,
        description=demo649.GAME.description or "Offline synthetic 6/49 lab game",
        module=demo649,
    ),
    "taiwan_super": DomainInfo(
        id="taiwan_super",
        name=taiwan_super.GAME.name,
        network=True,
        description=taiwan_super.GAME.description,
        module=taiwan_super,
    ),
    "taiwan_lotto649": DomainInfo(
        id="taiwan_lotto649",
        name=taiwan_lotto649.GAME.name,
        network=True,
        description=taiwan_lotto649.GAME.description,
        module=taiwan_lotto649,
    ),
}

_PLUGIN_CACHE: dict[str, DomainInfo] | None = None


def _load_plugin_domains() -> dict[str, DomainInfo]:
    """Load domains from entry points group ``nullbench.domains``.

    Entry target may be:
    - a module with DOMAIN_ID + GAME (+ optional prepare_data / write_demo_data)
    - a zero-arg callable returning such a module or DomainInfo
    """
    global _PLUGIN_CACHE
    if _PLUGIN_CACHE is not None:
        return _PLUGIN_CACHE
    found: dict[str, DomainInfo] = {}
    try:
        eps = entry_points(group="nullbench.domains")
    except TypeError:
        eps = entry_points().get("nullbench.domains", [])  # type: ignore[assignment]
    for ep in eps:
        try:
            obj = ep.load()
            if callable(obj) and not hasattr(obj, "GAME"):
                obj = obj()
            if isinstance(obj, DomainInfo):
                found[obj.id] = obj
                continue
            mod = obj
            domain_id = getattr(mod, "DOMAIN_ID", ep.name)
            game = getattr(mod, "GAME", None)
            if game is None:
                continue
            network = bool(getattr(mod, "NETWORK", hasattr(mod, "prepare_data")))
            found[domain_id] = DomainInfo(
                id=domain_id,
                name=getattr(game, "name", domain_id),
                network=network,
                description=getattr(game, "description", "") or f"plugin:{ep.name}",
                module=mod,
            )
        except Exception:
            continue
    _PLUGIN_CACHE = found
    return found


def _all() -> dict[str, DomainInfo]:
    merged = dict(_BUILTIN)
    for k, v in _load_plugin_domains().items():
        if k not in merged:  # builtins win on id clash
            merged[k] = v
    return merged


# Back-compat
REGISTRY: dict[str, ModuleType] = {k: v.module for k, v in _BUILTIN.items()}


def get_domain_info(domain_id: str) -> DomainInfo:
    reg = _all()
    try:
        return reg[domain_id]
    except KeyError as e:
        known = ", ".join(list_domains())
        raise DomainError(
            f"unknown domain {domain_id!r}",
            hint=f"known domains: {known}. Run: nullbench domains -v",
        ) from e


def get_domain(domain_id: str) -> Any:
    return get_domain_info(domain_id).module


def game_for(domain_id: str) -> GameSpec:
    return get_domain(domain_id).GAME


def list_domains() -> list[str]:
    return sorted(_all())


def list_domain_infos() -> list[DomainInfo]:
    reg = _all()
    return [reg[k] for k in list_domains()]


def domain_needs_network(domain_id: str) -> bool:
    return get_domain_info(domain_id).network


def register_domain(info: DomainInfo) -> None:
    """Runtime registration (tests / notebooks)."""
    global _PLUGIN_CACHE
    _BUILTIN[info.id] = info
    _PLUGIN_CACHE = None
