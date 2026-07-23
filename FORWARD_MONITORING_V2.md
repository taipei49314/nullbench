# 前向決策監控 v2 預註冊

實驗版本：`forward-sequential-monitoring-v2`

凍結時間：`2026-07-19`（Asia/Taipei），第一筆前向結算之前。

凍結時帳本狀態：

- 2 筆開獎前登記、0 筆結算、2 筆 pending。
- 威力彩 2026-07-20 登記 hash：
  `e3c4b0d067fa8208158025356d51496e4376ffcaf657a4a89905744234a493d1`
- 大樂透 2026-07-21 登記 hash：
  `8991e28e95bb2e02c790049a4633c648c6f26bd0a3d620c792a3c8e3e3a1e4d9`
- `records/` SHA-256：
  `d9ae1a5d3deb3128262c1217f3852db4e091c519e87c674a2e225507dae71509`

本修正只改未來摘要如何判定證據，不修改登記、票券、結算 schema、
Agent、Qwen prompt 或正式 `records/`。

## 稽核發現

### Qwen 兩遊戲 checkpoint 未真正聯合

`FORWARD_PREREG.md` 要求威力彩與大樂透在同一 checkpoint 同時通過，
但 v1 摘要各自保存第一次支持：

- 威力彩可能在 52 期支持；
- 大樂透可能在 104 期支持；
- 即使威力彩在前 104 期已反轉，舊摘要仍可能把兩個不同 look 合併成整體
  `qwen_advantage_supported`。

這違反原決策語意。

### 兩個獲利結構未共用 comparison family

`guarded_profit` 與 `unconstrained_profit` 屬同一
`profit-portfolio-consensus-forward-v3` 決策，摘要採任一支持即
`supported`。v1 卻讓兩個結構各自使用完整五次-look lower-tail alpha
`0.025`，整體 family-wise alpha 最多可接近 `0.05`。

`profit-common-special-shadow-forward-v4` 同樣在兩個獲利結構中採任一
支持，需使用相同的兩比較修正。

## v2 凍結規則

固定 checkpoint 保持：

`52／104／208／416／832`

Bootstrap 保持：

- 統計單位：每款遊戲每個 eligible 前向配對。
- 主要差值與既有 v1 相同。
- 13 期 circular moving-block bootstrap。
- 2,000 次固定種子重抽。

### Qwen joint checkpoint

新增單一 `qwen_joint_sequential_monitor`：

1. 只評估兩款遊戲都已完成的共同 checkpoint。
2. 在每個共同 checkpoint，兩款遊戲都只讀各自 eligible 序列的相同前綴
   長度。
3. 同一 checkpoint 內，兩款遊戲的最佳主號命中差區間下界都必須大於 0。
4. 同一前綴內，兩款遊戲的總主號命中平均差都必須不小於 0。
5. 只在上述四條同時成立時停止並支持；不得拼接不同 checkpoint。
6. 兩款遊戲共同到 832 仍未同時通過，才是 `not_supported_final`。

Qwen 每個遊戲、五次 look 的 lower-tail alpha 維持
`0.025 / 5 = 0.005`。整體決策是 intersection-union test：必須兩款同時
通過，不採任一遊戲支持，因此不再額外除以 2。

### Profit comparison family

兩個獲利結構採 Bonferroni：

`每個結構、每次 look lower-tail alpha = 0.025 / (5 looks × 2 structures) = 0.0025`

所以 guarded／unconstrained 共十次可能檢查的 lower-tail family alpha
不超過 `0.025`。v4 的共同第二區兩結構使用另一個同樣大小的獨立 family。
壓力淨額差仍只作描述，不能替代嚴格獲利事件主要指標。

### 其他比較

- Coverage-vs-rule：每款遊戲是獨立、具名 shadow 問題，維持每 stream
  五次-look family alpha `0.025`；沒有「任一遊戲即全域升級」狀態。
- 歷史第二區-vs-coverage：只有威力彩一個比較，維持 `0.025`。
- 不新增 checkpoint，不依未來結果改 family 大小。

## 資料品質與 fail-closed

- Qwen 分母只含 Qwen 與 rule 同一期皆 eligible 的 settlement。
- Coverage 分母只含 coverage 與 rule 同一期皆 eligible。
- Profit 與共同第二區只含開獎前已存在、certificate／hash 完整且 parent
  coverage eligible 的配對。
- 晚登、Qwen 降級、coverage fallback、缺少 shadow、重複登記或重複結算
  不得進入對應分母。
- Joint monitor 必須拒絕 primary／total 長度不一致、未知／缺少遊戲、
  非有限值及多餘指標欄位；checkpoint 只能讀程式內已凍結的遞增常數。
- `status.json` 仍只是可重建快照；append-only JSONL 是唯一事實源。

## 驗收

測試必須至少涵蓋：

- 威力彩 52 支持、大樂透 104 支持但威力彩 104 反轉，不得聯合支持。
- 兩款同在 104 通過時才支持。
- 一款 103、一款 104 時只能開共同 52 前綴。
- 832 共同前綴的 final 狀態。
- Profit family 每 look alpha 精確為 `0.0025`。
- 51／52、103／104 邊界、晚登、降級、缺值、重複結算與舊帳本相容。
- 既有兩筆登記 hash、`records/` hash 與 0 settlement 狀態不變。

本系統為純模擬，不構成購買或下注建議。

## 實作封存驗收

2026-07-19 實作後的正式驗收：

- 監控、Goal 與前向驗證定向測試：`76 passed`。
- 前向、回饋、Qwen、維運與同步整合測試：`120 passed`。
- 完整後端回歸：`457 passed`，耗時 `434.89s`。
- 前端：`17 passed`，ESLint 與 production build 通過。
- 現場摘要重建：`forward-sequential-monitoring-v2`、
  `collecting_forward_data`、共同樣本 `0`、下次共同 checkpoint `52`。
- 正式 `records/` hash 仍為
  `d9ae1a5d3deb3128262c1217f3852db4e091c519e87c674a2e225507dae71509`。
- 前向 JSONL hash 為
  `7d67d09bcc7da46ed58c02e40852d03afba0e45d18ed5bc6870c9c84f79002f9`；
  重建摘要前後未改變。
- Goal 唯讀稽核狀態為 `waiting`；只缺 2026-07-20 威力彩與
  2026-07-21 大樂透的未來正式開獎，沒有當前資料品質阻斷。
