"""台彩官方 API 抓取器：全歷史開獎資料，逐月抓取＋本地快取。

紀律（承 ai-company procs.py 的教訓）：
- 純 stdlib urllib，逐月一次請求、禮貌間隔，失敗重試後放棄該月（fail-closed：
  寧可少資料也不寫壞資料）。
- 過去月份不可變 → 快取檔存在就不重抓；當月永遠重抓。
- 所有檔案 UTF-8。
"""
from __future__ import annotations

import json
import time
import urllib.request
from datetime import date
from pathlib import Path

from .games import SUPER, LOTTO649, Draw

API_BASE = "https://api.taiwanlottery.com/TLCAPIWeB/Lottery"

ENDPOINTS = {
    SUPER: ("SuperLotto638Result", "superLotto638Res"),
    LOTTO649: ("Lotto649Result", "lotto649Res"),
}

# 官方 API 資料起點：威力彩 2008-01 首期實測有資料；
# 大樂透掃描自 2004-01（實測 2005 前為空，多掃只是幾個空回應，換取「全歷史」保證）。
START_MONTH = {SUPER: (2008, 1), LOTTO649: (2004, 1)}

RETRIES = 3
TIMEOUT = 30
POLITE_DELAY = 0.15  # 秒


def _month_iter(start: tuple[int, int], end: tuple[int, int]):
    y, m = start
    while (y, m) <= end:
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def _fetch_month_raw(game: str, y: int, m: int) -> dict:
    ep, _ = ENDPOINTS[game]
    url = f"{API_BASE}/{ep}?period&month={y:04d}-{m:02d}&pageNum=1&pageSize=50"
    last_err = None
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "lotto-lab/1.0 (simulation research)"})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if data.get("rtCode") != 0:
                raise ValueError(f"rtCode={data.get('rtCode')} rtMsg={data.get('rtMsg')}")
            return data
        except Exception as e:  # noqa: BLE001 - 重試後上拋
            last_err = e
            time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"{game} {y}-{m:02d} 抓取失敗（{RETRIES} 次）：{last_err}")


def parse_month(game: str, raw: dict) -> list[Draw]:
    """把 API 月回應解析成正規化 Draw 清單。格式異常直接 raise（fail-closed）。"""
    _, res_key = ENDPOINTS[game]
    rows = raw["content"][res_key]
    draws = []
    for row in rows:
        nums = row["drawNumberSize"]
        if len(nums) != 7:
            raise ValueError(f"{game} 期 {row.get('period')}: drawNumberSize 應為 7 碼，收到 {nums}")
        main, special = sorted(nums[:6]), nums[6]
        prizes = {}
        for key, val in row.items():
            if key.endswith("Assign") and isinstance(val, dict):
                prizes[key] = {
                    "winner_count": val.get("winnerCount", 0) or 0,
                    "per_prize": val.get("perPrize", 0) or 0,
                    "pool": val.get("prize", 0) or 0,
                    "last_pool": val.get("lastPrize", 0) or 0,
                }
        draws.append(Draw(
            game=game,
            period=int(row["period"]),
            date=str(row["lotteryDate"])[:10],
            numbers=tuple(main),
            special=int(special),
            prizes=prizes,
            sell_amount=int(row.get("sellAmount") or 0),
            total_amount=int(row.get("totalAmount") or 0),
        ))
    draws.sort(key=lambda d: d.period)
    return draws


def ingest(game: str, data_dir: Path, today: date | None = None,
           progress=None) -> tuple[int, int]:
    """抓取／更新一個遊戲的全歷史。回傳 (月份數, 新抓月份數)。

    快取：data/raw/<game>/<YYYY-MM>.json。過去月份存在即跳過；當月永遠重抓。
    """
    today = today or date.today()
    raw_dir = data_dir / "raw" / game
    raw_dir.mkdir(parents=True, exist_ok=True)
    end = (today.year, today.month)
    total = fetched = 0
    for y, m in _month_iter(START_MONTH[game], end):
        total += 1
        cache = raw_dir / f"{y:04d}-{m:02d}.json"
        is_current = (y, m) == end
        if cache.exists() and not is_current:
            continue
        raw = _fetch_month_raw(game, y, m)
        tmp = cache.with_suffix(".tmp")
        tmp.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        tmp.replace(cache)
        fetched += 1
        if progress:
            progress(game, y, m)
        time.sleep(POLITE_DELAY)
    return total, fetched


def load_all_draws(game: str, data_dir: Path) -> list[Draw]:
    """從快取讀出全部期數（依期號排序、去重）。"""
    raw_dir = data_dir / "raw" / game
    seen = {}
    for f in sorted(raw_dir.glob("*.json")):
        raw = json.loads(f.read_text(encoding="utf-8"))
        for d in parse_month(game, raw):
            seen[d.period] = d
    return [seen[p] for p in sorted(seen)]
