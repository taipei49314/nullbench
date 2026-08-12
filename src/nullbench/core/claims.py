"""Honesty guard — refuse promotional claim language in reports."""

from __future__ import annotations

import re

# Case-insensitive substrings / phrases that must not appear in user-facing claims
FORBIDDEN = (
    "predict",
    "prediction",
    "必中",
    "即將開出",
    "勝率提升",
    "破解",
    "穩贏",
    "保證中",
    "guaranteed win",
    "beat the lottery",
    "winning numbers",
    "sure win",
)


def scan_forbidden(text: str) -> list[str]:
    hits: list[str] = []
    lower = text.lower()
    for phrase in FORBIDDEN:
        if phrase.lower() in lower:
            hits.append(phrase)
    return hits


def assert_clean(text: str) -> None:
    hits = scan_forbidden(text)
    if hits:
        raise ValueError(f"forbidden claim language: {hits}")


def strip_promotional(text: str) -> str:
    """Best-effort scrub for generated markdown (does not invent new claims)."""
    out = text
    for phrase in FORBIDDEN:
        out = re.sub(re.escape(phrase), "[redacted]", out, flags=re.IGNORECASE)
    return out
