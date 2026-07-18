"""帳本測試：append-only、末行毀損容忍、中段毀損 fail-closed。"""
import pytest

from engine.ledger import Ledger


def test_append_and_read(tmp_path):
    led = Ledger(tmp_path / "ledger.jsonl")
    led.append("picks", {"week": "2026-07-13", "n": 5})
    led.append("check", {"week": "2026-07-13", "hits": 0})
    events = led.read_all()
    assert [e["type"] for e in events] == ["picks", "check"]
    assert all("ts" in e for e in events)
    assert led.events_of("picks")[0]["n"] == 5


def test_tail_corruption_tolerated(tmp_path):
    path = tmp_path / "ledger.jsonl"
    led = Ledger(path)
    led.append("picks", {"a": 1})
    with open(path, "a", encoding="utf-8") as f:
        f.write('{"type": "check", "trunc')  # 斷電殘行
    events = led.read_all()
    assert len(events) == 1


def test_mid_corruption_fails_closed(tmp_path):
    path = tmp_path / "ledger.jsonl"
    led = Ledger(path)
    led.append("picks", {"a": 1})
    with open(path, "a", encoding="utf-8") as f:
        f.write("GARBAGE NOT JSON\n")
    led.append("check", {"b": 2})
    with pytest.raises(RuntimeError):
        led.read_all()


def test_missing_file_is_empty(tmp_path):
    led = Ledger(tmp_path / "nope.jsonl")
    assert led.read_all() == []
