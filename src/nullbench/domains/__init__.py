"""Domain packs (game rules + optional data loaders)."""

from __future__ import annotations

from nullbench.core.models import GameSpec
from nullbench.domains import demo649

REGISTRY = {
    "demo649": demo649,
}


def get_domain(domain_id: str):
    try:
        return REGISTRY[domain_id]
    except KeyError as e:
        known = ", ".join(sorted(REGISTRY))
        raise KeyError(f"unknown domain {domain_id!r}; known: {known}") from e


def game_for(domain_id: str) -> GameSpec:
    return get_domain(domain_id).GAME
