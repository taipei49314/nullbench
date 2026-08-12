"""Domain-agnostic hit scoring and conservative payout lookup."""

from __future__ import annotations

from nullbench.core.models import Draw, GameSpec, Ticket


def hit_key(main_hits: int, special_hit: bool, has_special: bool) -> str:
    if has_special and special_hit:
        return f"{main_hits}+s"
    return str(main_hits)


def score_ticket(game: GameSpec, ticket: Ticket, draw: Draw) -> dict:
    main_hits = len(set(ticket.numbers) & set(draw.numbers))
    has_special = game.special_max is not None
    special_hit = False
    if has_special and ticket.special is not None and draw.special is not None:
        special_hit = ticket.special == draw.special
    key = hit_key(main_hits, special_hit, has_special)
    payout = float(game.prize_table.get(key, 0.0))
    # Also try without +s if table only has bare counts
    if payout == 0.0 and special_hit:
        payout = float(game.prize_table.get(str(main_hits), 0.0))
    return {
        "main_hits": main_hits,
        "special_hit": special_hit,
        "prize_key": key,
        "payout": payout,
        "numbers": ticket.numbers,
        "special": ticket.special,
    }


def portfolio_payout(game: GameSpec, tickets: list[Ticket], draw: Draw) -> tuple[float, list[dict]]:
    hits: list[dict] = []
    total = 0.0
    for t in tickets:
        h = score_ticket(game, t, draw)
        hits.append(h)
        total += h["payout"]
    return total, hits


def portfolio_cost(game: GameSpec, n_tickets: int) -> float:
    return game.ticket_cost * n_tickets
