# 時間自適應機率 Stacking 診斷預註冊

實驗版本：`temporal-probability-stacking-diagnostic-v1`

凍結日期：`2026-07-19`（Asia/Taipei）

## 問題

現行七專家 stacking 在完整歷史的逐期評分中略差於均勻模型。這項診斷要
回答：問題是否主要來自累積權重反應太慢，固定的 rolling 或 EWMA 時間
衰減能否在完全不讀取當期開獎的條件下，降低完整六號子集 proper-score
regret？

比較的控制組是精確均勻機率。某方法即使比現行 stacking 少輸，只要仍輸給
均勻控制組，就不得稱為提高下一期機率。

## 資料與單位

- 來源：`simulation/results/super.jsonl` 與
  `simulation/results/lotto649.jsonl`。
- 粒度：每款遊戲每期一列。
- 每期必須有五個 Agent 各三組提案、60 次跨 Agent 評論與 15 個有限
  debate score。
- 期別、日期與 sequence 必須嚴格遞增；`decision.history_count` 必須等於
  `sequence - 1`。
- 三個獨立 stream：威力彩主號、威力彩第二區、大樂透主號。

完整歷史已被其他研究使用，因此只作描述性診斷與未來研究設計；不能重新
宣稱歷史確認或直接升級現行策略。

## 固定專家

沿用 `online-probability-stacking-shadow-v1` 的七個專家、Jeffreys
smoothing `0.5` 與 debate temperature `1.0`：

1. 五個既有 Agent。
2. `debate_consensus`。
3. `uniform`。

禁止依本診斷結果新增 Agent、調 smoothing、調 temperature 或改提案來源。

## 固定時間方法

候選家族在執行前固定為九個：

1. `uniform`：精確均勻控制組。
2. `current_cumulative_marginal`：現行 marginal loss 與
   `eta_t=1/sqrt(t)` 更新。
3. `subset_cumulative`：以完整合法無序六號子集 likelihood 更新，
   `eta_t=1/sqrt(t)`。
4. `subset_rolling_52`。
5. `subset_rolling_104`。
6. `subset_rolling_208`。
7. `subset_ewma_52`。
8. `subset_ewma_104`。
9. `subset_ewma_208`。

Rolling 方法只保留最近 W 期的專家 regret，下一期
`log_weight = -sum(regret)/sqrt(n_eff)`。EWMA 方法使用
`decay = 2^(-1/half_life)`，並以折減有效樣本数的平方根縮放。所有權重
只在當期 reveal 之後更新，供下一期使用。

## Proper score

主號不是六次獨立有放回抽樣。對正值號碼質量 `p_i`，合法無序六號子集
`S` 的機率固定定義為：

`P(S) = product(p_i, i in S) / e_6(p_1, ..., p_N)`

其中 `e_6` 是第六階 elementary symmetric polynomial。主號 regret 為
`-log P_model(S) - log C(N,6)`；負值才優於均勻。威力彩第二區使用
categorical log loss，相對均勻 `1/8` 計算 regret。

## 固定診斷指標

每個方法、每個 stream 固定輸出：

- 全期平均 regret 與 13 期 circular moving-block bootstrap 95% 區間。
- 前半、後半平均 regret。
- 最近 52、104、208 期平均 regret。
- 單期優於均勻的比例。
- 最終 uniform 專家權重。
- 相對均勻 likelihood ratio 的 restart-mixture e-process 最終與歷史最大
  e-value。

平均 regret 越低越好；0 是精確均勻控制組。

## 固定決策規則

排除 `uniform` 後，先依下列順序產生描述性 minimax 排名：

1. 三個 stream 平均 regret 的最大值較小。
2. 三個 stream 平均 regret 的平均較小。
3. 方法 ID 字典序較小。

某方法只有同時符合以下全部條件，才可建議建立新的、不可回填 future-only
challenger；這仍不是歷史升級證據：

- 三個 stream 的平均 regret 都小於 0。
- 三個 stream 的 bootstrap 95% 上界都小於 0。
- 三個 stream 的前半與後半平均 regret 都不大於 0。
- 三個 stream 最近 52、104、208 期平均 regret 都不大於 0。
- 三個 stream 的最終 e-value 都至少達 family-wise 門檻 `60`。

沒有方法全數通過時，結論固定為
`retain_existing_null_safe_protocol`，不得接入 watcher。

## Fail-closed

- 當期權重若讀取當期 reveal、期別不連續、來源 ledger 驗證失敗或資料契約
  不完整，整個研究失敗。
- 分布定義域、有限正值、總和、子集 likelihood、權重或 e-process 任一
  無法重建即拒絕。
- 結果必須包含固定 9 方法 × 3 stream 共 27 列；缺列、重複、非有限值、
  protocol hash 或 audit hash 不符即拒絕。
- 不修改 `records/`、前向 ledger、既有登記號碼或正式研究 artifact。

本研究為純模擬。公平開獎下所有合法號碼組合理論等機率，不構成購買或
下注建議。
