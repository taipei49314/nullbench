# 目前狀態

> 每一輪結束後更新這份檔案；下一輪只需讀它即可接續工作。

## 進度

| 項目 | 數字 |
|---|---|
| core（回歸網） | 57 / 57 GREEN |
| frontier（前線） | 86 / 123 |
| extra | 1 |
| score | 86 |

## 已完成

**L0 地基** —— `State`、`Action`、`Model`、`Invariant`、`Checker` 的最小可用版；BFS 探索、狀態去重、不變量檢查、可重播反例軌跡。

**L1 探索核心** —— `max_depth` / `max_states` 邊界與截斷追蹤、`Result.complete`、`Result.max_depth_reached`、`Result.search`、BFS/DFS 搜尋、完整搜尋的 deterministic deadlocks。截斷搜尋不宣稱 complete，也不回報 deadlock。

**L2 安全性質與反例品質（本輪完成）** —— `stop_on_first`、`Result.violations`、多不變量依宣告順序收集、述詞例外的 fail-closed `Violation.error` 與格式化錯誤訊息；維持 BFS 最短反例、DFS 確定性與獨立重播成立。

**L3 建模語言與訊息袋（本輪完成）** —— 新增 `crucible.dsl.Spec` / `@action`，支援單一或多個初始狀態、參數屬性展開，以及以空後繼序列表示未啟用；新增 `crucible.net` 的不可變多重集訊息袋，支援送出、查詢、單份遞送、重複訊息計數，並維持順序無關與可雜湊。

## 本輪做了什麼

修正 `Checker` 在 `stop_on_first` 找到違反後錯誤回報 `complete=True` 的問題；提前停止代表尚未窮舉所有可達狀態，因此現在正確回報 `False`，並新增 `tests/test_extra.py` 回歸測試。

同輪推進 L5：新增 `crucible.temporal` 的 `Always`、`Eventually`、`LeadsTo` 與 `weak_fair`，讓 `Checker` 支援時序性質、弱公平假設與可重播的 deterministic lasso 反例；`Violation.cycle_start` 也會指出循環起點。反例搜尋只在完整圖上進行，受 bounds 截斷時不宣稱完成。

驗收：`python scoreboard.py --pretty` → core `57/57`、frontier `86/123`、score `86`（前一輪 `70`）。L5 的 16 條前線測試與額外測試全數通過。

## 人類裁決事項（優先於下方建議）

上一輪記錄的 `Result.complete` 語意問題已修正：`Checker(Counter(限1000), [under_2])` 現在探索 3 個狀態時會正確回報 `complete=False`，並由額外測試守住。

## 下一輪建議

推進 L6 狀態爆炸歸約，建議先做 `symmetry(model, groups=...)`：以 canonical representative 保留判定結果，並用前線測試量測狀態數確實下降；完成後再做 `partial_order`。持續以 deterministic 順序與獨立重播作為驗收重點。
