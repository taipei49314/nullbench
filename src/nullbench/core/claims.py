"""Honesty guard — refuse promotional claim language in reports (IC-06)."""

from __future__ import annotations

import re

# Multi-word phrases (substring, case-insensitive)
FORBIDDEN_PHRASES = (
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

# English tokens matched on word boundaries (avoid "does not predict")
FORBIDDEN_WORDS = (
    "predict",
    "prediction",
    "predictions",
    "predicted",
    "predicts",
)


def scan_forbidden(text: str) -> list[str]:
    hits: list[str] = []
    lower = text.lower()
    for phrase in FORBIDDEN_PHRASES:
        if phrase.lower() in lower:
            hits.append(phrase)
    for word in FORBIDDEN_WORDS:
        if re.search(rf"\b{re.escape(word)}\b", lower):
            hits.append(word)
    return hits


def assert_clean(text: str) -> None:
    hits = scan_forbidden(text)
    if hits:
        raise ValueError(f"forbidden claim language: {hits}")


def strip_promotional(text: str) -> str:
    """Best-effort scrub for generated markdown (does not invent new claims)."""
    out = text
    for phrase in FORBIDDEN_PHRASES:
        out = re.sub(re.escape(phrase), "[redacted]", out, flags=re.IGNORECASE)
    for word in FORBIDDEN_WORDS:
        out = re.sub(rf"\b{re.escape(word)}\b", "[redacted]", out, flags=re.IGNORECASE)
    return out
