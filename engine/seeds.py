"""種子紀律：單一公式覆蓋全部隨機性，位元級可重現。

seed_str = "lotto-lab|{experiment_id}|{game}|{week_id}|{stream}|{persona_id}|slot{k}|retry{n}"
stream ∈ {official, shadow, null|port{p}}；week_id 形如 2026-W30。
"""
from __future__ import annotations

import hashlib
import random

from .config import EXPERIMENT_ID


def seed_int(seed_str: str) -> int:
    return int(hashlib.sha256(seed_str.encode("utf-8")).hexdigest()[:16], 16)


def seed_str(game: str, week_id: str, stream: str, persona_id: str,
             slot: int, retry: int = 0, experiment_id: str = EXPERIMENT_ID) -> str:
    return (f"lotto-lab|{experiment_id}|{game}|{week_id}|{stream}"
            f"|{persona_id}|slot{slot}|retry{retry}")


def rng_for(game: str, week_id: str, stream: str, persona_id: str,
            slot: int, retry: int = 0) -> random.Random:
    return random.Random(seed_int(seed_str(game, week_id, stream, persona_id, slot, retry)))


def mc_rng(checkpoint: str, game: str) -> random.Random:
    s = f"mc|{EXPERIMENT_ID}|{checkpoint}|{game}"
    return random.Random(seed_int(s))


def content_hash(canonical_json: str) -> str:
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
