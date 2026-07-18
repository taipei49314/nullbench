"""append-only JSONL 帳本：picks / debate / check / weights 事件全記錄。

紀律（承 ai-company ledger.py）：
- 只追加、不改寫；重建狀態一律從頭掃帳本（帳本是唯一事實源）。
- 原子寫入：先寫 tmp 再 replace 不適用於 append，改用「單行寫入＋flush」，
  每行自成合法 JSON，尾行毀損時讀取端丟棄殘行並警告。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

TAIPEI = timezone(timedelta(hours=8))


def now_iso() -> str:
    return datetime.now(TAIPEI).isoformat(timespec="seconds")


class Ledger:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event_type: str, payload: dict) -> dict:
        event = {"ts": now_iso(), "type": event_type, **payload}
        line = json.dumps(event, ensure_ascii=False)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
        return event

    def read_all(self) -> list[dict]:
        if not self.path.exists():
            return []
        events = []
        with open(self.path, encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    # 只容忍最後一行毀損（斷電殘行）；中段毀損=帳本壞了，fail-closed
                    remainder = f.read().strip()
                    if remainder:
                        raise RuntimeError(f"帳本第 {i} 行毀損且非末行：{self.path}")
                    print(f"[警告] 帳本末行毀損已丟棄（第 {i} 行）")
        return events

    def events_of(self, event_type: str) -> list[dict]:
        return [e for e in self.read_all() if e["type"] == event_type]
