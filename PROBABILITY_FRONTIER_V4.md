# 完整六主號機率前緣 v4

正式實驗：`main-subset-probability-frontier-v4`

## 結論

加入跨遊戲最近一期 overlap 模型後，精確均勻 `uniform_null_safe` 仍是
14 個完整六主號 proper-score 方法的雙遊戲 minimax champion。

13 個非均勻方法在威力彩與大樂透的平均 regret 全部大於 0，均被均勻模型
嚴格支配。沒有方法同時通過兩款平均 regret `<0` 與 bootstrap 95% 上界
`<0`，所以不新增 Agent、future challenger 或 watcher integration。

## v4 唯一變更

v3 的 13 列與正式 artifact 完全不改。v4 無條件新增
`cross_game_overlap_dirichlet_null_1`：

- 威力彩 regret：`+0.023938`
- 大樂透 regret：`+0.008117`
- 跨遊戲平均 regret：`+0.016027`
- minimax regret：`+0.023938`
- 最差遊戲幾何平均機率比：`97.6346%`
- 正式排名：第 11

它比抽出位置、持續球號頻率及星期模型接近均勻，但仍比前十名差，且在兩款
遊戲都被均勻嚴格支配。

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
| 11 | `cross_game_overlap_dirichlet_null_1` | +0.023938 | 97.6346% |
| 12 | `position_dirichlet_1` | +0.030719 | 96.9748% |
| 13 | `persistent_dirichlet_1` | +0.049229 | 95.1963% |
| 14 | `weekday_dirichlet_1_regular` | +0.084567 | 91.8910% |

最佳非均勻方法仍是 `subset_cumulative`；它實際上把權重推回近乎 100%
uniform，並非找到更可能開出的號碼。

## 決策與完整性

- 正式機率維持精確均勻 null-safe。
- 停止用同一歷史搜尋跨遊戲球號轉移、lag、窗口或 prior。
- 五注可維持已證明的完全分散 coverage，但不宣稱號碼標籤更可能開出。
- 只接受開獎前封存、不可回填的未來完整 subset proper score。
- v1–v3 artifacts 維持 immutable。

```powershell
python -B -X utf8 probability_frontier_v4.py
python -B -X utf8 probability_frontier_v4_verify.py --tests-only
```

正式 artifact：`research/results/probability_frontier_v4.json`

- v4 來源、映射、排序、live recompute 與竄改測試：15／15。
- Python 3.11／3.12 位元級相同。
- artifact SHA-256：
  `6fbae1477e440b62bdafdedff1648991c49ca8429bb2846b4712353c3f0b868a`
- audit hash：
  `d26af2422ab6a74f9cd7aa397d92b8285e1d176e118085042976df9d13246cde`
- protocol file SHA-256：
  `e6c1706420c5c2f76642407915fc7d7a2962391977ac2660c0cc4fd9dd8a26e0`
- protocol payload hash：
  `2c2f7578f247be044486ecd96ec4035da3db3d48370978899354c2884aa02103`
- `records/` 維持
  `d9ae1a5d3deb3128262c1217f3852db4e091c519e87c674a2e225507dae71509`。

完整固定來源與決策規則見 `PROBABILITY_FRONTIER_V4_PROTOCOL.md`。本研究為
純模擬，不構成購買或下注建議。
