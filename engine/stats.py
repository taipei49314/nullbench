"""歷史統計工具箱：給選號人格用的純函式。

重要紀律：所有函式只吃呼叫端給的 draws 切片——分析截止日由呼叫端用
store.before(game, cutoff) 控制，工具箱本身不碰時間，杜絕未來資料洩漏。
"""
from __future__ import annotations

from collections import Counter

from .games import POOL, SPECIAL_POOL, SUPER, Draw


def main_freq(draws: list[Draw], window: int | None = None) -> Counter:
    """主號出現次數。window=None 全歷史；否則取最近 window 期。"""
    sl = draws[-window:] if window else draws
    c = Counter()
    for d in sl:
        c.update(d.numbers)
    return c


def special_freq(draws: list[Draw], window: int | None = None) -> Counter:
    sl = draws[-window:] if window else draws
    return Counter(d.special for d in sl)


def gaps(draws: list[Draw], game: str) -> dict[int, int]:
    """每個主號的目前遺漏期數（距上次開出隔幾期；從未開出=len(draws)）。"""
    out = {}
    for n in range(1, POOL[game] + 1):
        gap = len(draws)
        for i, d in enumerate(reversed(draws)):
            if n in d.numbers:
                gap = i
                break
        out[n] = gap
    return out


def special_gaps(draws: list[Draw], game: str) -> dict[int, int]:
    pool = SPECIAL_POOL[game] if game == SUPER else POOL[game]
    out = {}
    for n in range(1, pool + 1):
        gap = len(draws)
        for i, d in enumerate(reversed(draws)):
            if n == d.special:
                gap = i
                break
        out[n] = gap
    return out


def spread(numbers) -> dict:
    """一組號碼的形狀指標：總和、極差、奇數比、低區(≤池半)數。"""
    nums = sorted(numbers)
    return {
        "sum": sum(nums),
        "range": nums[-1] - nums[0],
        "odd": sum(1 for n in nums if n % 2),
        "consecutive_pairs": sum(1 for a, b in zip(nums, nums[1:]) if b - a == 1),
    }
