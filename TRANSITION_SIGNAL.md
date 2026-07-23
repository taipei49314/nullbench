# 前期號碼條件轉移訊號稽核

`lag-transition-signal-audit-v1` 專門檢查上一期或上兩期號碼，是否對下一期
30 個主號標籤具有可重現的條件訊號。熱號、冷號、gap、時間衰減、星期效果
與同期开奖共現都已由其他研究測過，本研究不重複搜尋。

## 預註冊候選

結果開封前固定八個候選：

- `lag1_all_probability`：全歷史 lag-1 條件機率。
- `lag1_all_lift`：全歷史 lag-1 條件機率扣除各號碼邊際機率。
- `lag1_520_lift`、`lag1_260_lift`：最近固定期數的 lag-1 lift。
- `lag2_all_lift`：全歷史 lag-2 lift。
- `lag12_all_lift`：lag-1 與 lag-2 lift 等權平均。
- `consensus_lag1_all_mix`、`consensus_lag12_all_mix`：轉移名次與
  Agent 辯論共識名次等權合成。

條件估計使用固定 prior strength `50`，避免高維轉移矩陣的小樣本極端值。
每個候選仍只選 30 個不同主號並分成五注，因此不改變已證明最優的五注結構。

預註冊 protocol hash：

```
fb51ade764175c262440575bd455deedb2fa7d58d259753e169b0a8baa32675b
```

## 時間切分與門檻

- 暖機 60 期。
- 暖機後前 70% 為 development；development 前 70% 只累積狀態，
  後 30% inner validation 最多選一個候選。
- 最近 30% 為外層 holdout，禁止依 holdout 改選。
- 主要指標：30 號聯集主號命中相對現行 Agent 共識的逐期配對差。
- 護欄：最佳單注主號、至少一注三主號、完整任一獎級都不得下降。
- 八候選乘兩遊戲共 16 個 exact-null 單尾 p 共用 Holm 校正。
- 通過還必須滿足 13 期區塊 bootstrap 下界大於零，且 holdout 前後半
  都是正向。

`candidate_transition_rankings` 不接受 reveal；當期評分完成後才更新
lag-1／lag-2 狀態。大樂透 113 期春節合法加開依真實時間順序保留。

## 正式結果

資料品質通過：

| 遊戲 | 全資料 | inner validation | holdout |
|---|---:|---:|---:|
| 威力彩 | 1,929 | 393 | 561 |
| 大樂透 | 2,153 | 440 | 628 |

兩款遊戲都沒有候選同時通過 inner-validation 的主要指標與護欄：

| 遊戲 | inner 聯集命中最高候選 | 聯集差／期 | 最佳單注差 | 三主號事件差 | 任一獎差 |
|---|---|---:|---:|---:|---:|
| 威力彩 | `lag1_520_lift` | +0.0712 | -0.0483 | -0.0280 | -0.0153 |
| 大樂透 | `lag1_260_lift` | +0.0250 | -0.0614 | +0.0068 | -0.0159 |

候選增加的聯集命中沒有轉化成更好的單注或中獎事件。依預註冊規則，
inner selection 都回到 `consensus`，外層 holdout 不得再挑另一個看起來
較好的候選。

大樂透 `consensus_lag1_all_mix` 在 holdout 對精確均勻零模型的未校正
p 值是 `0.0291`，但 16 項 Holm 校正後為 `0.4648`；而且最佳單注、
三主號事件與任一獎護欄都下降，不能宣稱存在轉移訊號。

正式結論：`no_confirmed_transition_signal`。

由於兩款遊戲 inner validation 都保留現行共識，本研究不建立一個與控制臂
相同的重複 forward shadow，也不改寫 2026-07-20／2026-07-21 已凍結號碼。
若未來要測新的序列假說，必須建立新的 experiment ID，不能每期重開本次
holdout。

## 執行與驗收

```powershell
python -X utf8 transition_signal.py
python -X utf8 transition_signal_verify.py --tests-only
```

正式輸出：

- `research/results/transition_signal.json`
- `research/results/transition_signal_candidates.csv`

本系統純模擬，不構成購買或下注建議。
