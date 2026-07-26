# 目前狀態

> 每一輪結束後更新這份檔案；下一輪只需讀它即可接續工作。

## 進度

| 項目 | 數字 |
|---|---|
| core（回歸網） | 57 / 57 GREEN |
| frontier（前線） | 98 / 123 |
| extra | 1 |
| score | 98 |

## 已完成

**L0 地基** —— `State`、`Action`、`Model`、`Invariant`、`Checker` 的最小可用版；BFS 探索、狀態去重、不變量檢查、可重播反例軌跡。

**L1 探索核心** —— `max_depth` / `max_states` 邊界與截斷追蹤、`Result.complete`、`Result.max_depth_reached`、`Result.search`、BFS/DFS 搜尋、完整搜尋的 deterministic deadlocks。截斷搜尋不宣稱 complete，也不回報 deadlock。

**L2 安全性質與反例品質（本輪完成）** —— `stop_on_first`、`Result.violations`、多不變量依宣告順序收集、述詞例外的 fail-closed `Violation.error` 與格式化錯誤訊息；維持 BFS 最短反例、DFS 確定性與獨立重播成立。

**L3 建模語言與訊息袋（本輪完成）** —— 新增 `crucible.dsl.Spec` / `@action`，支援單一或多個初始狀態、參數屬性展開，以及以空後繼序列表示未啟用；新增 `crucible.net` 的不可變多重集訊息袋，支援送出、查詢、單份遞送、重複訊息計數，並維持順序無關與可雜湊。

**L6 狀態爆炸歸約（本輪完成）** —— 新增 `crucible.reduce.symmetry` 與 `partial_order`。前者以明確節點群的 permutation canonical representative 合併對稱狀態；後者只在實際後繼可驗證互換時選取 deterministic persistent action，無法證明獨立時保留完整動作集合。兩者都回傳普通 `Model` 包裝器，反例仍可透過包裝模型自身的 `enabled` / `successors` 重播。

## 本輪做了什麼

本輪完成 L6：新增 `crucible.reduce`，提供對稱性與偏序兩種狀態空間歸約。對稱性會對每個狀態套用群置換並取固定的最小代表；偏序歸約會以 local diamond 檢查確認動作兩兩 commute，只有全體獨立時採 deterministic 單一動作，否則不砍狀態。這讓 L6 的 12 條前線測試全數通過，且維持獨立重播所需的模型語意。

上一輪修正 `Checker` 在 `stop_on_first` 找到違反後錯誤回報 `complete=True` 的問題；提前停止代表尚未窮舉所有可達狀態，因此現在正確回報 `False`，並由 `tests/test_extra.py` 回歸測試守住。

同輪推進 L5：新增 `crucible.temporal` 的 `Always`、`Eventually`、`LeadsTo` 與 `weak_fair`，讓 `Checker` 支援時序性質、弱公平假設與可重播的 deterministic lasso 反例；`Violation.cycle_start` 也會指出循環起點。反例搜尋只在完整圖上進行，受 bounds 截斷時不宣稱完成。

驗收：`python scoreboard.py --pretty` → core `57/57`、frontier `98/123`、score `98`（本輪前 `86`）。L6 的 12 條前線測試、core 回歸與額外測試全數通過。

## 人類裁決事項（優先於下方建議）

上一輪記錄的 `Result.complete` 語意問題已修正：`Checker(Counter(限1000), [under_2])` 現在探索 3 個狀態時會正確回報 `complete=False`，並由額外測試守住。

## 下一輪建議

推進 L7 故障注入，建議先實作 `MessageLoss` 與 `with_faults` 的最小可重播模型包裝，再補 `MessageDuplication`、`Crash`、`Partition`；務必讓 `faults.used` 進入狀態並遵守 budget，且每個 fault action 的反例都能被前線測試獨立重播。持續以 deterministic 順序、完整性與 core 57/57 作為驗收重點。
