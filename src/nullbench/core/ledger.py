"""Append-only JSONL ledger with SHA-256 chain + tip seal.

verify_chain alone cannot detect a full rewrite with re-linked hashes (IC-01).
Tip seal + semantic verification (integrity.verify_study_semantic) close that gap
for honest disk operators; external notarization is still required for adversaries
with full filesystem write (see IC-10 / PUBLISH.md OIDC).
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from nullbench.core.hashing import sha256_hex
from nullbench.errors import IntegrityError


class Ledger:
    """One JSON object per line; each line carries prev_line_hash + line_hash."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.tip_path = path.with_suffix(path.suffix + ".tip")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("", encoding="utf-8")
            self._write_tip("0" * 64, 0)
        elif not self.tip_path.exists() and self._line_count() == 0:
            # Empty ledger without tip — heal so first append is not blocked
            self._write_tip("0" * 64, 0)

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

    def _line_count(self) -> int:
        n = 0
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    n += 1
        return n

    def _write_tip(self, line_hash: str, n_lines: int) -> None:
        tip = {"line_hash": line_hash, "n_lines": n_lines, "path": self.path.name}
        tmp = self.tip_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(tip, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.tip_path)

    def append(self, event: dict[str, Any]) -> dict[str, Any]:
        return self.append_many([event])[0]

    def append_many(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Append one logical batch with a single preflight and tip update."""
        if not events:
            return []
        # Refuse append if tip does not match file (detects silent rewrite)
        self.verify_tip()
        prev = self._last_line_hash()
        rows: list[dict[str, Any]] = []
        for event in events:
            body = {k: v for k, v in event.items() if k not in ("prev_line_hash", "line_hash")}
            material = {"prev_line_hash": prev, **body}
            digest = sha256_hex(
                json.dumps(material, sort_keys=True, separators=(",", ":"), default=str)
            )
            row = {**material, "line_hash": digest}
            rows.append(row)
            prev = digest
        with self.path.open("a", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        self._write_tip(prev, self._line_count())
        return rows

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
        n = 0
        last_hash = "0" * 64
        try:
            for i, row in enumerate(self, start=1):
                n = i
                if row.get("prev_line_hash") != prev:
                    return False, f"line {i}: prev_line_hash mismatch"
                body = {k: v for k, v in row.items() if k != "line_hash"}
                expected = sha256_hex(
                    json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
                )
                if row.get("line_hash") != expected:
                    return False, f"line {i}: line_hash mismatch"
                prev = row["line_hash"]
                last_hash = prev
        except (json.JSONDecodeError, KeyError, OSError, TypeError) as exc:
            return False, f"ledger unreadable: {exc}"
        # Tip seal required whenever the ledger has events (R-01).
        # Deleting the tip must not leave verify_chain green.
        if n > 0 and not self.tip_path.exists():
            return False, "tip seal missing (required when ledger has events)"
        if self.tip_path.exists():
            try:
                tip = json.loads(self.tip_path.read_text(encoding="utf-8"))
            except Exception:
                return False, "tip seal unreadable"
            if tip.get("n_lines") != n:
                return False, f"tip n_lines mismatch file={n} tip={tip.get('n_lines')}"
            if n > 0 and tip.get("line_hash") != last_hash:
                return False, "tip line_hash mismatch (ledger rewrite without tip)"
        return True, "ok"

    def verify_tip(self) -> None:
        ok, msg = self.verify_chain()
        if not ok:
            raise IntegrityError(f"ledger tip/chain invalid: {msg}")

    def __len__(self) -> int:
        return sum(1 for _ in self)
