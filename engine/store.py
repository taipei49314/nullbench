"""開獎資料儲存與「週」的時間學。

一週的定義：週一 00:00 起算，week_id = 該週週一的 YYYY-MM-DD。
本週票券覆蓋該週內該遊戲的所有期數（威力彩：一、四；大樂透：二、五）。
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from .fetch import load_all_draws
from .games import DRAW_WEEKDAYS, Draw


def week_id_of(d: date) -> str:
    monday = d - timedelta(days=d.weekday())
    return monday.isoformat()


def week_dates(week_id: str, game: str) -> list[str]:
    """該週該遊戲的預定開獎日期清單。"""
    monday = date.fromisoformat(week_id)
    return [(monday + timedelta(days=wd)).isoformat() for wd in DRAW_WEEKDAYS[game]]


def draws_in_week(draws: list[Draw], week_id: str) -> list[Draw]:
    monday = date.fromisoformat(week_id)
    sunday = monday + timedelta(days=6)
    lo, hi = monday.isoformat(), sunday.isoformat()
    return [d for d in draws if lo <= d.date <= hi]


class DrawStore:
    """快取上的唯讀視圖。"""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self._cache: dict[str, list[Draw]] = {}

    def draws(self, game: str) -> list[Draw]:
        if game not in self._cache:
            self._cache[game] = load_all_draws(game, self.data_dir)
        return self._cache[game]

    def latest(self, game: str) -> Draw | None:
        ds = self.draws(game)
        return ds[-1] if ds else None

    def before(self, game: str, cutoff_date: str) -> list[Draw]:
        """cutoff_date（不含）之前的所有期數——分析用，防止未來資料洩漏。"""
        return [d for d in self.draws(game) if d.date < cutoff_date]
