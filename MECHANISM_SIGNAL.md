# 開獎機制訊號稽核

`draw-mechanism-signal-audit-v1` 檢查歷史開獎是否存在能跨時間重現的：

- 主號標籤頻率偏差。
- 一週兩個正常開獎日的號碼差異。
- 相鄰兩期主號重複偏差。
- 威力彩第二區／大樂透特別號分布偏差。
- 主號、星期主號及大樂透主號＋特別號的 30 號排序策略。

結論是：目前沒有候選通過升級門檻，維持 Agent 共識主號與第二區排序。

## 資料與品質

| 遊戲 | 期數 | 日期 | 重複日期／期別 | 非法開獎 | 一般星期外開獎 |
|---|---:|---|---:|---:|---:|
| 威力彩 | 1,929 | 2008-01-24～2026-07-16 | 0／0 | 0 | 0 |
| 大樂透 | 2,153 | 2007-01-02～2026-07-17 | 0／0 | 0 | 113 |

大樂透 113 期一般星期外資料是春節加開，不是資料錯誤。星期候選只對正常
週二／週五建立分組，春節加開使用全訓練期排序 fallback，避免把合法促銷期
誤刪或硬塞進錯誤星期。

兩份逐期 JSONL 的雜湊鏈、日期順序、期別唯一性、主號範圍及特別號規則都通過。

## 巢狀時間切分

先暖機 60 期，剩餘資料依時間切為前 70% development、後 30% 外層 holdout。
development 再切成前 70% inner train 與後 30% inner validation：

| 遊戲 | Inner train | Inner validation | 外層 holdout |
|---|---:|---:|---:|
| 威力彩 | 915 | 393 | 561 |
| 大樂透 | 1,025 | 440 | 628 |

候選只能在 inner train 擬合、inner validation 選擇；外層 holdout 不得反過來
換候選。五個主號候選、威力彩前五第二區與共同第二區共七項，使用 Holm family-wise
校正。升級另要求 13 期區塊 bootstrap 下界大於 0、holdout 前後半都正向。

## 30 號候選結果

表中差值是每期 30 個選號涵蓋的實際六主號數，相對公平模型精確期望值。

| 遊戲 | 候選 | Inner validation 差 | Holdout 差 | 95% 區間 | Holm p |
|---|---|---:|---:|---:|---:|
| 威力彩 | 全訓練期主號頻率 | -0.0218 | -0.0327 | `[-0.1112,+0.0564]` | 1.0000 |
| 威力彩 | 星期主號頻率 | -0.0982 | +0.0439 | `[-0.0220,+0.1099]` | 0.6808 |
| 大樂透 | 全訓練期主號頻率 | +0.0356 | -0.0461 | `[-0.1225,+0.0352]` | 1.0000 |
| 大樂透 | 星期主號頻率 | +0.0038 | -0.0493 | `[-0.1448,+0.0479]` | 1.0000 |
| 大樂透 | 主號＋特別號頻率 | +0.0493 | -0.0238 | `[-0.1018,+0.0606]` | 1.0000 |

威力彩沒有 inner validation 正向候選；大樂透選到主號＋特別號頻率，但外層
holdout 反轉。兩款遊戲都保留現行 Agent 共識主號標籤。

## 機制診斷

外層 holdout 的八項機制診斷經另一組 Holm 校正：

| 遊戲 | 診斷 | 原始 p | Holm p |
|---|---|---:|---:|
| 威力彩 | 主號標籤均勻性 | 0.7475 | 1.0000 |
| 威力彩 | 第二區均勻性 | 0.3179 | 1.0000 |
| 威力彩 | 星期主號差異 | 0.9868 | 1.0000 |
| 威力彩 | 相鄰期主號重複 | 0.7807 | 1.0000 |
| 大樂透 | 主號標籤均勻性 | 0.9366 | 1.0000 |
| 大樂透 | 特別號均勻性 | 0.0380 | 0.3039 |
| 大樂透 | 星期主號差異 | 0.0805 | 0.5636 |
| 大樂透 | 相鄰期主號重複 | 0.9855 | 1.0000 |

大樂透特別號的單項原始 p 值偏低，但多重比較後不顯著，也沒有轉成可通過
holdout 的選號策略。development 與 holdout 的主號殘差相關係數分別為
威力彩 `-0.0383`、大樂透 `-0.1838`，沒有穩定同方向的標籤偏差。

## 威力彩第二區探索結果

Development 全期頻率前五名為 `[2,5,3,4,1]`。外層 holdout 中，開出這五個
第二區的期數為 `377/561`：

| 指標 | 結果 |
|---|---:|
| 外層第二區覆蓋率 | 67.2014% |
| 公平模型基準 | 62.5000% |
| 原始單尾 p | 0.0115 |
| 七候選 Holm p | 0.0805 |
| Inner validation 差 | -1.1768 個百分點 |
| 相對共識任一獎差 | +3.9216 個百分點 |
| 配對 95% 區間 | `[-0.7130,+8.5561]` 個百分點 |

它看起來有趣，但三個必要條件同時失敗：

1. 更早的 inner validation 沒有重現。
2. 七候選 Holm 校正後未達 0.05。
3. 實際任一獎配對區間仍跨 0。

因此不替換現行第二區。系統只凍結
`special-frequency-forward-shadow-v1` 的未來純模擬候選，hash 為
`08f424111df2f6c6a759e001d55eaafd31febc4bc58e8d81cacd4178c2a193e1`；
不得回填既有 7/20、7/21 登記，也不得把探索結果冒充已確認優勢。下一個
威力彩新登記會把它存成配對子影子：主號、分組與正式 coverage
完全相同，只更換第二區；它不是第五個臂，也不改正式 coverage 號碼。

## 共同第二區獲利探索

既有 `guarded_profit`／`unconstrained_profit` 結構原本以同一期辯論支持最高
的 coverage 第二區作共同第二區。新增假說只改這個標籤：inner train 選到
第二區 `5`，development 全期選到 `2`，主號排序與兩種已證明結構完全不變。

| 指標 | 結果 |
|---|---:|
| Inner validation：5 命中 | 46／393（11.7048%） |
| Inner validation 相對 1/8 | -0.7952 個百分點 |
| Holdout：2 命中 | 83／561（14.7950%） |
| 原始單尾 p／七候選 Holm p | 0.0596／0.3576 |
| Guarded 嚴格獲利差 | +0.7130 個百分點 |
| Guarded 95% 區間 | `[-1.0695,+2.6738]` 個百分點 |
| Unconstrained 嚴格獲利差 | +0.7130 個百分點 |
| Unconstrained 95% 區間 | `[-1.9608,+3.5651]` 個百分點 |

因 inner validation 反向、Holm 未過且兩個 paired 區間都跨 0，第二區 `2`
不替換現行辯論選號。它只凍結為
`profit-common-special-forward-shadow-v1`，candidate hash
`99a3f01dd841b566e4582aff9699500b07eab140cc101ec000e0463157abf987`。
從 coverage v4 起，系統會在開獎前把它和同主號、同結構的辯論 baseline
一起登記，開獎後以固定 500 元成本作配對結算；既有期數不回填。

近期、星期與衰減加權共同第二區另由
[ADAPTIVE_SPECIAL_SIGNAL.md](ADAPTIVE_SPECIAL_SIGNAL.md) 稽核。預註冊的
`rolling_104` 在 inner validation 入選，但外層 561 期的兩個獲利區間都
跨 0，未建立自適應 v2。

主號辯論 support 排名本身的 top-10／20／30 校準另由
[DEBATE_RANK_CALIBRATION.md](DEBATE_RANK_CALIBRATION.md) 稽核。六項
holdout 精確檢定皆未通過，威力彩 top10-vs-next10 區間跨 0，因此不把
高 support multiplicity 解讀成標籤預測力。
逐期 support margin 與 candidate disagreement 組成的開獎前信心，
另由 [DEBATE_CONFIDENCE.md](DEBATE_CONFIDENCE.md) 驗證。分群與漂移
品質通過，但八項 Holm p 全為 `1.0`，因此不新增 gated shadow。
開封後另以 predictable-weight mixture e-value 修正自適應群組推論，
八項 anytime-valid Holm p 同樣全為 `1.0`。

## 執行與自動化

```powershell
python -X utf8 mechanism_signal.py
python -X utf8 mechanism_signal_verify.py --tests-only
```

正式輸出：

- `research/results/mechanism_signal.json`
- `research/results/mechanism_signal_candidates.csv`

新開獎觸發桌機 watcher 後，這項研究會和 Agent 品質、最大覆蓋、標籤及分組
研究一起重算。每個已預註冊的第二區子影子會在開獎後自動計算相對 coverage
的任一獎差；只在 52／104／208／416／832 個合格配對 checkpoint 審查，
五次 look 採 alpha spending，區間下界大於 0 才可能支持。
本研究不改動正式 `records/` 或既有前向號碼，純模擬，不構成購買或下注建議。
