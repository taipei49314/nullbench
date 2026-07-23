# 前向序列監測與防重複偷看

前向 Loop 會在每次新開獎後重建摘要。如果從第 52 期開始，每新增一期就重算
普通 95% 區間，並在第一次下界大於 0 時宣布成功，長期假陽性率會高於原本
的 5%。`final-judge-forward-v1` 因此改用固定 checkpoint 與 alpha spending；
第一筆結算前又以 `forward-sequential-monitoring-v2` 修正跨遊戲與跨結構
family 的判定。完整凍結稽核見
[FORWARD_MONITORING_V2.md](FORWARD_MONITORING_V2.md)。

## 預註冊檢查點

所有前向推論比較使用相同 checkpoint：

```
52, 104, 208, 416, 832 個合格配對
```

適用範圍：

- 威力彩／大樂透 Qwen－規則的最佳主號命中差。
- 威力彩／大樂透 coverage－規則的最佳主號命中差。
- 威力彩歷史第二區子影子－正式 coverage 的任一獎差。
- 威力彩 guarded／unconstrained 獲利結構－coverage 的嚴格獲利事件差。
- 威力彩共同第二區－當期 baseline 第二區的嚴格獲利事件差。

兩個 checkpoint 之間的新資料只累積，不進入推論區間。例如已有 103 期時，
摘要仍只使用前 52 期的凍結結果；到第 104 期才開第二次 look。若某次
checkpoint 已通過，就在第一次通過時停止並永久保存該次判定；後續資料不會
撤銷或重做這個 experiment。未通過才繼續等下一個 checkpoint，不會用
第 53、54…期反覆試到顯著。

## Alpha spending

原本兩側 95% 區間的 lower-tail alpha 是 `0.025`。五次 look 平均分配：

```
每次 look lower-tail alpha = 0.025 / 5 = 0.005
每次使用 0.5% 與 99.5% bootstrap 分位數
跨五次 look 的 lower-tail family alpha <= 0.025
```

這是 Bonferroni alpha spending，不要求不同 checkpoint 相互獨立。Coverage
與歷史第二區等單一具名 stream 各自是一個預註冊研究問題。

Qwen 的正式升級使用 intersection-union test：只有兩款遊戲都完成的共同
checkpoint 才開封；兩款都必須在該次相同前綴通過主要區間與總主號護欄。
不得把威力彩 52 期的支持和大樂透 104 期的支持拼成整體支持。因為整體拒絕
需要兩個遊戲同時通過，每個遊戲仍使用每 look `0.005`，不再跨兩遊戲除以 2。

Guarded 與 unconstrained 的獲利摘要採任一結構支持即重新審查，因此兩者
共用一個 comparison family：

```
每個結構、每次 look lower-tail alpha = 0.025 / (5 × 2) = 0.0025
跨兩個結構、五次 look 的 lower-tail family alpha <= 0.025
```

共同第二區的兩個獲利結構使用另一個同樣大小的 family。

固定種子零效果常態模擬以 5,000 條、每條 832 期序列同時檢查五個 checkpoint：

| 模擬 | 至少一次假陽性 |
|---|---:|
| 5,000 條零效果序列 | 105 |
| 實測比例 | 2.10% |
| 預註冊上界 | 2.50% |

這個模擬只驗證 alpha-spending 邏輯；正式資料仍使用 13 期循環區塊 bootstrap
2,000 次，以保留短期相依性。

## 決策狀態

每個單一比較會保存：

- `observed_pairs`：帳本已有多少合格配對。
- `evaluated_pairs`：最近完成的 checkpoint；推論只讀此前綴。
- `checkpoint_index` 與 `next_checkpoint`。
- 本次與整個序列的 lower-tail alpha。
- checkpoint 平均差、區間、是否支持及是否已到最後一次 look。

Qwen 另保存 `qwen_joint_sequential_monitor`：

- `observed_pairs_by_game` 與兩遊戲可共同開封的 `common_observed_pairs`。
- `evaluated_pairs_per_game`：兩遊戲實際共同評估的相同前綴。
- 每款遊戲在該共同 checkpoint 的主要區間與總命中護欄。
- `games` 在尚無共同完成 checkpoint 前必須為空，不能顯示個別遊戲的
  提前結果冒充聯合證據。

狀態語意：

- `collecting_forward_data`：尚未到 52，或已完成某次 look 但未通過且仍有
  下一 checkpoint。
- `supported`：某次預註冊 look 的區間下界大於 0，且其他護欄通過。
- `not_supported_final`：832 期最後一次 look 仍未通過；要再測必須開新的
  experiment ID，不得無限追加 checkpoint。

既有 7/20、7/21 登記與號碼完全不變；序列契約只影響未來證據如何解讀。
測試涵蓋 51／52、103／104、832 邊界、兩個 checkpoint 之間資料隔離、
不同遊戲 checkpoint 不得拼接、兩結構 family alpha、固定種子假陽性模擬
及舊帳本相容。本系統純模擬，不構成下注建議。
