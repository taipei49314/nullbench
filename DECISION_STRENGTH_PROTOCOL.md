# 號碼決策強度稽核契約

實驗版本：`probability-label-decision-strength-audit-v1`

凍結日期：`2026-07-19`（Asia/Taipei）

## 問題

機率 stacking 已把均勻專家權重推到接近 1，但 top-30 仍必須輸出確定的
30 個號碼。本稽核只量化「軟機率差」與「硬性號碼清單」之間的尺度差，
不重開歷史 holdout，也不建立新的號碼變體。

## 指標

- `selected_mass_lift`：混合分布前 k 名總質量減去 `k / 號碼池`。
- `model_implied_expected_hit_lift`：主號為
  `6 × selected_mass_lift`；威力彩第二區為 `1 × selected_mass_lift`。
- 公平基準變異：固定 k 個號碼與一次開獎交集數的精確超幾何變異。
- 可偵測尺度：單尾 alpha `0.005`、power `0.80` 的常態近似，
  checkpoint 固定為 `52／104／208／416／832`。
- 同時報告 total variation、相對均勻最大最小 spread、KL divergence、
  top-k 邊界 gap 與邊界同分數號碼數。

## 解讀限制

可偵測尺度是規劃診斷，不是新的歷史顯著性檢定。歷史結果只可決定：

1. 號碼清單是否承載可辨識的模型差異。
2. 是否應在既有 v5 之外增加新的比較 family。

不得用本稽核升級策略、改寫 7/20 或 7/21 號碼、重設 v5 checkpoint，
也不得把 top-k 清單描述為已有實質較高的開出率。

若軟效果低於 832 期可偵測尺度，維持既有 v5 future-only shadow，
不增加新標籤變體。真正的升級證據仍只來自預先登記的未來配對。
