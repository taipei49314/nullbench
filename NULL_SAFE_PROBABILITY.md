# 公平零模型安全機率研究

## 結論

目前沒有足夠證據讓號碼機率偏離均勻分布。

新的 `null-safe-probability-forward-shadow-v1` 候選因此會把完整主號機率
與威力彩第二區機率設為精確均勻，同時保留 consensus coverage 的五注
標籤與全域最優分散結構。它不把 `1–30`、熱號、冷號或最近漏號當成較可能。

這項改動改善的是機率校準：消除現行 stacking 在無訊號時仍保留的微小
正 regret。它不改變公平彩券的理論中獎率，也不是歷史升級證據。

## 資料與比較基準

| 遊戲／維度 | 期數 | 現行 mixture regret | Null-safe regret | 最大 restart e-value |
|---|---:|---:|---:|---:|
| 威力彩主號 | 1,929 | +0.002950648399 | 0 | 1.000000 |
| 威力彩第二區 | 1,929 | +0.000751655989 | 0 | 1.038536 |
| 大樂透主號 | 2,153 | +0.004108485760 | 約 0 | 2.180271 |

regret 是模型 log loss 減均勻基準 log loss，越低越好。主號採完整無序
六號子集 log loss；第二區採 categorical log loss。Null-safe 的歷史
regret 歸零，是因三個 gate 從未開啟，預測全程等於公平基準。這個完整
子集量尺與舊 stacking 報告的六個 marginal loss 平均不同，兩者不可混用。

## 為什麼不採用現行微小偏移

以合法無序六號子集 likelihood 計算，現行 mixture 相對均勻的累積
log likelihood ratio 為：

- 威力彩主號：`-5.691801`
- 威力彩第二區：`-1.449944`
- 大樂透主號：`-8.845570`

負值表示完整歷史沒有支持這些非均勻偏移。可重啟 mixture e-process 的
最高值也只有 `2.18`，距離固定啟用門檻 `60` 很遠。

即使把描述性門檻放寬到 `3` 或 `20`，三個 stream 的歷史啟用期數仍全部
為 0。正式門檻不因這個結果改動。

## 下一期候選如何工作

候選 hash：

`2969f5207b94d0726e09dd5db9b858c774cb669fd2231c0cf4b5944eb1a0a3a1`

目前狀態：

- 威力彩主號 gate：關閉
- 威力彩第二區 gate：關閉
- 大樂透主號 gate：關閉

所以候選只會保留 coverage 號碼與分組，完整機率分布使用均勻基準。未來若
某個維度在開獎前累積到 `E >= 60`，只有該維度才允許使用 stacking 分布。

## 證據邊界

這份 4,082 期回放用於方法檢查與狀態初始化，不是新的確認性 holdout。
候選只能在新的 future-only experiment 下登記；既有 7/20、7/21 號碼與
hash 不變。

在新候選累積足夠前向 proper score 前，正確說法是「消除無證據偏移」，
不是「已提高下一期中獎率」。

## 自動 loop 狀態

v7 前向契約已接入 watcher。下一次真實揭曉後，系統會先結算舊 v6 登記，
再用最新 reveal 更新 stacking 權重；null-safe 的 operational state 只複製
這些新權重、ledger hash 與 fitted-through，**不會**讓 v6 結果推進
e-process。gate 每次都從凍結的正式基線，加上帳本內全部已驗證 v7
proper-score 結算決定性重建，因此重跑與晚到結算不會重複或漏算。只有
開獎前已封存的 v7 capsule 才能更新下一期 gate。7/20、7/21 現有登記與
hash 不變，也不構成 v7 證據；第一筆確認性轉移只能來自其後真正建立並
揭曉的 v7 新目標期。

## 重現

```powershell
python -B -X utf8 null_safe_probability.py
python -B -X utf8 null_safe_probability_verify.py --tests-only
```

正式產物：
`research/results/null_safe_probability.json`

純模擬，不構成購買或下注建議。
