"""Offline 6/49-style demo domain — no network, synthetic history."""

from __future__ import annotations

import random
from pathlib import Path

from nullbench.core.models import Draw, GameSpec

DOMAIN_ID = "demo649"

GAME = GameSpec(
    id="demo649",
    name="Demo 6/49",
    main_count=6,
    main_max=49,
    special_max=None,
    ticket_cost=50.0,
    prize_table={
        "3": 400.0,
        "4": 2000.0,
        "5": 50_000.0,
        "6": 10_000_000.0,
    },
    description=(
        "Synthetic 6-of-49 lab game for tutorials. "
        "Prizes are illustrative, not any real lottery."
    ),
)


def generate_synthetic_draws(
    n: int = 120,
    seed: int = 2026,
    period_prefix: str = "P",
) -> list[Draw]:
    """Deterministic synthetic history for offline demos and tests."""
    rng = random.Random(seed)
    draws: list[Draw] = []
    for i in range(1, n + 1):
        nums = sorted(rng.sample(range(1, GAME.main_max + 1), GAME.main_count))
        draws.append(
            Draw(
                period=f"{period_prefix}{i:04d}",
                numbers=nums,
                special=None,
                date=None,
                meta={"synthetic": True, "seed": seed},
            )
        )
    return draws


def write_demo_data(path: Path, n: int = 120, seed: int = 2026) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    draws = generate_synthetic_draws(n=n, seed=seed)
    # JSONL
    lines = [d.model_dump_json() for d in draws]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def load_draws(path: Path) -> list[Draw]:
    rows: list[Draw] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(Draw.model_validate_json(line))
    return rows
