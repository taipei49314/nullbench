"""Deterministic hashing for freeze / ledger integrity."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(obj: Any) -> str:
    """Stable JSON for hashing (sorted keys, no whitespace variance)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def content_hash(payload: dict[str, Any]) -> str:
    return sha256_hex(canonical_json(payload))


def code_fingerprint() -> str:
    """Lightweight fingerprint of public package version (not full tree hash)."""
    from nullbench import __version__

    return sha256_hex(f"nullbench=={__version__}")[:16]
