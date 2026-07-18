"""獎則引擎測試：每個獎級用合成票窮舉驗證，獎金估值邏輯逐路徑驗證。"""
import pytest

from engine.games import (
    SUPER, LOTTO649, SUPER_TIERS, LOTTO649_TIERS,
    Draw, match_tier, prize_value, validate_pick,
)

# 威力彩測試期：主號 5,6,9,15,16,33 第二區 5（取自 2026-06 真實期 115000052）
SUPER_DRAW = Draw(game=SUPER, period=115000052, date="2026-06-01",
                  numbers=(5, 6, 9, 15, 16, 33), special=5)
# 大樂透測試期：主號 4,10,16,29,36,45 特別號 14（真實期 115000066）
L649_DRAW = Draw(game=LOTTO649, period=115000066, date="2026-06-02",
                 numbers=(4, 10, 16, 29, 36, 45), special=14)

# 不在威力彩開獎主號中的填充號
S_MISS = [1, 2, 3, 4, 7, 8]
# 不在大樂透主號也不是特別號的填充號
L_MISS = [1, 2, 3, 5, 6, 7]


def _super_pick(hits: int, sp: bool):
    nums = list(SUPER_DRAW.numbers[:hits]) + S_MISS[: 6 - hits]
    return nums, (5 if sp else 6)


def _l649_pick(hits: int, sp: bool):
    nums = list(L649_DRAW.numbers[:hits]) + ([14] if sp else []) + L_MISS[: 6 - hits - (1 if sp else 0)]
    return nums


@pytest.mark.parametrize("hits,sp,expect_rank", [
    (6, True, 1), (6, False, 2), (5, True, 3), (5, False, 4),
    (4, True, 5), (4, False, 6), (3, True, 7), (2, True, 8),
    (3, False, 9), (1, True, 10),
    # 未中組合
    (2, False, None), (1, False, None), (0, True, None), (0, False, None),
])
def test_super_tiers(hits, sp, expect_rank):
    nums, special = _super_pick(hits, sp)
    tier = match_tier(SUPER, nums, special, SUPER_DRAW)
    assert (tier.rank if tier else None) == expect_rank


@pytest.mark.parametrize("hits,sp,expect_rank", [
    (6, False, 1), (5, True, 2), (5, False, 3), (4, True, 4),
    (4, False, 5), (3, True, 6), (3, False, 7), (2, True, 8),
    # 未中組合
    (2, False, None), (1, True, None), (1, False, None), (0, True, None), (0, False, None),
])
def test_lotto649_tiers(hits, sp, expect_rank):
    nums = _l649_pick(hits, sp)
    tier = match_tier(LOTTO649, nums, None, L649_DRAW)
    assert (tier.rank if tier else None) == expect_rank


def test_lotto649_six_hits_cannot_also_hit_special():
    # 6 個主號全中時特別號必不在我方 6 碼內（特別號不會等於任何主號）→ 頭獎
    tier = match_tier(LOTTO649, list(L649_DRAW.numbers), None, L649_DRAW)
    assert tier.rank == 1


def test_validate_pick_rejects():
    with pytest.raises(ValueError):
        validate_pick(SUPER, [1, 2, 3, 4, 5], 3)          # 只有 5 碼
    with pytest.raises(ValueError):
        validate_pick(SUPER, [1, 2, 3, 4, 5, 5], 3)       # 重複
    with pytest.raises(ValueError):
        validate_pick(SUPER, [1, 2, 3, 4, 5, 39], 3)      # 超界
    with pytest.raises(ValueError):
        validate_pick(SUPER, [1, 2, 3, 4, 5, 6], 9)       # 第二區超界
    with pytest.raises(ValueError):
        validate_pick(LOTTO649, [1, 2, 3, 4, 5, 6], 7)    # 大樂透不選特別號
    validate_pick(LOTTO649, [1, 2, 3, 4, 5, 49], None)     # 合法


def _draw_with_prizes(base: Draw, api_key: str, winner_count: int, per_prize: int,
                      pool: int = 0, last_pool: int = 0) -> Draw:
    prizes = {api_key: {"winner_count": winner_count, "per_prize": per_prize,
                        "pool": pool, "last_pool": last_pool}}
    return Draw(game=base.game, period=base.period, date=base.date,
                numbers=base.numbers, special=base.special, prizes=prizes)


def test_prize_value_fixed_tier_uses_actual_when_winners():
    tier = SUPER_TIERS[3]  # 肆獎 fixed 20000
    d = _draw_with_prizes(SUPER_DRAW, tier.api_key, 37, 20000)
    assert prize_value(tier, d) == (20000, False)


def test_prize_value_fixed_tier_falls_back_when_no_winners():
    tier = SUPER_TIERS[2]  # 參獎 fixed 150000
    d = _draw_with_prizes(SUPER_DRAW, tier.api_key, 0, 0)
    assert prize_value(tier, d) == (150000, False)


def test_prize_value_floating_no_winner_is_estimated():
    tier = SUPER_TIERS[0]  # 頭獎浮動
    d = _draw_with_prizes(SUPER_DRAW, tier.api_key, 0, 0, pool=14_942_147, last_pool=115_589_619)
    value, estimated = prize_value(tier, d)
    assert value == 14_942_147 + 115_589_619
    assert estimated is True


def test_prize_value_floating_with_winner_is_exact():
    tier = LOTTO649_TIERS[0]
    d = _draw_with_prizes(L649_DRAW, tier.api_key, 1, 643_445_802)
    assert prize_value(tier, d) == (643_445_802, False)
