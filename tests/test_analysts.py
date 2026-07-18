"""人格測試：決定性（同種子位元級一致）、合法性、約束滿足。"""
import random
from pathlib import Path

import pytest

from engine.analysts import PERSONAS, _weighted_sample, balance_engineer, _balance_ok
from engine.games import SUPER, LOTTO649, validate_pick
from engine.seeds import rng_for
from engine.store import DrawStore

DATA = Path(__file__).parent.parent / "data"
needs_data = pytest.mark.skipif(not (DATA / "raw").exists(), reason="需要已 ingest 的歷史資料")


@pytest.fixture(scope="module")
def history():
    store = DrawStore(DATA)
    return {SUPER: store.before(SUPER, "2026-07-13"),
            LOTTO649: store.before(LOTTO649, "2026-07-13")}


@needs_data
@pytest.mark.parametrize("pid", sorted(PERSONAS))
@pytest.mark.parametrize("game", [SUPER, LOTTO649])
def test_persona_deterministic_and_valid(pid, game, history):
    out1 = PERSONAS[pid](game, history[game], rng_for(game, "2026-W29", "official", pid, 1))
    out2 = PERSONAS[pid](game, history[game], rng_for(game, "2026-W29", "official", pid, 1))
    assert out1 == out2, "同種子必須位元級一致"
    validate_pick(game, out1["numbers"], out1["special"])
    assert out1["numbers"] == sorted(out1["numbers"])
    # 不同 retry nonce 應產生不同亂數流（極高機率不同票）
    out3 = PERSONAS[pid](game, history[game], rng_for(game, "2026-W29", "official", pid, 1, retry=1))
    assert (out1["numbers"], out1["special"]) != (out3["numbers"], out3["special"]) or pid == "balance_engineer"


@needs_data
def test_personas_work_with_empty_history():
    for pid, fn in PERSONAS.items():
        out = fn(SUPER, [], rng_for(SUPER, "2026-W29", "shadow", pid, 1))
        validate_pick(SUPER, out["numbers"], out["special"])


@needs_data
def test_balance_constraints_hold(history):
    out = balance_engineer(SUPER, history[SUPER], rng_for(SUPER, "2026-W29", "official", "balance_engineer", 2))
    assert not out["meta"].get("relaxed")
    nums = out["numbers"]
    assert _balance_ok(nums, SUPER, {"sum", "odd", "consecutive", "tails", "range"})
    assert 96 <= sum(nums) <= 138


def test_weighted_sample_properties():
    rng = random.Random(42)
    w = {n: 1.0 for n in range(1, 39)}
    out = _weighted_sample(rng, w, 6)
    assert len(out) == 6 and len(set(out)) == 6 and out == sorted(out)
    # 極端權重：重號碼幾乎必中
    rng = random.Random(1)
    w = {1: 10000.0, **{n: 0.0001 for n in range(2, 39)}}
    hits = sum(1 in _weighted_sample(random.Random(s), w, 6) for s in range(30))
    assert hits == 30
