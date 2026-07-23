# Agent 共識完全分散五注契約

`max-coverage-consensus-shadow-v1` 的目標是在固定五注預算下，提高「五注中
至少一注落入任一現行獎級」的精確聯集機率。它不宣稱預測得到更可能開出的
特定號碼，也不改變任何合法單注或頭獎組合的理論機率。

## 策略

每一期只使用開獎前已封存的 15 組 Agent 提案與 60 筆交叉評論：

1. 依提案辯論總分、支持該號碼的 Agent 數與提案出現次數，建立號碼支持排序。
2. 選出前 30 個不同主號，使用 round-robin 平均分成五注，使任兩注主號交集
   都是 0。
3. 威力彩以同一份開獎前支持資料選五個不同第二區。
4. 封存來源決策 hash、支持證據 hash、30 個主號、五注支持證據與完整結構機率。
5. 若來源、結構或精確機率驗證失敗，當期退回規則臂並標記為不合格，不冒充成功。

selector 函式不接受 `reveal`。實際開獎只在五注固定後用於回顧命中評分，
因此不能用當期答案改號。

## 數學護欄

五注主號完全不重疊時，十組票對的完整中獎事件交集各自達到已精確驗證的
最小值；威力彩第二區也互異。二階 Bonferroni 聯集機率下界達到全域最大。
`five-ticket-structural-optimum-proof-v1` 再窮舉三注的全部 256 個 Venn
membership 結構，以三階 Bonferroni 與精確整數 charge inequality 證明：
所有可能五注的完整任一獎級聯集機率，都不會超過完全分散五注；三主號護欄
亦同。詳細證書見 [STRUCTURAL_OPTIMUM.md](STRUCTURAL_OPTIMUM.md)。
獨立的 [HIGH_TIER_OPTIMUM.md](HIGH_TIER_OPTIMUM.md) 再以 union bound
與完整獎級整數計數證明：同一結構也同步最大化至少 4／5／6 主號，以及
威力彩頭獎至柒獎、大樂透頭獎至陸獎的每個累積門檻；不是用高獎機率交換
低獎聯集率。

依台彩現行規則，威力彩完整事件納入至少三個主號，以及一或二個主號搭配
第二區；大樂透納入至少三個主號，以及兩個主號搭配特別號。規則來源：
[台彩威力彩遊戲介紹](https://www.taiwanlottery.com/lotto/info/super_lotto638)、
[台彩大樂透遊戲介紹](https://www.taiwanlottery.com/lotto/info/lotto649)。

| 遊戲 | 完整任一獎級：完全分散五注 | 三主號護欄 | 主號聯集 | 最大兩票主號重疊 |
|---|---:|---:|---:|---:|
| 威力彩 | 54.2963% | 19.2041% | 30 | 0 |
| 大樂透 | 15.2966% | 9.2902% | 30 | 0 |

這些數字是固定五注的聯集事件機率；不能解讀為單注中獎率、頭獎率或某個號碼
的開出率提高。完整獎級分解顯示任一獎事件主要來自低獎級；五注頭獎率、
同時中多注機率與第 1 至第 5 注的邊際增益見
[PRIZE_TIER_PROFILE.md](PRIZE_TIER_PROFILE.md)。

## 4,082 期正式回跑

資料截至威力彩 `2026-07-16`、大樂透 `2026-07-17`。暖機 60 期後以前
70% 作 development、最近 30% 作一次性 holdout；全程重用當期開獎前已
封存的 Agent 辯論。

| 遊戲 | holdout 期數 | 規則臂完整機率 | 15 選 5 coverage | 完全分散 | 相對 15 選 5 |
|---|---:|---:|---:|---:|---:|
| 威力彩 | 561 | 46.6825% | 53.0956% | 54.2963% | +1.2007 個百分點 |
| 大樂透 | 628 | 14.6982% | 15.1871% | 15.2966% | +0.1095 個百分點 |

三主號護欄相對 15 選 5 coverage 的 holdout 改善為威力彩
`+0.3656` 個百分點、大樂透 `+0.0374` 個百分點。development 與 holdout
每一期的兩個精確機率都沒有下降；這項結構保證是升級依據。

回顧性最佳主號命中差只作診斷：

| 比較 | 威力彩平均差與 95% 區間 | 大樂透平均差與 95% 區間 |
|---|---:|---:|
| 完全分散－規則臂 | +0.1266 `[+0.0623, +0.1907]` | +0.1274 `[+0.0685, +0.1847]` |
| 完全分散－15 選 5 | +0.0303 `[-0.0321, +0.0945]` | +0.0446 `[-0.0144, +0.1051]` |

第二列區間跨 0，因此不能把歷史命中差宣稱為確認性優勢。真正的確認仍要靠
未來開獎前凍結的 forward shadow 樣本。

## 號碼標籤沒有通過替換門檻

完全分散決定結構機率，Agent 共識只決定 30 個號碼標籤。後續
`label-signal-shadow-v1` 以 development／封存 holdout 比較 15 個開獎前
ranker；沒有任何替代排序通過兩款遊戲的主指標與護欄。大樂透共識在 holdout
看似多涵蓋 43.06 個主號命中，但精確零模型單尾 p 值 `0.0662`，六項
Holm 校正後為 `0.3309`；威力彩則低於零模型。故保持共識只代表不採用已
失敗的歷史 heuristic，不宣稱共識能預測號碼。詳見
[LABEL_SIGNAL.md](LABEL_SIGNAL.md)。

同一批 30 號如何分成五注也經 `partition-signal-shadow-v1` 封存檢查。
development 選出的威力彩固定種子 shuffle 在 holdout 反轉，兩款遊戲都
沒有通過分組替換門檻，因此維持 round-robin。詳見
[PARTITION_SIGNAL.md](PARTITION_SIGNAL.md)。

## 前向契約 v2／v3

完全分散策略先以 `max-coverage-consensus-forward-v2` 上線；新增獲利子影子
後的新登記使用 `profit-portfolio-consensus-forward-v3`。威力彩
`2026-07-20` 與大樂透 `2026-07-21` 已存在的三臂登記保持原樣，不回填、
不改號；新版本都只從下一個尚未登記的目標期開始。

每個合格 v2／v3 coverage 樣本必須同時滿足：

- 在目標期截止時間前與 Qwen、規則、隨機臂一起凍結。
- 支持證據 hash、來源 decision hash 與帳本雜湊鏈可重建。
- 結構最優證書版本與 certificate hash 必須完全吻合。
- 主號聯集恰為 30、任兩注主號重疊為 0；威力彩五個第二區互異。
- 完整任一獎級與三主號精確機率都不低於同一期規則臂。
- selector 失敗、晚登或任何證明不符時，該 coverage 樣本永久不合格。

v3 另把同一辯論排序映射成 guarded／unconstrained 兩種獲利子影子；它們
不改 coverage 票、不新增正式臂，只累積新期次的嚴格獲利配對結果。歷史
v1、舊三臂、v2 與 v3 由版本欄位分開驗證，不能用新格式竄改舊事件。

## 驗收

```powershell
python -X utf8 exact_selector_audit.py --game super --output research/results/exact_selector_audit_super.json
python -X utf8 exact_selector_audit.py --game lotto649 --output research/results/exact_selector_audit_lotto649.json
python -X utf8 max_coverage.py
python -X utf8 max_coverage_verify.py --tests-only
python -X utf8 prize_tier_profile.py
python -X utf8 prize_tier_profile_verify.py --tests-only
python -X utf8 high_tier_optimum.py
python -X utf8 high_tier_optimum_verify.py --tests-only
```

正式輸出：

- `research/results/max_coverage.json`
- `research/results/max_coverage_summary.csv`
- `research/results/exact_selector_audit_super.json`
- `research/results/exact_selector_audit_lotto649.json`
- `research/results/prize_tier_profile.json`
- `research/results/high_tier_optimum.json`

正式研究前後的 `records/` tree SHA-256 必須完全一致。本系統純模擬，
不構成購買或下注建議。
