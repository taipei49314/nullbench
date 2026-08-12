"""Domain packs (game rules + optional data loaders)."""

from __future__ import annotations

from types import ModuleType

from nullbench.core.models import GameSpec
from nullbench.domains import demo649, taiwan_lotto649, taiwan_super

REGISTRY: dict[str, ModuleType] = {
    "demo649": demo649,
    "taiwan_super": taiwan_super,
    "taiwan_lotto649": taiwan_lotto649,
}


def get_domain(domain_id: str) -> ModuleType:
    try:
        return REGISTRY[domain_id]
    except KeyError as e:
        known = ", ".join(sorted(REGISTRY))
        raise KeyError(f"unknown domain {domain_id!r}; known: {known}") from e


def game_for(domain_id: str) -> GameSpec:
    return get_domain(domain_id).GAME


def list_domains() -> list[str]:
    return sorted(REGISTRY)
