"""Taiwan Lottery official API fetch (stdlib only). Ported from lotto-lab discipline."""

from __future__ import annotations

import json
import time
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any, Callable

from nullbench.core.models import Draw

API_BASE = "https://api.taiwanlottery.com/TLCAPIWeB/Lottery"

# game_key used in nullbench domains
ENDPOINTS = {
    "super": ("SuperLotto638Result", "superLotto638Res"),
    "lotto649": ("Lotto649Result", "lotto649Res"),
}

START_MONTH = {
    "super": (2008, 1),
    "lotto649": (2004, 1),
}

RETRIES = 3
TIMEOUT = 30
POLITE_DELAY = 0.12


def _month_iter(start: tuple[int, int], end: tuple[int, int]):
    y, m = start
    while (y, m) <= end:
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def _fetch_month_raw(game_key: str, y: int, m: int) -> dict[str, Any]:
    ep, _ = ENDPOINTS[game_key]
    url = f"{API_BASE}/{ep}?period&month={y:04d}-{m:02d}&pageNum=1&pageSize=50"
    last_err: Exception | None = None
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "nullbench/0.2 (simulation research; no betting)"}
            )
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if data.get("rtCode") != 0:
                raise ValueError(f"rtCode={data.get('rtCode')} rtMsg={data.get('rtMsg')}")
            return data
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"{game_key} {y}-{m:02d} fetch failed after {RETRIES}: {last_err}")


def parse_month(game_key: str, raw: dict[str, Any]) -> list[Draw]:
    _, res_key = ENDPOINTS[game_key]
    rows = raw["content"][res_key]
    draws: list[Draw] = []
    for row in rows:
        nums = row["drawNumberSize"]
        if len(nums) != 7:
            raise ValueError(
                f"{game_key} period {row.get('period')}: expected 7 numbers, got {nums}"
            )
        main, special = sorted(nums[:6]), int(nums[6])
        draws.append(
            Draw(
                period=str(row["period"]),
                numbers=list(main),
                special=special,
                date=str(row["lotteryDate"])[:10],
                meta={"game_key": game_key, "source": "taiwanlottery-api"},
            )
        )
    draws.sort(key=lambda d: (d.date or "", d.period))
    return draws


def ingest(
    game_key: str,
    cache_dir: Path,
    *,
    today: date | None = None,
    progress: Callable[[str, int, int], None] | None = None,
    max_months: int | None = None,
) -> tuple[int, int]:
    """
    Fetch/update monthly caches under cache_dir/raw/<game_key>/.
    Past months are immutable once cached; current month always refreshed.
    Returns (months_scanned, months_fetched).
    """
    if game_key not in ENDPOINTS:
        raise KeyError(game_key)
    today = today or date.today()
    raw_dir = cache_dir / "raw" / game_key
    raw_dir.mkdir(parents=True, exist_ok=True)
    end = (today.year, today.month)
    total = fetched = 0
    for y, m in _month_iter(START_MONTH[game_key], end):
        total += 1
        if max_months is not None and total > max_months:
            break
        cache = raw_dir / f"{y:04d}-{m:02d}.json"
        is_current = (y, m) == end
        if cache.exists() and not is_current:
            continue
        raw = _fetch_month_raw(game_key, y, m)
        tmp = cache.with_suffix(".tmp")
        tmp.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        tmp.replace(cache)
        fetched += 1
        if progress:
            progress(game_key, y, m)
        time.sleep(POLITE_DELAY)
    return total, fetched


def load_all_draws(game_key: str, cache_dir: Path) -> list[Draw]:
    raw_dir = cache_dir / "raw" / game_key
    seen: dict[str, Draw] = {}
    if not raw_dir.exists():
        return []
    for f in sorted(raw_dir.glob("*.json")):
        raw = json.loads(f.read_text(encoding="utf-8"))
        for d in parse_month(game_key, raw):
            seen[d.period] = d
    return [seen[p] for p in sorted(seen, key=lambda x: (seen[x].date or "", x))]


def write_draws_jsonl(draws: list[Draw], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(d.model_dump_json() for d in draws) + ("\n" if draws else ""),
        encoding="utf-8",
    )
