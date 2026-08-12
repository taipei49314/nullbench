"""Append-only JSONL ledger with SHA-256 chain."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from nullbench.core.hashing import sha256_hex


class Ledger:
    """One JSON object per line; each line carries prev_line_hash + line_hash."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("", encoding="utf-8")

    def _last_line_hash(self) -> str:
        last = ""
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    last = line
        if not last:
            return "0" * 64
        row = json.loads(last)
        return row["line_hash"]

    def append(self, event: dict[str, Any]) -> dict[str, Any]:
        prev = self._last_line_hash()
        body = {k: v for k, v in event.items() if k not in ("prev_line_hash", "line_hash")}
        material = {"prev_line_hash": prev, **body}
        # Hash without line_hash field
        digest = sha256_hex(json.dumps(material, sort_keys=True, separators=(",", ":"), default=str))
        row = {**material, "line_hash": digest}
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        return row

    def __iter__(self) -> Iterator[dict[str, Any]]:
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    yield json.loads(line)

    def events_of(self, event_type: str) -> list[dict[str, Any]]:
        return [e for e in self if e.get("type") == event_type]

    def verify_chain(self) -> tuple[bool, str]:
        prev = "0" * 64
        for i, row in enumerate(self, start=1):
            if row.get("prev_line_hash") != prev:
                return False, f"line {i}: prev_line_hash mismatch"
            body = {k: v for k, v in row.items() if k != "line_hash"}
            expected = sha256_hex(
                json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
            )
            if row.get("line_hash") != expected:
                return False, f"line {i}: line_hash mismatch"
            prev = row["line_hash"]
        return True, "ok"

    def __len__(self) -> int:
        return sum(1 for _ in self)
