"""Frequency-weighted sampler using only history strictly before the period."""

from __future__ import annotations

import random
from collections import Counter

from nullbench.core.models import Draw, GameSpec, StrategySpec, Ticket


def propose_frequency(
    game: GameSpec,
    spec: StrategySpec,
    history: list[Draw],
    period_seed: int,
) -> list[Ticket]:
    window = int(spec.params.get("window", 50))
    alpha = float(spec.params.get("alpha", 1.0))  # Laplace smoothing
    use = history[-window:] if window > 0 else history

    main_counts = Counter({n: 0 for n in range(1, game.main_max + 1)})
    for d in use:
        main_counts.update(d.numbers)
    main_weights = [main_counts[n] + alpha for n in range(1, game.main_max + 1)]

    special_weights: list[float] | None = None
    if game.special_max is not None:
        sp_counts = Counter({n: 0 for n in range(1, game.special_max + 1)})
        for d in use:
            if d.special is not None:
                sp_counts[d.special] += 1
        special_weights = [sp_counts[n] + alpha for n in range(1, game.special_max + 1)]

    rng = random.Random(period_seed ^ spec.seed ^ 0xF4E9)
    tickets: list[Ticket] = []
    seen: set[tuple[int, ...]] = set()
    attempts = 0
    while len(tickets) < spec.tickets_per_period and attempts < 20_000:
        attempts += 1
        nums = _weighted_sample_without_replacement(
            rng, list(range(1, game.main_max + 1)), main_weights, game.main_count
        )
        nums_t = tuple(sorted(nums))
        special = None
        if special_weights is not None and game.special_max is not None:
            special = _weighted_choice(rng, list(range(1, game.special_max + 1)), special_weights)
        key = nums_t + ((special,) if special is not None else ())
        if key in seen:
            continue
        seen.add(key)
        tickets.append(
            Ticket(numbers=list(nums_t), special=special, label=f"freq-{len(tickets)+1}")
        )
    if len(tickets) < spec.tickets_per_period:
        raise RuntimeError("failed to sample unique frequency tickets")
    return tickets


def _weighted_choice(rng: random.Random, items: list[int], weights: list[float]) -> int:
    total = sum(weights)
    r = rng.random() * total
    acc = 0.0
    for item, w in zip(items, weights):
        acc += w
        if r <= acc:
            return item
    return items[-1]


def _weighted_sample_without_replacement(
    rng: random.Random,
    items: list[int],
    weights: list[float],
    k: int,
) -> list[int]:
    pool_i = list(range(len(items)))
    pool_w = list(weights)
    chosen: list[int] = []
    for _ in range(k):
        total = sum(pool_w)
        r = rng.random() * total
        acc = 0.0
        pick = 0
        for j, w in enumerate(pool_w):
            acc += w
            if r <= acc:
                pick = j
                break
        chosen.append(items[pool_i[pick]])
        pool_i.pop(pick)
        pool_w.pop(pick)
    return chosen
