# 目前狀態

> 每一輪結束後更新這份檔案；下一輪只需讀它即可接續工作。

## 進度

| 項目 | 數字 |
|---|---|
| core（回歸網） | 57 / 57 GREEN |
| frontier（前線） | 42 / 123 |
| extra | 0 |
| score | 42 |

## 已完成

**L0 地基** —— `State`、`Action`、`Model`、`Invariant`、`Checker` 的最小可用版；BFS 探索、狀態去重、不變量檢查、可重播反例軌跡。

**L1 探索核心** —— `max_depth` / `max_states` 邊界與截斷追蹤、`Result.complete`、`Result.max_depth_reached`、`Result.search`、BFS/DFS 搜尋、完整搜尋的 deterministic deadlocks。截斷搜尋不宣稱 complete，也不回報 deadlock。

**L2 安全性質與反例品質（本輪完成）** —— `stop_on_first`、`Result.violations`、多不變量依宣告順序收集、述詞例外的 fail-closed `Violation.error` 與格式化錯誤訊息；維持 BFS 最短反例、DFS 確定性與獨立重播成立。

## 本輪做了什麼

擴充 `crucible/checker.py` 的 `Checker`、`Result`、`Violation`，並在 `crucible/model.py` 為 `Invariant` 增加保留例外的評估路徑。預設 `stop_on_first=True` 維持既有最短反例行為；關閉後會依探索順序收集所有已探索狀態的不變量違反。述詞拋例外時仍視為違反，但會保存例外並顯示於 `format()`。

驗收：`python scoreboard.py --pretty` → core `57/57`、frontier `42/123`、score `42`（前一輪 `35`）。

## 下一輪建議

優先處理 **L3 建模語言**，先完成 `crucible.dsl.Spec` / `@action` 的參數化 action 展開與單一／多初始狀態，再實作 `crucible.net` 的 deterministic multiset message queue；每完成一組就跑 scoreboard，維持 core 全綠與反例獨立重播。
