"""遊戲規則引擎：威力彩 / 大樂透 的號碼規格、獎級判定、虛擬獎金估值。

設計原則：
- 獎級判定是純函式，只吃 (我方號碼, 開獎紀錄)，可窮舉測試。
- 虛擬獎金分兩類：固定獎級用官方固定金額；浮動獎級優先用該期實際 per_prize，
  該期無人中獎時退回「獎池估值」並標記 estimated=True（防自欺：報告必須揭露）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

SUPER = "super"      # 威力彩
LOTTO649 = "lotto649"  # 大樂透

GAME_NAMES = {SUPER: "威力彩", LOTTO649: "大樂透"}

# 每注售價（虛擬記帳用）
TICKET_PRICE = {SUPER: 100, LOTTO649: 50}

# 開獎日（weekday: Mon=0）
DRAW_WEEKDAYS = {SUPER: (0, 3), LOTTO649: (1, 4)}  # 週一/週四；週二/週五

# 號碼空間
POOL = {SUPER: 38, LOTTO649: 49}
PICK_N = 6
SPECIAL_POOL = {SUPER: 8}  # 威力彩第二區 1~8；大樂透特別號出自同一 49 池


@dataclass(frozen=True)
class Tier:
    rank: int          # 1=頭獎
    label: str
    match_main: int    # 第一區/主號命中數
    match_special: bool
    fixed_prize: int | None  # None=浮動獎級
    api_key: str       # 對應 API 的 assign 欄位名


# 威力彩：頭貳獎浮動累積，參獎以下固定（金額以官方公告為準，測試以 API 實測值鎖定）
SUPER_TIERS = [
    Tier(1, "頭獎", 6, True, None, "super638JackpotAssign"),
    Tier(2, "貳獎", 6, False, None, "super638SecondAssign"),
    Tier(3, "參獎", 5, True, 150_000, "super638ThirdAssign"),
    Tier(4, "肆獎", 5, False, 20_000, "super638FourthAssign"),
    Tier(5, "伍獎", 4, True, 4_000, "super638FifthAssign"),
    Tier(6, "陸獎", 4, False, 800, "super638SixthAssign"),
    Tier(7, "柒獎", 3, True, 400, "super638SeventhAssign"),
    Tier(8, "捌獎", 2, True, 200, "super638EighthAssign"),
    Tier(9, "玖獎", 3, False, 100, "super638NinthAssign"),
    Tier(10, "普獎", 1, True, 100, "super638NormalAssign"),
]

# 大樂透：頭~肆獎浮動（均分制），伍獎以下固定
# 固定金額以現行制度為準（2026-07-18 以 2020+ 全期實掃驗證：伍2000/陸1000/柒400/普400
# 恆定；極少數低於面額者為該期獎金分配額不足之按比例調降，結算時以實際 per_prize 為準）
LOTTO649_TIERS = [
    Tier(1, "頭獎", 6, False, None, "jackpotAssign"),
    Tier(2, "貳獎", 5, True, None, "secondAssign"),
    Tier(3, "參獎", 5, False, None, "thirdAssign"),
    Tier(4, "肆獎", 4, True, None, "fourthAssign"),
    Tier(5, "伍獎", 4, False, 2_000, "fifthAssign"),
    Tier(6, "陸獎", 3, True, 1_000, "sixthAssign"),
    Tier(7, "柒獎", 3, False, 400, "seventhAssign"),
    Tier(8, "普獎", 2, True, 400, "normalAssign"),
]

TIERS = {SUPER: SUPER_TIERS, LOTTO649: LOTTO649_TIERS}


@dataclass(frozen=True)
class Draw:
    """一期開獎的正規化紀錄。"""
    game: str
    period: int
    date: str                 # YYYY-MM-DD
    numbers: tuple            # 6 個主號（排序）
    special: int              # 威力彩=第二區；大樂透=特別號
    prizes: dict = field(default_factory=dict)  # api_key -> {winner_count, per_prize, pool, last_pool}
    sell_amount: int = 0
    total_amount: int = 0


def validate_pick(game: str, numbers, special) -> None:
    """驗證一組號碼合法，不合法就 raise ValueError。"""
    pool = POOL[game]
    nums = list(numbers)
    if len(nums) != PICK_N or len(set(nums)) != PICK_N:
        raise ValueError(f"{game}: 主號必須 {PICK_N} 個不重複，收到 {numbers}")
    for n in nums:
        if not (1 <= n <= pool):
            raise ValueError(f"{game}: 主號 {n} 超出 1~{pool}")
    if game == SUPER:
        if not (1 <= special <= SPECIAL_POOL[SUPER]):
            raise ValueError(f"威力彩第二區 {special} 超出 1~8")
    else:
        if special is not None:
            raise ValueError("大樂透玩家不選特別號，special 必須為 None")


def match_tier(game: str, numbers, special, draw: Draw) -> Tier | None:
    """判定一組號碼在某期開獎中落在哪個獎級；未中回傳 None。"""
    validate_pick(game, numbers, special)
    main_hits = len(set(numbers) & set(draw.numbers))
    if game == SUPER:
        sp_hit = special == draw.special
    else:
        # 大樂透特別號出自同一池：我方 6 碼中任一碼等於特別號即算「中特別號」
        sp_hit = draw.special in set(numbers)
    for tier in TIERS[game]:
        if main_hits == tier.match_main and sp_hit == tier.match_special:
            return tier
    return None


def prize_value(tier: Tier, draw: Draw, floor_table: dict | None = None) -> tuple[int, str, int]:
    """回傳 (虛擬獎金, basis, 上界)。basis ∈ {"fixed", "counterfactual", "estimated"}。

    裁決書估值規則（方向一律對策略不利的保守估計）：
    - 固定獎級 → 官方固定金額（該期 API 有實際 per_prize 就用實際值）。
    - 浮動獎級、該期有人中獎 → 反事實修正：pool = per_prize × winner_count，
      我們若真中會多一個分獎人 → 記 pool // (winner_count + 1)。
    - 浮動獎級、該期無人中獎 → 保守下界（該獎級歷史最低 per_prize，
      由 floor_table 提供；缺表則用獎池），上界=本期獎池＋累積獎池，標 estimated。
    """
    info = draw.prizes.get(tier.api_key, {})
    winner_count = info.get("winner_count", 0)
    per_prize = info.get("per_prize", 0)
    if tier.fixed_prize is not None:
        if winner_count > 0 and per_prize > 0:
            return per_prize, "fixed", per_prize
        return tier.fixed_prize, "fixed", tier.fixed_prize
    if winner_count > 0 and per_prize > 0:
        pool = per_prize * winner_count
        value = pool // (winner_count + 1)
        return value, "counterfactual", value
    upper = info.get("pool", 0) + info.get("last_pool", 0)
    floor = (floor_table or {}).get(tier.api_key, 0)
    return (floor if floor > 0 else upper), "estimated", upper


def floor_table_from_history(draws: list[Draw]) -> dict:
    """每個浮動獎級的歷史最低實際 per_prize（保守下界估值用）。"""
    floors: dict[str, int] = {}
    for d in draws:
        for key, info in d.prizes.items():
            if info.get("winner_count", 0) > 0 and info.get("per_prize", 0) > 0:
                cur = floors.get(key)
                if cur is None or info["per_prize"] < cur:
                    floors[key] = info["per_prize"]
    return floors
