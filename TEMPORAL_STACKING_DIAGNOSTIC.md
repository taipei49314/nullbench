# 時間衰減沒有找到可升級的號碼訊號

## 結論

Rolling 與 EWMA 沒有讓七專家 stacking 穩定勝過精確均勻機率。固定九種
方法、三個 stream 的完整 prequential 診斷中，沒有任何非均勻方法通過
全期、bootstrap、前後半、最近視窗與 e-value 的共同門檻。

正式決策是 `retain_existing_null_safe_protocol`：不增加 Agent、不把時間
衰減接入 watcher，也不修改既有前向號碼。

## 資料與量尺

- 威力彩：1,929 期，2008-01-24 至 2026-07-16。
- 大樂透：2,153 期，2007-01-02 至 2026-07-17。
- 主號使用完整合法無序六號子集 log loss。
- 威力彩第二區使用 categorical log loss。
- 表中 regret 為模型 loss 減均勻 loss；負值才代表優於均勻。
- 每一期 forecast 都在讀取當期 reveal 前完成。

## 主要結果

| Stream | 現行 marginal 權重法（精確 subset score） | subset cumulative regret | 損失縮減 |
|---|---:|---:|---:|
| 威力彩主號 | +0.002950648 | +0.001456066 | 50.65% |
| 威力彩第二區 | +0.000751656 | +0.000751656 | 0% |
| 大樂透主號 | +0.004108486 | +0.000260540 | 93.66% |

`subset_cumulative` 是描述性 minimax 最佳方法，但三個平均 regret 仍都大於
0，bootstrap 95% 上界也都大於 0，因此只能解讀為「更快停止相信無效專家」，
不能解讀為找到較準號碼。

主號的 subset cumulative 在後半資料已把 uniform 專家權重推到近乎 100%，
後半與最近 52／104／208 期 regret 因而接近 0。這不是新訊號，而是模型
退回均勻控制的結果。

## 時間衰減為何更差

Rolling／EWMA 會持續忘記較早的負面證據，讓非均勻 Agent 權重重新上升。
問題在威力彩第二區最明顯：

| 方法 | 第二區平均 regret | 最近 52 期 regret | 最終 uniform 權重 |
|---|---:|---:|---:|
| subset cumulative | +0.000752 | 約 0 | 99.999844% |
| EWMA 208 | +0.006159 | +0.012638 | 77.521615% |
| Rolling 208 | +0.009485 | +0.021976 | 61.088086% |
| Rolling 52 | +0.025985 | +0.068768 | 40.267009% |

較短視窗越容易重新追逐隨機波動，並沒有形成可重複的機率優勢。

## 對現行系統的影響

1. 維持 null-safe family-wise e-value 門檻 60。
2. Gate 關閉時繼續使用精確均勻機率與既有 coverage 結構。
3. 不新增時間衰減 Agent；更多 Agent 不會自動提高準確率。
4. 保留 `subset_cumulative` 作研究基準，但除非建立新 experiment ID 並
   累積不可回填的未來 proper score，否則不得接入 watcher。

## 可稽核產物

- Protocol：`TEMPORAL_STACKING_PROTOCOL.md`
- 程式：`research/temporal_stacking_diagnostic.py`
- 結果：`research/results/temporal_stacking_diagnostic.json`
- Audit hash：
  `cd4b3427762146210a7db520a1c387bc01d4adedafe66b16675655a6ae465266`

本研究為純模擬。公平開獎下所有合法號碼組合理論等機率，不構成購買或
下注建議。
