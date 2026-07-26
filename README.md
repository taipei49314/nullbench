# crucible

確定性協定模型檢查器。把併發／分散式協定丟進熔爐，窮舉狀態空間，
找出違反不變量的**最短反例軌跡**。

**純 Python 標準函式庫。零第三方依賴、不連網、完全決定性。**

## 快速上手

```python
from crucible import Action, Checker, Invariant, Model, State


class Counter(Model):
    def init(self):
        yield State({"n": 0})

    def actions(self):
        yield Action("inc", lambda s: s["n"] < 3, lambda s: [s.set("n", s["n"] + 1)])


result = Checker(Counter(), [Invariant("under_two", lambda s: s["n"] < 2)]).check()
print(result.violation.format())
```

```
invariant 'under_two' violated:
  0. (init) State(n=0)
  1. inc -> State(n=1)
  2. inc -> State(n=2)
```

## 現況

**L0–L8 全部完成**（2026-07-26），前線驗收 123/123、回歸網 57/57。

| 層 | 能力 |
|---|---|
| L0 | `State` / `Action` / `Model` / `Invariant` / `Checker`、BFS 窮舉、狀態去重、反例軌跡 |
| L1 | `max_depth` / `max_states` 邊界、`complete`、死結偵測、BFS/DFS |
| L2 | 多不變量收集、BFS 最短反例保證、述詞例外 fail-closed |
| L3 | `crucible.dsl` 宣告式建模、`crucible.net` 不可變訊息多重集 |
| L4 | `crucible.minimize` 軌跡最小化（delta debugging） |
| L5 | `crucible.temporal` 時序性質、弱公平性、lasso 反例 |
| L6 | `crucible.reduce` 對稱性與偏序歸約 |
| L7 | `crucible.faults` 訊息遺失／重複、崩潰、網路分割 |
| L8 | `crucible.protocols` Peterson、Dekker、兩階段提交、Raft 選舉、銀行轉帳，各配一個故意有 bug 的變體 |

規格與 API 見 [SPEC.md](SPEC.md)。

## 執行測試

```bash
python -m unittest discover -s tests -t .
```

## 驗收

```bash
python scoreboard.py --pretty     # 計分板
python audit.py                   # 外部稽核
```

`scoreboard.py` 直接讀 `unittest` 的結果物件計分，不解析任何文字輸出。
它與 `audit.py`、`tests/test_core.py`、`tests/test_frontier.py` 共同構成
不可變的裁判 —— 開發流程中不得修改。

`audit.py` 專門查凍結的裁判查不到的事：裁判自身完整性、純標準函式庫、
**跨程序**雜湊種子穩定性、`complete` 是否名副其實、協定反例能否獨立重播。
它把「尚未實作」報成 SKIP 而不是 PASS —— 把還沒做算成做對了，正是本專案要防的病灶。

## 為什麼反例可以信

每一條牽涉反例的驗收測試都會把軌跡**重走一遍**，而重播只使用模型自己宣告的
`enabled` / `successors`，不呼叫 crucible 的任何重播程式碼。
假的軌跡、憑空捏造的步驟，都會在重播時被拆穿。
