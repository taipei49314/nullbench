# 完整六主號機率前緣 v2

正式實驗：`main-subset-probability-frontier-v2`

## 結論

加入預先指定的相鄰期重複數模型後，精確均勻 `uniform_null_safe` 仍是 12 個
可比較方法的雙遊戲 minimax champion。

11 個非均勻方法在威力彩與大樂透的平均完整 subset regret 都大於 0，全部被均勻
模型嚴格支配。沒有方法同時達到兩款平均 regret `<0` 與 bootstrap 95% 上界
`<0`，所以沒有新 Agent、future challenger 或 watcher integration。

## v2 的唯一變更

v1 的 11 列、分數、區間與原始 artifact 完全不改。v2 無條件加入
`lag_overlap_dirichlet_null_1` 的 raw prequential proper score；不加入其
null-safe 列，因為歷史 gate 從未啟用，該列與均勻控制完全相同。

新模型排名第 10：

- 威力彩 regret：`+0.009077`
- 大樂透 regret：`+0.007868`
- minimax regret：`+0.009077`
- 最差遊戲幾何平均機率比：`99.0964%`

它比六位置模型與持續球號頻率模型接近均勻，但仍比前九名差，且在兩款遊戲都被
均勻嚴格支配。

## 正式排名

| 排名 | 方法 | minimax regret | 最差遊戲機率比 |
| ---: | --- | ---: | ---: |
| 1 | `uniform_null_safe` | 0 | 100.0000% |
| 2 | `subset_cumulative` | +0.001456 | 99.8545% |
| 3 | `subset_ewma_104` | +0.001513 | 99.8488% |
| 4 | `subset_ewma_208` | +0.001531 | 99.8470% |
| 5 | `subset_rolling_208` | +0.001549 | 99.8452% |
| 6 | `subset_ewma_52` | +0.001550 | 99.8451% |
| 7 | `subset_rolling_104` | +0.001593 | 99.8408% |
| 8 | `subset_rolling_52` | +0.002038 | 99.7965% |
| 9 | `current_cumulative_marginal` | +0.004108 | 99.5900% |
| 10 | `lag_overlap_dirichlet_null_1` | +0.009077 | 99.0964% |
| 11 | `position_dirichlet_1` | +0.030719 | 96.9748% |
| 12 | `persistent_dirichlet_1` | +0.049229 | 95.1963% |

最佳非均勻方法仍是 `subset_cumulative`。它之所以最接近均勻，是因為把 stacking
權重推回近乎 100% uniform，不是找到一組較容易開出的號碼。

## 決策

- 正式機率保持精確均勻 null-safe。
- 五注仍可使用已證明的完全分散 coverage 結構，但不宣稱號碼標籤較可能開出。
- 停止在同一歷史上繼續調 lag prior、窗口或 overlap 變體。
- 只等待開獎前封存、不可回填的 v7 未來完整 subset proper score。
- v1 artifact 與 audit hash 保持 immutable。

## 執行、測試與完整性

```powershell
python -B -X utf8 probability_frontier_v2.py
python -B -X utf8 probability_frontier_v2_verify.py --tests-only
```

正式 artifact：`research/results/probability_frontier_v2.json`

- v2 契約、映射、排序、來源、live recompute 與竄改測試：16／16。
- Python 3.11／3.12 與正式輸出位元級相同。
- artifact SHA-256：
  `ca2c88e6bb438350d4cda3607877f47eb752489a7cfcb3efeca1df886062e2d8`
- audit hash：
  `c0a7790906298c5801b0ea89975a671fbb47b864e19ec252610d29fb4456f031`
- protocol file SHA-256：
  `ce5f0f31d9285a0a25e01dfca1c1e1ad2fa5fd8c6c9c53e225033c1611480357`
- protocol payload hash：
  `dcfa5fcf89fcc0dddcafab7a3f040a00dd75ba118510f4147b7b48e189a09978`
- `records/` 維持
  `d9ae1a5d3deb3128262c1217f3852db4e091c519e87c674a2e225507dae71509`。

完整固定來源、方法與決策規則見 `PROBABILITY_FRONTIER_V2_PROTOCOL.md`。本研究為
純模擬，不構成購買或下注建議。
