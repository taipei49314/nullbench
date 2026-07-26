# 目前狀態

> 每一輪結束後更新這份檔案；下一輪只需讀它即可接續工作。

## 進度

| 項目 | 數字 |
|---|---|
| core（回歸網） | 57 / 57 GREEN |
| frontier（前線） | 70 / 123 |
| extra | 0 |
| score | 70 |

## 已完成

**L0 地基** —— `State`、`Action`、`Model`、`Invariant`、`Checker` 的最小可用版；BFS 探索、狀態去重、不變量檢查、可重播反例軌跡。

**L1 探索核心** —— `max_depth` / `max_states` 邊界與截斷追蹤、`Result.complete`、`Result.max_depth_reached`、`Result.search`、BFS/DFS 搜尋、完整搜尋的 deterministic deadlocks。截斷搜尋不宣稱 complete，也不回報 deadlock。

**L2 安全性質與反例品質（本輪完成）** —— `stop_on_first`、`Result.violations`、多不變量依宣告順序收集、述詞例外的 fail-closed `Violation.error` 與格式化錯誤訊息；維持 BFS 最短反例、DFS 確定性與獨立重播成立。

**L3 建模語言與訊息袋（本輪完成）** —— 新增 `crucible.dsl.Spec` / `@action`，支援單一或多個初始狀態、參數屬性展開，以及以空後繼序列表示未啟用；新增 `crucible.net` 的不可變多重集訊息袋，支援送出、查詢、單份遞送、重複訊息計數，並維持順序無關與可雜湊。

## 本輪做了什麼

新增 `crucible.minimize.shrink`，以固定順序的 delta debugging 嘗試移除連續動作區段。每個候選都透過模型的 `enabled` / `successors` 重新播放，並要求最終狀態仍違反至少一個不變量；因此輸出軌跡可獨立重播，不會拼接原軌跡中的狀態。非決定性後繼依宣告順序選擇，結果可重現。

驗收：`python scoreboard.py --pretty` → core `57/57`、frontier `70/123`、score `70`（前一輪 `60`）。L4 的 11 條前線測試全數通過。

## 人類裁決事項（優先於下方建議）

**`Result.complete` 在 `stop_on_first` 命中違反時謊報 `True`。**
實測 `Checker(Counter(限1000), [under_2])` 只探索 3 個狀態（可達 1001 個）卻回報 `complete=True`。
`complete` 的語意是「看遍所有可達狀態」，提前收工不算看完。**請修**，並在 `tests/test_extra.py`
補一條守住它。前線測試沒涵蓋這個情境，所以裁判不會變紅 —— 但它仍然是錯的。
詳見 `SPEC.md` L1 段落。

## 下一輪建議

優先處理人類裁決事項：修正 `stop_on_first` 命中違反時 `Result.complete` 的語意，並在 `tests/test_extra.py` 補測；之後再推進 L5 時序性質。每完成一組都跑 scoreboard，維持 core 全綠。
