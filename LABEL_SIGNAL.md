# 30 號標籤訊號封存研究

`label-signal-shadow-v1` 檢查完全分散五注內的「號碼標籤」是否存在可重現
訊號。結構已由 [STRUCTURAL_OPTIMUM.md](STRUCTURAL_OPTIMUM.md) 證明全域
最優；這項研究不再改變五注結構，只比較哪 30 個主號進入五注。

## 預註冊 ranker

每一期只使用目標期以前的歷史與已封存 Agent 辯論：

- `consensus`：現行 Agent 辯論支持排序。
- `hot_all`、`gap`：全歷史出現次數與距離上次出現期數。
- `hot/cold_13`、`26`、`52`、`104`：四個固定近期視窗。
- `mix_13`、`26`、`52`、`104`：Agent 共識名次與同期 hot 名次等權相加。

共 15 個 ranker。每個 ranker 選前 30 個不同主號，再以 round-robin 分成
五注；威力彩仍使用開獎前 Agent 第二區排序並讓五注第二區互異。

ranker 函式不接受 `reveal`。每期實際開獎評分完成後，才更新頻率、視窗與
last-seen 狀態。

## 選模與封存規則

資料暖機 60 期；暖機後前 70% 是 development、最近 30% 是 holdout。

主要指標是每期 30 號聯集命中的主號數。development 候選必須：

1. 主號聯集命中平均嚴格高於 `consensus`。
2. 五注最佳主號命中不下降。
3. 至少一注三主號事件率不下降。
4. 完整任一獎級事件率不下降。

最多只選一個候選進 holdout。holdout 的配對 13 期區塊 bootstrap 95%
下界必須大於 0，三個護欄也都不得下降；兩款遊戲都通過才允許替換。
禁止看完 holdout 後改選當時表現較好的另一個 ranker。

另將現行共識直接和公平獨立開獎的精確零模型比較：

- 30 號聯集命中總數使用多期 hypergeometric convolution。
- 三主號與完整任一獎級事件使用全域最優結構的精確 Bernoulli 機率。
- 兩款遊戲共六項單尾檢定使用 Holm family-wise correction。

## 正式 4,082 期結果

| 遊戲 | development 選擇 | holdout 主號聯集差 | 13 期區塊 95% 區間 | 結論 |
|---|---|---:|---:|---|
| 威力彩 | `cold_13` | -0.0178／期 | [-0.1159, +0.0749] | 不升級 |
| 大樂透 | `consensus` | 0 | [0, 0] | development 無合格替代者 |

威力彩的 `cold_13` 在 development 只比共識多 `0.0008` 個聯集命中／期，
到了 561 期 holdout 反而變成負值，且三主號護欄下降 `0.0089`。這正是
封存 holdout 阻止事後過度擬合的案例。

現行共識相對精確均勻零模型：

| 遊戲 | holdout 期數 | 共識聯集命中平均 | 精確零模型 | 超額總命中 | 原始單尾 p | Holm p |
|---|---:|---:|---:|---:|---:|---:|
| 威力彩 | 561 | 4.7273 | 4.7368 | -5.37 | 0.6063 | 1.0000 |
| 大樂透 | 628 | 3.7420 | 3.6735 | +43.06 | 0.0662 | 0.3309 |

大樂透三主號事件的未校正 p 值雖為 `0.0287`，但它是六項檢查之一；Holm
校正後為 `0.1724`，不能挑出單一有利結果宣稱預測成功。

正式結論：`retain_consensus_label_ranking`。這不是證明 Agent 共識能預測
號碼，而是證明目前沒有一個預先固定的歷史 heuristic 通過更嚴格的替換門檻。
在公平模型中，每個號碼標籤仍然等機率。

## 自動 loop 與驗收

偵測到新開獎並凍結下一期後，背景 loop 會更新本研究；研究只寫
`research/results/`，不改寫已凍結票券或 `records/`。

```powershell
python -X utf8 label_signal.py
python -X utf8 label_signal_verify.py --tests-only
```

正式輸出：

- `research/results/label_signal.json`
- `research/results/label_signal_summary.csv`

本系統純模擬，不構成購買或下注建議。
