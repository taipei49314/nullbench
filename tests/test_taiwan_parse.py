from __future__ import annotations

from datetime import date
from pathlib import Path

from nullbench.core.models import Draw, Ticket
from nullbench.core.settle_math import score_ticket
from nullbench.domains import taiwan_fetch, taiwan_lotto649, taiwan_super


def test_parse_super_month_fixture() -> None:
    raw = {
        "rtCode": 0,
        "content": {
            "superLotto638Res": [
                {
                    "period": "115000058",
                    "lotteryDate": "2026-07-20T00:00:00",
                    "drawNumberSize": [6, 12, 13, 23, 29, 31, 2],
                    "sellAmount": 0,
                    "totalAmount": 0,
                }
            ]
        },
    }
    draws = taiwan_fetch.parse_month("super", raw)
    assert len(draws) == 1
    assert draws[0].period == "115000058"
    assert draws[0].numbers == [6, 12, 13, 23, 29, 31]
    assert draws[0].special == 2


def test_super_special_separate() -> None:
    t = Ticket(numbers=[6, 12, 13, 23, 29, 31], special=2)
    d = Draw(period="1", numbers=[6, 12, 13, 23, 29, 31], special=2)
    h = score_ticket(taiwan_super.GAME, t, d)
    assert h["main_hits"] == 6
    assert h["special_hit"] is True
    assert h["prize_key"] == "6+s"


def test_lotto649_special_from_main() -> None:
    # ticket does not pick special; special hit if special in mains
    t = Ticket(numbers=[1, 2, 3, 4, 5, 7], special=None)
    d = Draw(period="1", numbers=[1, 2, 3, 10, 11, 12], special=7)
    h = score_ticket(taiwan_lotto649.GAME, t, d)
    assert h["main_hits"] == 3
    assert h["special_hit"] is True
    assert h["prize_key"] == "3+s"
    assert h["payout"] == 1000.0


def test_sequential_e_process() -> None:
    from nullbench.scoring.sequential import e_process_from_deltas

    # consistently positive deltas should raise e-value above 1
    ev = e_process_from_deltas([1.0, 1.0, 1.0, 1.0, 1.0])
    assert ev.n == 5
    assert ev.e_value > 1.0


def test_ingest_max_months_takes_most_recent(tmp_path: Path, monkeypatch) -> None:
    """M5.4: max_months is a window ending at *today*, not 2004/2008."""
    seen: list[tuple[int, int]] = []

    def fake_fetch(game_key: str, y: int, m: int) -> dict:
        seen.append((y, m))
        return {"rtCode": 0, "content": {"superLotto638Res": []}}

    monkeypatch.setattr(taiwan_fetch, "_fetch_month_raw", fake_fetch)
    taiwan_fetch.ingest("super", tmp_path, today=date(2026, 9, 3), max_months=2, progress=None)
    assert seen == [(2026, 8), (2026, 9)]
