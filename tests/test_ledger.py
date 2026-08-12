from __future__ import annotations

from pathlib import Path

from nullbench.core.ledger import Ledger


def test_ledger_chain(tmp_path: Path) -> None:
    led = Ledger(tmp_path / "e.jsonl")
    led.append({"type": "a", "n": 1})
    led.append({"type": "b", "n": 2})
    ok, msg = led.verify_chain()
    assert ok, msg
    assert len(led) == 2
