"""實驗參數總表（裁決書 wf_bbd9e6c8 定案）。

鐵律：改本檔任何參數＝開新 experiment_id 從零起算，禁止原地調參沿用舊帳。
"""
from .games import SUPER, LOTTO649

EXPERIMENT_ID = "v1"

# ---- 人格參數 ----
HOT_HUNTER = {"W": 50, "LAMBDA": 0.97, "ALPHA": 1.0, "W2": 30, "LAMBDA2": 0.97, "ALPHA2": 1.0}
COLD_KEEPER = {"GAMMA": 1.5, "GAMMA2": 1.2, "CAP_MULT": 4}
# 和值帶：math.comb 精確枚舉之 20~80 百分位（建置時 DP 精算，2026-07-18）
BALANCE = {
    "SUM_BAND": {SUPER: (96, 138), LOTTO649: (122, 178)},
    "ODD_RANGE": (2, 4),
    "MAX_CONSECUTIVE_PAIRS": 1,
    "MIN_TAIL_KINDS": 4,
    "MIN_RANGE": 15,
    "MAX_RETRY_PER_LEVEL": 1000,
    # 放寬順序：(d)尾數 → (c)連號 → (b)奇偶 → (e)極差 → (a)和值
    "RELAX_ORDER": ("tails", "consecutive", "odd", "range", "sum"),
}
ANTIPOP = {"BETA_MONTH": 0.6, "BETA_DAY": 0.75, "MAX_RETRY": 100}

# ---- 席位與權重 ----
ADAPTIVE_PERSONAS = ("antipop_taoist", "balance_engineer", "cold_keeper", "hot_hunter")  # 字典序
RESERVED_PERSONA = "random_monk"   # 永遠第 1 席、權重凍結
SEATS = 5
ETA = 0.10            # 學習率
MIX_EPS = 0.10        # 均勻混合比例
WEIGHT_CLAMP = (0.05, 0.60)
BURN_IN_WEEKS = 8     # 每遊戲前 8 個已核對週權重凍結均勻
DEDUP_MAX_RETRY = 20

# ---- null model ----
NULL_PORTFOLIOS = 200  # 每遊戲每週 200 組 × 5 注

# ---- 統計 ----
ALPHA_TOTAL = 0.05           # 兩遊戲 Bonferroni → 每遊戲 0.025
CHECKPOINTS = {26: 0.005, 52: 0.020}  # alpha-spending：已核對週數 → 該檢查點 α
PERMUTATIONS = 10_000
FDR_Q = 0.10

# ---- 誠實紀律 ----
FORBIDDEN_WORDS = ("預測", "必中", "即將開出", "勝率提升", "破解", "穩贏", "保證中")
LATE_CUTOFF_TIME = "20:30"   # 開獎日當晚截止（台北時間）；晚於首期開獎即 LATE
ESTIMATED_WARN_RATIO = 0.10  # ESTIMATED 佔獎金比超過即加警語
INVALID_WARN_RATIO = 0.05    # INVALID 週佔比紅色警示

WEEKLY_COST = {SUPER: 5 * 2 * 100, LOTTO649: 5 * 2 * 50}  # 正常週虛擬成本
