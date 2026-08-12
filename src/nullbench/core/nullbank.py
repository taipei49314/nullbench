"""Equal-cost pure-chance portfolios for null comparison."""

from __future__ import annotations

import random

from nullbench.core.hashing import sha256_hex
from nullbench.core.models import Draw, GameSpec, PortfolioResult, SpecialMode, Ticket
from nullbench.core.settle_math import portfolio_cost, portfolio_payout


def sample_null_tickets(
    game: GameSpec,
    n_tickets: int,
    portfolio_index: int,
    period: str,
    base_seed: int,
) -> list[Ticket]:
    period_mix = int(sha256_hex(period)[:8], 16)
    rng = random.Random(base_seed ^ (portfolio_index * 1_000_003) ^ period_mix)
    tickets: list[Ticket] = []
    seen: set[tuple[int, ...]] = set()
    attempts = 0
    while len(tickets) < n_tickets and attempts < 20_000:
        attempts += 1
        nums = tuple(sorted(rng.sample(range(1, game.main_max + 1), game.main_count)))
        special = None
        if game.special_mode == SpecialMode.SEPARATE and game.special_max is not None:
            special = rng.randint(1, game.special_max)
        key = nums + ((special,) if special is not None else ())
        if key in seen:
            continue
        seen.add(key)
        tickets.append(Ticket(numbers=list(nums), special=special))
    if len(tickets) < n_tickets:
        raise RuntimeError("null sampler exhausted")
    return tickets


def evaluate_null_bank(
    game: GameSpec,
    draw: Draw,
    n_tickets: int,
    n_portfolios: int,
    base_seed: int,
) -> list[PortfolioResult]:
    results: list[PortfolioResult] = []
    cost = portfolio_cost(game, n_tickets)
    for i in range(n_portfolios):
        tickets = sample_null_tickets(game, n_tickets, i, draw.period, base_seed)
        payout, hits = portfolio_payout(game, tickets, draw)
        results.append(
            PortfolioResult(
                portfolio_id=f"null-{i:04d}",
                kind="null",
                cost=cost,
                payout=payout,
                hits=hits,
            )
        )
    return results
