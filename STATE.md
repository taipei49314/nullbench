# 目前狀態

> 每一輪結束後更新這份檔案；下一輪只需讀它即可接續工作。

## 進度

| 項目 | 數字 |
|---|---|
| core（回歸網） | 57 / 57 GREEN |
| frontier（前線） | 122 / 123 |
| extra | 1 |
| score | 122 |

## 已完成

**L0 地基** —— `State`、`Action`、`Model`、`Invariant`、`Checker` 的最小可用版；BFS 探索、狀態去重、不變量檢查、可重播反例軌跡。

**L1 探索核心** —— `max_depth` / `max_states` 邊界與截斷追蹤、`Result.complete`、`Result.max_depth_reached`、`Result.search`、BFS/DFS 搜尋、完整搜尋的 deterministic deadlocks。截斷搜尋不宣稱 complete，也不回報 deadlock。

**L2 安全性質與反例品質（本輪完成）** —— `stop_on_first`、`Result.violations`、多不變量依宣告順序收集、述詞例外的 fail-closed `Violation.error` 與格式化錯誤訊息；維持 BFS 最短反例、DFS 確定性與獨立重播成立。

**L3 建模語言與訊息袋（本輪完成）** —— 新增 `crucible.dsl.Spec` / `@action`，支援單一或多個初始狀態、參數屬性展開，以及以空後繼序列表示未啟用；新增 `crucible.net` 的不可變多重集訊息袋，支援送出、查詢、單份遞送、重複訊息計數，並維持順序無關與可雜湊。

**L6 狀態爆炸歸約（本輪完成）** —— 新增 `crucible.reduce.symmetry` 與 `partial_order`。前者以明確節點群的 permutation canonical representative 合併對稱狀態；後者只在實際後繼可驗證互換時選取 deterministic persistent action，無法證明獨立時保留完整動作集合。兩者都回傳普通 `Model` 包裝器，反例仍可透過包裝模型自身的 `enabled` / `successors` 重播。

**L7 故障注入（本輪部分完成）** —— 新增 `crucible.faults` 與普通 `Model` 包裝器；`MessageLoss` 會以 deterministic 順序從 `MessageBag` 產生可重播的遺失 action，並以 `faults.used` 及每個 fault 的內部用量欄位限制 budget。`MessageDuplication`、`Crash`、`Partition` 的宣告與基本狀態標記也已具備，後續仍需補齊它們對協定語意的實際影響。

**L8 協定庫（本輪完成）** —— 新增 `crucible.protocols`，提供 Peterson、Dekker、兩階段提交、Raft 選舉、銀行轉帳五組有限且 deterministic 的模型，以及各自共用不變量的 `_broken` 變體；正確版可完整窮舉，錯誤版反例可由模型 action 獨立重播。

## 本輪做了什麼

本輪改做 L8 協定庫：新增 `crucible/protocols.py`，以五個小型有限狀態模型覆蓋 Peterson、Dekker、兩階段提交、Raft 選舉與銀行轉帳；每組都有正確版與只改一個故障點的 `_broken` 變體，並讓兩者共用同名不變量。正確版的搜尋均 `complete=True`，錯誤版的反例均由實際 action 產生，且通過前線的獨立重播。

之所以選它，是因為當時前線 16 條未通過中有 15 條集中在整個 L8 模組不存在；一次完成這個單一路線項目能留下最大的可量測推進，且不需要修改任何裁判檔。L7 的 zero-budget 測試仍保留原狀，避免為迎合衝突的測試期待而改變 `budget=0` 等同關閉故障的語意。

驗收：`python -m unittest tests.test_frontier.TestL8Correct tests.test_frontier.TestL8Broken tests.test_frontier.TestL8Registry -v` 通過 15 條；`python scoreboard.py --pretty` → core `57/57`、frontier `122/123`、score `122`（本輪前 `107`）。另以獨立腳本逐一確認十個 builder 的完整性、判定與反例長度；裁判檔沒有差異。

## 人類裁決事項（優先於下方建議）

上一輪記錄的 `Result.complete` 語意問題已修正：`Checker(Counter(限1000), [under_2])` 現在探索 3 個狀態時會正確回報 `complete=False`，並由額外測試守住。

## 下一輪建議

先由人類裁決 L7 zero-budget 測試與目前規格語意的衝突；若維持 `budget=0` 關閉故障，再補強 MessageDuplication、Crash、Partition 的實際協定行為與獨立重播/budget 測試，最後再考慮協定庫的語意深化。
