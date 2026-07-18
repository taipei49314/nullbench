"""五個選號人格（裁決書定案版）。

介面契約：persona(game, draws, rng) -> {"numbers": [6碼排序], "special": int|None, "meta": {...}}
- draws 必須是「該週週一之前」的歷史切片（呼叫端負責截止，杜絕未來資料洩漏）。
- rng 是 seeds.rng_for 給的 random.Random——同種子位元級可重現。
- 人格只產號，不碰帳本、不碰權重。
"""
from __future__ import annotations

import random

from . import config
from .games import POOL, SPECIAL_POOL, SUPER, Draw
from .stats import gaps, special_gaps


def _weighted_sample(rng: random.Random, weights: dict[int, float], k: int) -> list[int]:
    """不放回逐一加權抽樣；候選以號碼升冪走訪，保證決定性。"""
    pool = dict(weights)
    chosen = []
    for _ in range(k):
        keys = sorted(pool)
        total = sum(pool[n] for n in keys)
        x = rng.random() * total
        acc = 0.0
        picked = keys[-1]  # 浮點邊界保底
        for n in keys:
            acc += pool[n]
            if x < acc:
                picked = n
                break
        chosen.append(picked)
        del pool[picked]
    return sorted(chosen)


def _uniform_special(game: str, rng: random.Random):
    return rng.randrange(1, SPECIAL_POOL[SUPER] + 1) if game == SUPER else None


# ---- 亂數修士：純均勻，內建對照，永遠第 1 席、權重凍結 ----

def random_monk(game: str, draws: list[Draw], rng: random.Random) -> dict:
    numbers = sorted(rng.sample(range(1, POOL[game] + 1), 6))
    return {"numbers": numbers, "special": _uniform_special(game, rng), "meta": {}}


# ---- 熱手獵人：指數衰減頻率加權 ----

def hot_hunter(game: str, draws: list[Draw], rng: random.Random) -> dict:
    p = config.HOT_HUNTER
    recent = draws[-p["W"]:]
    weights = {n: p["ALPHA"] for n in range(1, POOL[game] + 1)}
    for age, d in enumerate(reversed(recent)):  # age=0 最近一期
        for n in d.numbers:
            weights[n] += p["LAMBDA"] ** age
    numbers = _weighted_sample(rng, weights, 6)
    special = None
    if game == SUPER:
        recent2 = draws[-p["W2"]:]
        w2 = {s: p["ALPHA2"] for s in range(1, SPECIAL_POOL[SUPER] + 1)}
        for age, d in enumerate(reversed(recent2)):
            w2[d.special] += p["LAMBDA2"] ** age
        special = _weighted_sample(rng, w2, 1)[0]
    return {"numbers": numbers, "special": special, "meta": {}}


# ---- 冷灶守望者：遺漏值加權（截斷防獨大）----

def _median(xs: list) -> float:
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def cold_keeper(game: str, draws: list[Draw], rng: random.Random) -> dict:
    p = config.COLD_KEEPER
    g = gaps(draws, game)
    med = _median(list(g.values()))
    cap = (med * p["CAP_MULT"] + 1) ** p["GAMMA"]
    weights = {n: min((sk + 1) ** p["GAMMA"], cap) for n, sk in g.items()}
    numbers = _weighted_sample(rng, weights, 6)
    special = None
    if game == SUPER:
        g2 = special_gaps(draws, game)
        med2 = _median(list(g2.values()))
        cap2 = (med2 * p["CAP_MULT"] + 1) ** p["GAMMA2"]
        w2 = {s: min((sk + 1) ** p["GAMMA2"], cap2) for s, sk in g2.items()}
        special = _weighted_sample(rng, w2, 1)[0]
    return {"numbers": numbers, "special": special, "meta": {}}


# ---- 均衡工程師：拒絕取樣＋逐條放寬 ----

def _balance_ok(nums: list[int], game: str, active: set) -> bool:
    b = config.BALANCE
    if "sum" in active:
        lo, hi = b["SUM_BAND"][game]
        if not (lo <= sum(nums) <= hi):
            return False
    if "odd" in active:
        odd = sum(1 for n in nums if n % 2)
        if not (b["ODD_RANGE"][0] <= odd <= b["ODD_RANGE"][1]):
            return False
    if "consecutive" in active:
        pairs = sum(1 for a, c in zip(nums, nums[1:]) if c - a == 1)
        if pairs > b["MAX_CONSECUTIVE_PAIRS"]:
            return False
    if "tails" in active:
        if len({n % 10 for n in nums}) < b["MIN_TAIL_KINDS"]:
            return False
    if "range" in active:
        if nums[-1] - nums[0] < b["MIN_RANGE"]:
            return False
    return True


def balance_engineer(game: str, draws: list[Draw], rng: random.Random) -> dict:
    b = config.BALANCE
    active = {"sum", "odd", "consecutive", "tails", "range"}
    relaxed = []
    relax_queue = list(b["RELAX_ORDER"])
    while True:
        for _ in range(b["MAX_RETRY_PER_LEVEL"]):
            nums = sorted(rng.sample(range(1, POOL[game] + 1), 6))
            if _balance_ok(nums, game, active):
                return {"numbers": nums, "special": _uniform_special(game, rng),
                        "meta": {"relaxed": relaxed} if relaxed else {}}
        if not relax_queue:  # 理論上到不了：全放寬後任何票都合格
            return {"numbers": nums, "special": _uniform_special(game, rng),
                    "meta": {"relaxed": relaxed + ["exhausted"]}}
        dropped = relax_queue.pop(0)
        active.discard(dropped)
        relaxed.append(dropped)


# ---- 反眾道人：避開人類熱門選號模式 ----

def _is_arithmetic(nums: list[int]) -> bool:
    diffs = {b - a for a, b in zip(nums, nums[1:])}
    return len(diffs) == 1


def antipop_taoist(game: str, draws: list[Draw], rng: random.Random) -> dict:
    p = config.ANTIPOP
    weights = {}
    for n in range(1, POOL[game] + 1):
        weights[n] = p["BETA_MONTH"] if n <= 12 else (p["BETA_DAY"] if n <= 31 else 1.0)
    for _ in range(p["MAX_RETRY"]):
        nums = _weighted_sample(rng, weights, 6)
        if not (all(n <= 31 for n in nums) or _is_arithmetic(nums)):
            break
    return {"numbers": nums, "special": _uniform_special(game, rng), "meta": {}}


PERSONAS = {
    "random_monk": random_monk,
    "hot_hunter": hot_hunter,
    "cold_keeper": cold_keeper,
    "balance_engineer": balance_engineer,
    "antipop_taoist": antipop_taoist,
}

SLOGANS = {
    "random_monk": "我不猜，我就是基準線。",
    "hot_hunter": "剛開過的號碼，我再追一程。",
    "cold_keeper": "它欠我的總會還——我知道這是賭徒謬誤，我就是來被檢驗的。",
    "balance_engineer": "我不猜號碼，我只拒絕長得太醜的組合。",
    "antipop_taoist": "中不中天注定，分不分看人性。",
}

NAMES = {
    "random_monk": "亂數修士",
    "hot_hunter": "熱手獵人",
    "cold_keeper": "冷灶守望者",
    "balance_engineer": "均衡工程師",
    "antipop_taoist": "反眾道人",
}
