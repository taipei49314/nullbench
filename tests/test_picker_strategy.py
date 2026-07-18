"""出號與權重系統測試：席位分配、冪等凍結、可重現性、權重數學。"""
from datetime import datetime
from pathlib import Path

import pytest

from engine import strategy
from engine.games import SUPER, LOTTO649
from engine.ledger import Ledger, TAIPEI
from engine.picker import (
    GAMES, build_official, existing_picks, generate, null_tickets,
    reproduce_check, target_week, first_draw_dt,
)
from engine.store import DrawStore

DATA = Path(__file__).parent.parent / "data"
needs_data = pytest.mark.skipif(not (DATA / "raw").exists(), reason="需要已 ingest 的歷史資料")


@pytest.fixture()
def store():
    return DrawStore(DATA)


def test_allocate_seats_largest_remainder():
    w = {"a": 0.25, "b": 0.25, "c": 0.25, "d": 0.25}
    assert strategy.allocate_seats(w) == {"a": 1, "b": 1, "c": 1, "d": 1}
    w = {"a": 0.60, "b": 0.20, "c": 0.15, "d": 0.05}
    alloc = strategy.allocate_seats(w)
    assert sum(alloc.values()) == 4 and alloc["a"] == 2
    # 平手依字典序
    w = {"b": 0.5, "a": 0.5, "c": 0.0, "d": 0.0}
    alloc = strategy.allocate_seats(w)
    assert alloc == {"a": 2, "b": 2, "c": 0, "d": 0}


def test_update_weights_math():
    before = dict(strategy.UNIFORM)
    scores = {"hot_hunter": 0.4, "cold_keeper": -0.4, "balance_engineer": 0.0, "antipop_taoist": 0.0}
    after = strategy.update_weights(before, scores, burn_in=False)
    assert abs(sum(after.values()) - 1.0) < 1e-9
    assert after["hot_hunter"] > after["balance_engineer"] > after["cold_keeper"]
    lo, hi = 0.05, 0.60
    assert all(lo - 1e-9 <= v <= hi + 1e-9 for v in after.values())
    assert strategy.update_weights(before, scores, burn_in=True) == strategy.UNIFORM


def test_percentile_rank_average_ties():
    assert strategy.percentile_rank(0, [0] * 100) == pytest.approx(0.5, abs=0.01)
    assert strategy.percentile_rank(100, list(range(100))) > 0.95
    assert strategy.percentile_rank(-5, list(range(100))) < 0.05


def test_target_week_and_cutoff():
    sat = datetime(2026, 7, 18, 12, 0, tzinfo=TAIPEI)
    assert target_week(sat) == "2026-W30"  # 週六：本週威力彩已開完 → 下週
    mon_morning = datetime(2026, 7, 20, 10, 0, tzinfo=TAIPEI)
    assert target_week(mon_morning) == "2026-W30"  # 週一早上：首期未開 → 本週
    mon_night = datetime(2026, 7, 20, 21, 0, tzinfo=TAIPEI)
    assert target_week(mon_night) == "2026-W31"  # 週一 20:30 後 → 下週
    assert first_draw_dt(SUPER, "2026-W30").isoformat().startswith("2026-07-20T20:30")


@needs_data
def test_build_official_structure_and_determinism(store):
    history = store.before(SUPER, "2026-07-06")
    alloc = {"antipop_taoist": 1, "balance_engineer": 1, "cold_keeper": 1, "hot_hunter": 1}
    t1 = build_official(SUPER, history, "2026-W28", alloc)
    t2 = build_official(SUPER, history, "2026-W28", alloc)
    assert t1 == t2
    assert len(t1) == 5
    assert t1[0]["persona"] == "random_monk" and t1[0]["slot"] == 1
    sets = [frozenset(t["numbers"]) for t in t1]
    assert len(set(sets)) == 5 or any(t.get("dup") for t in t1)


@needs_data
def test_generate_idempotent_and_reproducible(tmp_path, store):
    picks = Ledger(tmp_path / "picks.jsonl")
    weights = Ledger(tmp_path / "weights.jsonl")
    now = datetime(2026, 7, 18, 12, 0, tzinfo=TAIPEI)
    r1 = generate(picks, weights, store, now, week_id="2026-W28")
    assert all(not r["existing"] for r in r1.values())
    r2 = generate(picks, weights, store, now, week_id="2026-W28")
    assert all(r["existing"] for r in r2.values())
    for game in GAMES:
        assert r1[game]["event"]["content_hash"] == r2[game]["event"]["content_hash"]
        assert reproduce_check(r1[game]["event"], store)
        assert r1[game]["event"]["late"] is True  # 事後補出 → LATE
        assert len(r1[game]["event"]["tickets"]) == 5
        assert len(r1[game]["event"]["shadow"]) == 5
    assert picks.verify_chain()


def test_null_tickets_deterministic():
    n1 = null_tickets(SUPER, "2026-W30")
    n2 = null_tickets(SUPER, "2026-W30")
    assert n1 == n2
    assert len(n1) == 200 and all(len(p) == 5 for p in n1)
    assert n1[0] != n1[1]  # 不同 port 不同票
