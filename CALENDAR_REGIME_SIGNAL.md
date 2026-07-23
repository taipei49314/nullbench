# 開獎星期沒有提高下一期完整六號機率

正式實驗：`calendar-weekday-subset-audit-v1`

## 結論

已知下一期是週一、週二、週四或週五，沒有讓歷史同星期號碼形成可延續的
機率優勢。預註冊候選 `weekday_dirichlet_1_regular` 在兩款遊戲都明確輸給
精確均勻基準：

- 不新增星期 Agent 或 future challenger。
- 不接入 watcher。
- 不修改任何既有前向登記。
- 機率決策維持 `uniform_null_safe`。

## 固定模型與時間邊界

- 威力彩週一／週四、大樂透週二／週五各自維護獨立球號累積次數。
- 第 `t` 期只讀截至第 `t-1` 期的同星期 state，權重固定為次數加
  Laplace `alpha=1`。
- 以 64-state dynamic programming 精確加總目標完整六號集合的 720 個
  無放回順序。
- 大樂透 113 期春節加開保留在時間序列，但在正常星期外一律使用精確均勻
  分布，且不更新正常星期 state。
- 不搜尋月份、節日、農曆日期、期號、prior、窗口或交互作用。

## Proper-score 結果

Regret 是候選完整 subset log loss 減去精確均勻基準；負值才代表候選提高
真正開出集合的機率。

| 指標 | 威力彩 | 大樂透 |
|---|---:|---:|
| 期數 | 1,929 | 2,153 |
| 正常星期外期數 | 0 | 113 |
| 平均 regret（nats／期） | +0.071037257 | +0.084567489 |
| 13 期 block-bootstrap 95% | `[+0.048799167,+0.094467370]` | `[+0.060100001,+0.110596563]` |
| 前半平均 regret | +0.113268349 | +0.130840604 |
| 後半平均 regret | +0.028849928 | +0.038337339 |
| 最近 52 期 | +0.016112093 | +0.044761149 |
| 最近 104 期 | +0.036630980 | +0.037930195 |
| 最近 208 期 | +0.025927548 | +0.029992350 |
| 單期優於均勻比例 | 44.3235% | 39.6656% |
| 最終 e-value | `3.08e-60` | `8.44e-80` |

兩款遊戲的 bootstrap 下界都大於零；前後半及所有近期視窗也全部是正
regret，五項預註冊門檻全數失敗。

候選對真正開出集合給出的幾何平均機率只有均勻基準的：

- 威力彩：`exp(-0.071037257) = 93.1427%`
- 大樂透：`exp(-0.084567489) = 91.8910%`

分星期把可用樣本約切半後，歷史隨機高低被放大成更強的不均勻權重；下一段
資料沒有維持同方向，所以比不分星期的累積頻率模型更差。

## 資料、完整性與驗收

- 494 份官方 raw 月檔、4,082 期，與正式 replay ledger 逐期零不符。
- 威力彩星期分布：週一 964、週四 965。
- 大樂透正常星期：週二 1,020、週五 1,020；正常星期外 113。
- 正常星期外最大絕對 regret 為 0，確認回到均勻且沒有污染 state。
- `records/` 前後 SHA-256：
  `d9ae1a5d3deb3128262c1217f3852db4e091c519e87c674a2e225507dae71509`。
- 專項數學、時間邊界、live recompute 與竄改測試：16／16。
- Python 3.11／3.12 正式 JSON 位元級相同。

正式產物與 hash：

- `research/results/calendar_regime_signal.json`
- artifact SHA-256：
  `a0e00ad11fb50b78a0ba62d63292d5534a5ea14dbab62033d7b7d8d86f90cc6c`
- audit hash：
  `9e2fc29f3b065b0cd34310e93669d0ae73bfdd9d73e0ccb42a730e79debb80bb`
- protocol file SHA-256：
  `dca380031dd6709924fef8b8acc5a7b88d68d94a0b2e7a7edb330164a56a5555`
- protocol payload hash：
  `d6bab38d2f717f2438cd0ed01750a03565fcea5ce60ecda027b0e1cbcb8141ba`

```powershell
python -B -X utf8 calendar_regime_signal.py
python -B -X utf8 calendar_regime_signal_verify.py --tests-only
```

本研究為純模擬，不構成購買或下注建議。
