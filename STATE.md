# 目前狀態

> 每一輪結束後更新這份檔案。接手的人（或下一輪的你）只讀這份就能繼續。

## 進度

| 項目 | 數字 |
|---|---|
| core（回歸網） | 57 / 57 GREEN |
| frontier（前線） | 12 / 123 |
| extra | 0 |
| score | 12 |

## 已完成

**L0 地基** —— `State`（不可變、可雜湊、排序後 repr）、`Action`（guard + successors）、
`Model`（初始狀態保序去重、動作依名排序）、`Invariant`、`Checker`（BFS 窮舉、狀態去重、
不變量檢查、反例軌跡重建）。

前線一開始就有 12 條是綠的，那是 L0 本來就做對的事：BFS 天生給出最短反例、
不變量依宣告序回報、大狀態空間（1600 狀態）能跑完。**沒有假綠。**

## 上一輪做了什麼

（尚未開始第一輪。）

## 下一輪建議

**L1 探索核心**是最自然的起點，因為 L4 以後的層都要靠它：

1. `Checker` 的 `max_depth` / `max_states` 邊界與 `Result.complete`
   —— 注意「被截斷時不得宣稱 complete，也不得宣稱沒有死結」。
2. `Result.deadlocks`（決定性排序）。
3. `search="dfs"` 與 `Result.search`。

L3 的 `crucible.dsl` 與 `crucible.net` 是 L7 故障注入的前置，優先序也高。

## 環境

- Python 3.9+，純標準函式庫，測試用 `unittest`。
- 驗收：`python scoreboard.py --pretty`
- 完整測試：`python -m unittest discover -s tests -t .`
