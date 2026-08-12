"""Domain-agnostic hit scoring and conservative payout lookup."""

from __future__ import annotations

from nullbench.core.models import Draw, GameSpec, SpecialMode, Ticket


def hit_key(main_hits: int, special_hit: bool, mode: SpecialMode) -> str:
    if mode != SpecialMode.NONE and special_hit:
        return f"{main_hits}+s"
    return str(main_hits)


def special_hit(game: GameSpec, ticket: Ticket, draw: Draw) -> bool:
    if game.special_mode == SpecialMode.NONE:
        return False
    if game.special_mode == SpecialMode.SEPARATE:
        if ticket.special is None or draw.special is None:
            return False
        return ticket.special == draw.special
    if game.special_mode == SpecialMode.FROM_MAIN_POOL:
        # e.g. 大樂透：特別號出自主號池，票上任一主號命中特別號
        if draw.special is None:
            return False
        return draw.special in set(ticket.numbers)
    return False


def score_ticket(game: GameSpec, ticket: Ticket, draw: Draw) -> dict:
    main_hits = len(set(ticket.numbers) & set(draw.numbers))
    sp = special_hit(game, ticket, draw)
    key = hit_key(main_hits, sp, game.special_mode)
    payout = float(game.prize_table.get(key, 0.0))
    # Fallback: bare count if +s key missing
    if payout == 0.0 and sp:
        payout = float(game.prize_table.get(str(main_hits), 0.0))
    return {
        "main_hits": main_hits,
        "special_hit": sp,
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
