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

L0 地基已完成：`State` / `Action` / `Model` / `Invariant` / `Checker`、
廣度優先窮舉、狀態去重、不變量檢查、反例軌跡重建。

L1–L8（邊界與死結、反例品質、建模語言、軌跡最小化、時序性質、狀態爆炸歸約、
故障注入、協定庫）見 [SPEC.md](SPEC.md)。

## 執行測試

```bash
python -m unittest discover -s tests -t .
```

## 計分板

```bash
python scoreboard.py --pretty
```

`scoreboard.py` 是這個專案的驗收基準，直接讀 `unittest` 的結果物件計分，
不解析任何文字輸出。它與 `tests/test_core.py`、`tests/test_frontier.py`
共同構成不可變的裁判 —— 開發流程中不得修改。

## 為什麼反例可以信

每一條牽涉反例的驗收測試都會把軌跡**重走一遍**，而重播只使用模型自己宣告的
`enabled` / `successors`，不呼叫 crucible 的任何重播程式碼。
假的軌跡、憑空捏造的步驟，都會在重播時被拆穿。
