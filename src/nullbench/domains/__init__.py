"""Domain packs — registry with product metadata."""

from __future__ import annotations

from types import ModuleType

from nullbench.core.models import GameSpec
from nullbench.domains import demo649, taiwan_lotto649, taiwan_super
from nullbench.errors import DomainError
from nullbench.protocols import DomainInfo

_REGISTRY: dict[str, DomainInfo] = {
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

# Back-compat module map
REGISTRY: dict[str, ModuleType] = {k: v.module for k, v in _REGISTRY.items()}


def get_domain_info(domain_id: str) -> DomainInfo:
    try:
        return _REGISTRY[domain_id]
    except KeyError as e:
        known = ", ".join(list_domains())
        raise DomainError(
            f"unknown domain {domain_id!r}",
            hint=f"known domains: {known}. Run: nullbench domains",
        ) from e


def get_domain(domain_id: str) -> ModuleType:
    return get_domain_info(domain_id).module


def game_for(domain_id: str) -> GameSpec:
    return get_domain(domain_id).GAME


def list_domains() -> list[str]:
    return sorted(_REGISTRY)


def list_domain_infos() -> list[DomainInfo]:
    return [_REGISTRY[k] for k in list_domains()]


def domain_needs_network(domain_id: str) -> bool:
    return get_domain_info(domain_id).network
