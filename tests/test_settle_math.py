from __future__ import annotations

from nullbench.core.models import Draw, Ticket
from nullbench.core.settle_math import score_ticket
from nullbench.domains.demo649 import GAME


def test_score_ticket_hits() -> None:
    t = Ticket(numbers=[1, 2, 3, 4, 5, 6])
    d = Draw(period="P1", numbers=[1, 2, 3, 10, 11, 12])
    h = score_ticket(GAME, t, d)
    assert h["main_hits"] == 3
    assert h["payout"] == 400.0
