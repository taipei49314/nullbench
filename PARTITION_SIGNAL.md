# 同 30 號五注分組封存研究

`partition-signal-shadow-v1` 固定現行 Agent 共識選出的 30 個主號，只研究
它們如何分成五注。所有候選均為五注各六號、主號兩兩互斥；依
[STRUCTURAL_OPTIMUM.md](STRUCTURAL_OPTIMUM.md)，它們的完整任一獎級與
三主號理論機率完全相同。

## 固定候選

- `round_robin`：現行方法，依共識名次輪流分到五注。
- `chunks`：每六個連續名次形成一注。
- `snake`：每五個名次正向、反向交替分配。
- `proposal_affinity/anti`：把 Agent 提案中常共同出現的號碼聚合／拆散。
- `history_all_affinity/anti`：全歷史開獎共現聚合／拆散。
- `history_52_affinity/anti`：最近 52 期共現聚合／拆散。
- `seeded_shuffle`：依遊戲與目標期固定種子的可重現隨機分組。

共現資料只更新到目標期之前。`candidate_partitions` 不接受 `reveal`；當期
實際號碼評分後才更新歷史 pair state。

## 選模契約

暖機 60 期；暖機後前 70% 為 development、最近 30% 為 holdout。主要
指標是至少一注命中三個主號的事件率。development 候選必須同時：

1. 三主號事件率嚴格高於 round-robin。
2. 五注最佳主號命中平均不下降。
3. 完整任一獎級事件率不下降。

最多只選一個候選進 holdout。holdout 的三主號配對 13 期區塊 bootstrap
95% 下界必須大於 0，兩個護欄亦不得下降；兩款遊戲都通過才允許升級。

## 正式結果

| 遊戲 | development 選擇 | development 三主號差 | holdout 三主號差 | holdout 95% 區間 |
|---|---|---:|---:|---:|
| 威力彩 | `seeded_shuffle` | +0.0138 | -0.0232 | [-0.0606, +0.0160] |
| 大樂透 | `round_robin` | 0 | 0 | [0, 0] |

威力彩的 development 候選到了 561 期 holdout 明顯反轉：

- 最佳主號命中差：`-0.0143`／期。
- 三主號事件率差：`-0.0232`。
- 完整任一獎級事件率差：`-0.0089`。

大樂透 development 中，部分共現分組的三主號事件率較高，但最佳命中護欄
下降，因此沒有資格進 holdout。威力彩 holdout 的 `chunks` 等方法事後看來
較好，也不能取代 development 事先選定的 `seeded_shuffle`。

正式結論：`retain_round_robin_partition`。沒有證據支持用歷史共現改動
分組；round-robin 保留的理由是其他預先固定候選未通過，不是它能預測號碼。

## 自動重算與驗收

新開獎結算並凍結下一期後，背景 loop 會更新本研究。它只寫
`research/results/`，不修改 `records/` 或已凍結前向帳本。

```powershell
python -X utf8 partition_signal.py
python -X utf8 partition_signal_verify.py --tests-only
```

正式輸出：

- `research/results/partition_signal.json`
- `research/results/partition_signal_summary.csv`

本系統純模擬，不構成購買或下注建議。
