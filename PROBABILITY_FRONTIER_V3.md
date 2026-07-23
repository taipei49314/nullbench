# 完整六主號機率前緣 v3

正式實驗：`main-subset-probability-frontier-v3`

## 結論

把預註冊開獎星期模型無條件加入後，精確均勻 `uniform_null_safe` 仍是
13 個完整六主號 proper-score 方法的雙遊戲 minimax champion。

12 個非均勻方法在威力彩與大樂透的平均 regret 全部大於 0，均被精確均勻
模型嚴格支配。沒有方法同時達到兩款平均 regret `<0` 與 bootstrap 95%
上界 `<0`，所以不新增 Agent、future challenger 或 watcher integration。

## v3 唯一變更

v2 的 12 列、分數、區間與原始 artifact 完全不改。v3 新增
`weekday_dirichlet_1_regular`：

- 威力彩 regret：`+0.071037`
- 大樂透 regret：`+0.084567`
- 跨遊戲平均 regret：`+0.077802`
- minimax regret：`+0.084567`
- 最差遊戲幾何平均機率比：`91.8910%`
- 正式排名：第 13

它是目前最差的非均勻完整 subset 方法；星期分組減少樣本後放大噪音，沒有
產生可重現機率。

## 正式排名

| 排名 | 方法 | minimax regret | 最差遊戲機率比 |
|---:|---|---:|---:|
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
| 13 | `weekday_dirichlet_1_regular` | +0.084567 | 91.8910% |

最佳非均勻方法仍是 `subset_cumulative`。它只把 stacking 權重推回近乎
100% uniform，並沒有找到較容易開出的號碼。

## 決策

- 正式機率保持精確均勻 null-safe。
- 五注可以使用已證明的完全分散 coverage 結構，但不得宣稱特定號碼標籤
  更可能開出。
- 停止在同一歷史調星期、月份、節日、窗口或 prior。
- 只接受開獎前封存且不可回填的未來完整 subset proper score。
- v1、v2 artifact 與 audit hash 維持 immutable。

## 執行、測試與完整性

```powershell
python -B -X utf8 probability_frontier_v3.py
python -B -X utf8 probability_frontier_v3_verify.py --tests-only
```

正式 artifact：`research/results/probability_frontier_v3.json`

- v3 來源、映射、排序、live recompute 與竄改測試：15／15。
- Python 3.11／3.12 正式輸出位元級相同。
- artifact SHA-256：
  `00b11aa187a02daf281a1e32b19ec0be36d0b25fb02b6edab6a562457b541fa9`
- audit hash：
  `245f74f34e8445c5d7f7965aa37422ad7b819ec8e5ccde571c8ebd526c2d6ae4`
- protocol file SHA-256：
  `30b76be981abc9620ff7443abbbff5b27148afa63876b0817f6c3d47db2a75aa`
- protocol payload hash：
  `b4f5607a26b545fa8e4fbdbbab5b2eb7c4ca4dfedf7ccb85034ed2df010f2e28`
- `records/` 維持
  `d9ae1a5d3deb3128262c1217f3852db4e091c519e87c674a2e225507dae71509`。

完整固定來源、方法與決策規則見 `PROBABILITY_FRONTIER_V3_PROTOCOL.md`。
本研究為純模擬，不構成購買或下注建議。
