# 完整六主號機率前緣

正式實驗：`main-subset-probability-frontier-v1`

## 結論

在目前所有能以同一把尺公平比較的模型中，`uniform_null_safe` 是威力彩與
大樂透的 minimax champion。納入的 10 個非均勻方法，在兩款遊戲的完整六主號
子集合平均 regret 都大於 0，全部被均勻模型嚴格支配。

因此：

- 正式機率分布維持精確均勻 null-safe。
- 不把任何歷史候選接入 Agent、shadow 或 watcher。
- 停止在同一份歷史上繼續搜尋窗口、衰減率、prior 或欄位組合。
- 只有開獎前封存、不可回填的 v7 未來完整 subset proper score，才有資格改變
  這個決策。

這不表示未來永遠不可能發現偏差，而是目前 4,082 期正式歷史沒有支持任何已測
非均勻方法。把較差的歷史模型拿來選號，會降低而不是提高實際開獎組合所得的機率。

## 公平比較的量尺

每個候選都必須在看見當期開獎前，對全部合法無序六主號組合給出總和為 1 的正機率。
每期分數為：

`候選 negative log probability - 精確均勻 negative log probability`

單位是 `nats／期`。平均 regret 小於 0 才代表候選給實際開獎組合的幾何平均機率
高於均勻；大於 0 代表較低。跨遊戲排名先比較兩款 regret 中較差的一個
`minimax_regret`，再比較兩款的等權平均。

威力彩使用 1,929 期（2008-01-24 至 2026-07-16），大樂透使用 2,153 期
（2007-01-02 至 2026-07-17）。兩款歷史、日期範圍與 ledger hash 在四個來源
artifact 間完全一致。

## 正式排名

| 排名 | 方法 | 威力彩 regret | 大樂透 regret | minimax regret | 最差遊戲機率比 |
| ---: | --- | ---: | ---: | ---: | ---: |
| 1 | `uniform_null_safe` | 0 | 0 | 0 | 100.0000% |
| 2 | `subset_cumulative` | +0.001456 | +0.000261 | +0.001456 | 99.8545% |
| 3 | `subset_ewma_104` | +0.001513 | +0.000244 | +0.001513 | 99.8488% |
| 4 | `subset_ewma_208` | +0.001531 | +0.000215 | +0.001531 | 99.8470% |
| 5 | `subset_rolling_208` | +0.001549 | +0.000194 | +0.001549 | 99.8452% |
| 6 | `subset_ewma_52` | +0.001550 | +0.000333 | +0.001550 | 99.8451% |
| 7 | `subset_rolling_104` | +0.001593 | +0.000201 | +0.001593 | 99.8408% |
| 8 | `subset_rolling_52` | +0.002038 | +0.000297 | +0.002038 | 99.7965% |
| 9 | `current_cumulative_marginal` | +0.002951 | +0.004108 | +0.004108 | 99.5900% |
| 10 | `position_dirichlet_1` | +0.024462 | +0.030719 | +0.030719 | 96.9748% |
| 11 | `persistent_dirichlet_1` | +0.039638 | +0.049229 | +0.049229 | 95.1963% |

「最差遊戲機率比」是 `exp(-minimax_regret)`。例如歷史頻率模型在較差遊戲中，
給實際開獎六號集合的幾何平均機率只有均勻的 95.1963%。

排名第二的 `subset_cumulative` 只是最接近均勻的非均勻方法，不是已發現訊號。
它在兩款遊戲的平均 regret 仍為正，bootstrap 95% 上界也都大於 0；它的改善來源
是迅速把 stacking 權重推回近乎 100% 均勻。

## 沒有混入的指標

以下研究各有用途，但不能回答「下一期完整六主號組合的機率是否提高」，所以沒有
混入排名：

- 舊 stacking 的 marginal mass loss。
- top-30、最佳一注、票券命中或任一獎事件。
- 五注 coverage、獎級、成本後獲利與其他效用指標。
- 威力彩第二區與大樂透特別號。
- 任何看過結果後才選擇的窗口、prior、遊戲或欄位。

五注完全分散仍能最佳化既定五注的聯集覆蓋結構，但不會讓某個六號標籤更容易被公平
開獎抽出。這兩個問題必須分開。

## 未來翻盤門檻

歷史結果只用來決定目前 champion，不直接 promotion。任何非均勻候選都必須：

1. 在新目標期開獎前封存完整合法六主號分布。
2. 不回填舊期數，也不依當期結果修改預測。
3. 在兩款遊戲的平均 regret 都小於 0。
4. 在兩款遊戲的預註冊 block-bootstrap 95% 上界都小於 0。
5. 只在固定 checkpoint 評估，並通過 v7 sequential evidence gate。

未達門檻時，系統持續輸出模擬票券，但正式機率保持 null-safe；票券標籤由已證明的
coverage 結構決定，不宣稱號碼本身較可能開出。

## 可重現性與完整性

```powershell
python -B -X utf8 probability_frontier.py
python -B -X utf8 probability_frontier_verify.py --tests-only
```

正式 artifact：
`research/results/probability_frontier.json`

- 11 個固定方法，四個來源 artifact。
- 專項契約、live recompute 與竄改測試：14／14。
- Python 3.11、3.12 與正式輸出位元級相同。
- artifact SHA-256：
  `68f467fb68bbf17eb647ce940c0ca46ffd88a4598614158d55179ae12d315af3`
- audit hash：
  `9690bb28e6ca295e541e62e1b3c99e297e4ef8370a031869b5818764eb46e4b7`
- protocol SHA-256：
  `55e48d67336c0f81d5b8c4e3620152a54e69a49d9310b48d7d37e79022749274`
- `records/` 在研究前後維持
  `d9ae1a5d3deb3128262c1217f3852db4e091c519e87c674a2e225507dae71509`。

完整預註冊規格見 `PROBABILITY_FRONTIER_PROTOCOL.md`。本研究為純模擬，不構成購買
或下注建議。
