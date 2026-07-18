"""抓取解析與週排程測試：以真實 API 月回應快照為夾具。"""
import json
from datetime import date
from pathlib import Path

import pytest

from engine.fetch import parse_month
from engine.games import SUPER, LOTTO649
from engine.store import week_id_of, week_dates, draws_in_week

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_parse_super_month():
    draws = _parse_super()
    assert len(draws) == 9
    assert [d.period for d in draws] == sorted(d.period for d in draws)
    d = draws[-1]  # 115000052
    assert d.period == 115000052
    assert d.numbers == (5, 6, 9, 15, 16, 33)
    assert d.special == 5
    assert 1 <= d.special <= 8
    assert d.date.startswith("2026-06")
    assert "super638JackpotAssign" in d.prizes


def _parse_super():
    return parse_month(SUPER, _load("super_2026-06.json"))


def test_parse_lotto649_month():
    draws = parse_month(LOTTO649, _load("lotto649_2026-06.json"))
    assert len(draws) == 9
    d = [x for x in draws if x.period == 115000066][0]
    assert d.numbers == (4, 10, 16, 29, 36, 45)
    assert d.special == 14
    for x in draws:
        assert len(x.numbers) == 6 and len(set(x.numbers)) == 6
        assert all(1 <= n <= 49 for n in x.numbers)
        assert "jackpotAssign" in x.prizes


def test_all_super_specials_in_range():
    for d in _parse_super():
        assert 1 <= d.special <= 8


def test_week_id_and_dates():
    assert week_id_of(date(2026, 7, 18)) == "2026-07-13"  # 週六 → 該週週一
    assert week_id_of(date(2026, 7, 13)) == "2026-07-13"  # 週一是自己
    assert week_id_of(date(2026, 7, 19)) == "2026-07-13"  # 週日仍屬本週
    assert week_dates("2026-07-13", SUPER) == ["2026-07-13", "2026-07-16"]
    assert week_dates("2026-07-13", LOTTO649) == ["2026-07-14", "2026-07-17"]


def test_draws_in_week_with_real_fixture():
    draws = _parse_super()
    wk = draws_in_week(draws, "2026-06-01")
    assert all("2026-06-01" <= d.date <= "2026-06-07" for d in wk)
    assert len(wk) == 2  # 威力彩每週兩期


def test_parse_rejects_bad_shape():
    raw = _load("super_2026-06.json")
    raw["content"]["superLotto638Res"][0]["drawNumberSize"] = [1, 2, 3]
    with pytest.raises(ValueError):
        parse_month(SUPER, raw)
