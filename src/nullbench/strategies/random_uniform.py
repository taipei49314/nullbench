"""Uniform random tickets — built-in live null persona."""

from __future__ import annotations

import random

from nullbench.core.models import Draw, GameSpec, StrategySpec, Ticket


def propose_random(
    game: GameSpec,
    spec: StrategySpec,
    history: list[Draw],
    period_seed: int,
) -> list[Ticket]:
    """history is accepted for API uniformity; random ignores it (no peek)."""
    del history  # explicit: no look-ahead channel
    from nullbench.core.hashing import sha256_hex

    id_mix = int(sha256_hex(spec.id)[:8], 16)
    rng = random.Random(period_seed ^ spec.seed ^ id_mix)
    tickets: list[Ticket] = []
    seen: set[tuple[int, ...]] = set()
    attempts = 0
    while len(tickets) < spec.tickets_per_period and attempts < 10_000:
        attempts += 1
        nums = tuple(sorted(rng.sample(range(1, game.main_max + 1), game.main_count)))
        special = None
        if game.special_max is not None:
            special = rng.randint(1, game.special_max)
        key = nums + ((special,) if special is not None else ())
        if key in seen:
            continue
        seen.add(key)
        tickets.append(Ticket(numbers=list(nums), special=special, label=f"random-{len(tickets)+1}"))
    if len(tickets) < spec.tickets_per_period:
        raise RuntimeError("failed to sample unique random tickets")
    return tickets
