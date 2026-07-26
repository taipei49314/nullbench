# 目前狀態

> 每一輪結束後更新這份檔案；下一輪只需讀它即可接續工作。

## 進度

| 項目 | 數字 |
|---|---|
| core（回歸網） | 57 / 57 GREEN |
| frontier（前線） | 107 / 123 |
| extra | 1 |
| score | 107 |

## 已完成

**L0 地基** —— `State`、`Action`、`Model`、`Invariant`、`Checker` 的最小可用版；BFS 探索、狀態去重、不變量檢查、可重播反例軌跡。

**L1 探索核心** —— `max_depth` / `max_states` 邊界與截斷追蹤、`Result.complete`、`Result.max_depth_reached`、`Result.search`、BFS/DFS 搜尋、完整搜尋的 deterministic deadlocks。截斷搜尋不宣稱 complete，也不回報 deadlock。

**L2 安全性質與反例品質（本輪完成）** —— `stop_on_first`、`Result.violations`、多不變量依宣告順序收集、述詞例外的 fail-closed `Violation.error` 與格式化錯誤訊息；維持 BFS 最短反例、DFS 確定性與獨立重播成立。

**L3 建模語言與訊息袋（本輪完成）** —— 新增 `crucible.dsl.Spec` / `@action`，支援單一或多個初始狀態、參數屬性展開，以及以空後繼序列表示未啟用；新增 `crucible.net` 的不可變多重集訊息袋，支援送出、查詢、單份遞送、重複訊息計數，並維持順序無關與可雜湊。

**L6 狀態爆炸歸約（本輪完成）** —— 新增 `crucible.reduce.symmetry` 與 `partial_order`。前者以明確節點群的 permutation canonical representative 合併對稱狀態；後者只在實際後繼可驗證互換時選取 deterministic persistent action，無法證明獨立時保留完整動作集合。兩者都回傳普通 `Model` 包裝器，反例仍可透過包裝模型自身的 `enabled` / `successors` 重播。

**L7 故障注入（本輪部分完成）** —— 新增 `crucible.faults` 與普通 `Model` 包裝器；`MessageLoss` 會以 deterministic 順序從 `MessageBag` 產生可重播的遺失 action，並以 `faults.used` 及每個 fault 的內部用量欄位限制 budget。`MessageDuplication`、`Crash`、`Partition` 的宣告與基本狀態標記也已具備，後續仍需補齊它們對協定語意的實際影響。

## 本輪做了什麼

本輪先推進 L7 的最小可用垂直切片：新增 `crucible/faults.py`，讓 `with_faults(model, faults)` 回傳普通 `Model`，保留原 action 的名稱與後繼，加入 deterministic 的 MessageLoss fault action，並將 fault 使用量寫入狀態。所有 fault 反例仍由包裝模型自身的 `enabled` / `successors` 產生，能通過獨立重播；同時補上 MessageDuplication、Crash、Partition 的基本宣告介面，為後續擴充留下固定狀態表示。

之所以選它，是因為上一輪已完成 L6，而目前前線最大的連續缺口就是 L7；MessageLoss 是最小但能端到端驗證 budget、狀態追蹤、determinism 與反例可信度的一組切片。

上一輪修正 `Checker` 在 `stop_on_first` 找到違反後錯誤回報 `complete=True` 的問題；提前停止代表尚未窮舉所有可達狀態，因此現在正確回報 `False`，並由 `tests/test_extra.py` 回歸測試守住。

同輪推進 L5：新增 `crucible.temporal` 的 `Always`、`Eventually`、`LeadsTo` 與 `weak_fair`，讓 `Checker` 支援時序性質、弱公平假設與可重播的 deterministic lasso 反例；`Violation.cycle_start` 也會指出循環起點。反例搜尋只在完整圖上進行，受 bounds 截斷時不宣稱完成。

驗收：`python scoreboard.py --pretty` → core `57/57`、frontier `107/123`、score `107`（本輪前 `98`）。L7 的 10 條測試通過；剩下的 1 條 zero-budget 測試使用安全性 invariant 檢查合法的「已送出、尚未接收」中間狀態，即使未包裝的原始 Relay 也會失敗，因此沒有為迎合測試而改變 `budget=0` 等同關閉的語意。L6、core 回歸與額外測試維持通過。

## 人類裁決事項（優先於下方建議）

上一輪記錄的 `Result.complete` 語意問題已修正：`Checker(Counter(限1000), [under_2])` 現在探索 3 個狀態時會正確回報 `complete=False`，並由額外測試守住。

## 下一輪建議

完成 L7 剩餘語意：先讓 MessageDuplication 真正驗證重複遞送，再依協定明確的節點/通道表示實作 Crash 與 Partition 的行為約束；補上每種 fault 的獨立重播與 budget 測試，並處理上述 zero-budget 測試的規格裁決。之後再進入 L8 協定庫。
