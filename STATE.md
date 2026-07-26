# 目前狀態

> 每一輪結束後更新這份檔案。接手的人（或下一輪的你）只讀這份就能繼續。

## 進度

| 項目 | 數字 |
|---|---|
| core（回歸網） | 57 / 57 GREEN |
| frontier（前線） | 35 / 123 |
| extra | 0 |
| score | 35 |

## 已完成

**L0 地基** —— `State`（不可變、可雜湊、排序後 repr）、`Action`（guard + successors）、
`Model`（初始狀態保序去重、動作依名排序）、`Invariant`、`Checker`（BFS 窮舉、狀態去重、
不變量檢查、反例軌跡重建）。

**L1 探索核心（本輪完成）** —— `max_depth` / `max_states` 驗證與截斷追蹤、
`Result.complete`、`Result.max_depth_reached`、`Result.search`、BFS/DFS 搜尋、
可重播且 deterministic 的 DFS 反例、完整搜尋的 deterministic deadlocks。
界線上的實際後繼會使結果標記為 incomplete；截斷搜尋一律不宣稱 deadlock。

## 本輪做了什麼

擴充 `crucible/checker.py` 的 `Result` 與 `Checker`，保留既有 L0 行為，並完成 L1 前線測試要求。
BFS 維持最短反例；DFS 依排序後的 action 與 successors 順序探索；狀態上限不會納入超額狀態，
深度上限不會展開界線外狀態；只有完整窮舉才回傳排序後的 deadlocks。

驗收：`python scoreboard.py --pretty` → core `57/57`、frontier `35/123`、score `35`。

## 下一輪建議

優先處理 **L2 安全性質與反例品質**：加入 `stop_on_first` / `violations`、述詞例外的 `Violation.error`
與格式化錯誤訊息，同時維持 BFS 最短反例與獨立重播成立。之後再進入 L3 DSL / network。
