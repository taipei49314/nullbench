"""Domain packs — built-in registry + entry-point plugins.

IC-09: list plugin ids from entry-point metadata without ``ep.load()``;
loading happens only after ``assert_plugins_trusted``.
"""

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

_PLUGIN_CACHE: dict[str, DomainInfo] = {}


def _domain_entry_points():
    try:
        return list(entry_points(group="nullbench.domains"))
    except TypeError:
        return list(entry_points().get("nullbench.domains", []) or [])  # type: ignore[attr-defined]


def plugin_domain_names() -> list[str]:
    """Entry-point names without importing plugins (IC-09)."""
    names: list[str] = []
    for ep in _domain_entry_points():
        name = getattr(ep, "name", None)
        if name:
            names.append(str(name))
    return names


def _materialize_domain(ep_name: str, obj: Any) -> DomainInfo | None:
    if callable(obj) and not hasattr(obj, "GAME"):
        obj = obj()
    if isinstance(obj, DomainInfo):
        return obj
    mod = obj
    domain_id = getattr(mod, "DOMAIN_ID", ep_name)
    game = getattr(mod, "GAME", None)
    if game is None:
        return None
    network = bool(getattr(mod, "NETWORK", hasattr(mod, "prepare_data")))
    return DomainInfo(
        id=domain_id,
        name=getattr(game, "name", domain_id),
        network=network,
        description=getattr(game, "description", "") or f"plugin:{ep_name}",
        module=mod,
    )


def _load_plugin_domain(domain_id: str) -> DomainInfo:
    if domain_id in _PLUGIN_CACHE:
        return _PLUGIN_CACHE[domain_id]
    for ep in _domain_entry_points():
        ep_name = str(getattr(ep, "name", "") or "")
        if ep_name != domain_id:
            continue
        try:
            info = _materialize_domain(ep_name, ep.load())
        except Exception as e:
            raise DomainError(
                f"failed to load domain plugin {domain_id!r}",
                hint=str(e),
            ) from e
        if info is None:
            raise DomainError(
                f"domain plugin {domain_id!r} missing GAME",
                hint="entry point must expose GAME / DomainInfo",
            )
        _PLUGIN_CACHE[info.id] = info
        if ep_name != info.id:
            _PLUGIN_CACHE[ep_name] = info
        return info
    raise DomainError(
        f"unknown domain {domain_id!r}",
        hint=f"known domains: {', '.join(list_domains())}. Run: nullbench domains -v",
    )


def _all() -> dict[str, DomainInfo]:
    """Builtins + already-loaded plugins (does not import new EPs)."""
    merged = dict(_BUILTIN)
    for k, v in _PLUGIN_CACHE.items():
        if k not in merged:
            merged[k] = v
    return merged


# Back-compat
REGISTRY: dict[str, ModuleType] = {k: v.module for k, v in _BUILTIN.items()}


def get_domain_info(domain_id: str) -> DomainInfo:
    if domain_id in _BUILTIN:
        return _BUILTIN[domain_id]
    if domain_id in _PLUGIN_CACHE:
        return _PLUGIN_CACHE[domain_id]
    from nullbench.core.integrity import assert_plugins_trusted

    assert_plugins_trusted(domain_id, is_domain=True)
    return _load_plugin_domain(domain_id)


def get_domain(domain_id: str) -> Any:
    return get_domain_info(domain_id).module


def game_for(domain_id: str) -> GameSpec:
    return get_domain(domain_id).GAME


def list_domains() -> list[str]:
    return sorted(set(_BUILTIN) | set(plugin_domain_names()) | set(_PLUGIN_CACHE))


def list_domain_infos() -> list[DomainInfo]:
    """Builtins + loaded plugins. Unloaded EP ids appear in ``list_domains`` only."""
    infos: list[DomainInfo] = []
    seen: set[str] = set()
    for k in list_domains():
        if k in _BUILTIN:
            infos.append(_BUILTIN[k])
            seen.add(k)
        elif k in _PLUGIN_CACHE and _PLUGIN_CACHE[k].id not in seen:
            infos.append(_PLUGIN_CACHE[k])
            seen.add(_PLUGIN_CACHE[k].id)
    return infos


def domain_needs_network(domain_id: str) -> bool:
    return get_domain_info(domain_id).network


def register_domain(info: DomainInfo) -> None:
    """Runtime registration (tests / notebooks)."""
    _BUILTIN[info.id] = info
    _PLUGIN_CACHE.pop(info.id, None)
