# crucible — 確定性協定模型檢查器 規格書

把併發／分散式協定丟進熔爐，**窮舉狀態空間**，找出違反不變量的**最短反例軌跡**，
並注入故障（訊息遺失、重排、重送、節點崩潰、網路分割）看它還撐不撐得住。

**純 Python 標準函式庫實作。零第三方依賴、不連網、不讀寫工作目錄以外的檔案。**

---

## 核心立場

一個模型檢查器最容易犯的錯，是**宣稱檢查過但其實沒檢查到**。所以本專案的驗收建立在兩件事上：

1. **已知有 bug 的協定必須被抓到**，而且吐出的反例要能被**獨立重播**確認為真。
2. **已知正確的協定不得誤報**。

反例的重播驗證由測試自己實作（只使用模型本身的 action 語意），**不呼叫 crucible 的重播程式碼**。
因此無法用「特判」或「回傳漂亮字串」蒙混——假的反例會在重播時被拆穿。

---

## 公開 API

```python
from crucible import State, Action, Model, Invariant, Checker

class Counter(Model):
    def init(self):
        yield State({"n": 0})

    def actions(self):
        yield Action("inc", lambda s: s["n"] < 3, lambda s: [s.set("n", s["n"] + 1)])

result = Checker(Counter(), invariants=[Invariant("n_small", lambda s: s["n"] < 3)]).check()
result.ok                      # False
result.violation.invariant     # "n_small"
result.violation.trace.steps   # (("inc", State({"n": 1})), ("inc", ...), ("inc", State({"n": 3})))
```

### `State`

不可變映射。可雜湊、可比較、`repr` 決定性（鍵依序排列）。

| 成員 | 語意 |
|---|---|
| `State(mapping)` | 由 dict 建構；值必須可雜湊 |
| `s[key]` | 讀取；缺鍵拋 `KeyError` |
| `s.get(key, default)` | 讀取，可給預設 |
| `s.set(key, value)` | **回傳新 State**，原狀態不變 |
| `s.update(mapping)` | 回傳套用多個鍵的新 State |
| `s.keys()` / `s.items()` | 依鍵排序後回傳 |
| `hash(s)` / `s == t` | 值相等即相等 |

### `Action`

| 成員 | 語意 |
|---|---|
| `Action(name, enabled, successors)` | `enabled(state) -> bool`；`successors(state) -> Iterable[State]` |
| `.name` | 動作名稱。同一模型內必須唯一 |

`successors` 可回傳多個後繼狀態（表達非決定性）。回傳空序列等同未啟用。

### `Model`

覆寫兩個方法：

- `init(self) -> Iterable[State]` —— 初始狀態（可多個）
- `actions(self) -> Iterable[Action]` —— 動作集合

### `Invariant`

`Invariant(name, predicate)`。`predicate(state) -> bool`。
**述詞自身拋出例外時視為違反**（fail-closed，不得靜默吞掉）。

### `Checker`

```python
Checker(model, invariants=(), max_depth=None, max_states=None)
```

`check() -> Result`：

| `Result` 成員 | 語意 |
|---|---|
| `.ok` | 是否無違反 |
| `.violation` | `Violation` 或 `None` |
| `.states_explored` | **相異**狀態數 |
| `.max_depth_reached` | 最深層數 |
| `.complete` | 是否窮舉完畢（未被 `max_depth` / `max_states` 截斷） |
| `.deadlocks` | 無任何啟用動作的狀態（tuple，決定性排序） |

`Violation` 成員：`.invariant`（名稱字串）、`.trace`。

`Trace` 成員：`.initial`（初始 `State`）、`.steps`（`(action_name, state)` 的 tuple）、`.final`、`len(trace)`。

### 決定性要求（不可協商）

同一模型、同一參數，**任意兩次執行必須產生位元相同的結果**：探索順序、狀態計數、反例軌跡皆同。
達成方式：初始狀態依 `init()` 產出順序、動作依 `name` 排序、後繼依 `successors()` 產出順序、BFS 佇列先進先出。

**不得依賴 `set` 或 `dict` 的迭代順序來決定探索順序**，也不得依賴 `hash()` 的執行期隨機化。

---

## 分層路線圖

**L0 為已完成的地基**（最小可用的 BFS 探索 + 安全性質檢查），L1 起為前線（frontier）。

| 層級 | 主題 | 內容 |
|---|---|---|
| **L0** | 地基 ✅ | `State` / `Action` / `Model` / `Invariant` / `Checker` 的最小可用版；BFS 探索、狀態去重、不變量檢查、反例軌跡 |
| **L1** | 探索核心 | `max_depth` / `max_states` 邊界與 `.complete`、死結偵測、決定性保證、大狀態空間的效能 |
| **L2** | 安全性質與反例 | 多不變量按宣告序回報、**BFS 最短反例保證**、初始態違反、述詞例外 fail-closed |
| **L3** | 建模語言 | `@action` 宣告式風格、參數化動作、guard／effect 分離、節點集合、訊息通道原語 |
| **L4** | 反例最小化 | delta debugging 縮短軌跡；最小化後仍須合法且違反；不得長於 BFS 深度 |
| **L5** | 時序性質 | `always` / `eventually`、弱公平性假設、lasso（前綴＋循環）反例與其重播 |
| **L6** | 狀態爆炸歸約 | 對稱性歸約、偏序歸約；**歸約前後結論必須一致**且實測狀態數確有下降 |
| **L7** | 故障注入 | 訊息遺失／重排／重送、節點崩潰與重啟、網路分割、故障預算上限 |
| **L8** | 協定庫 | Peterson、Dekker、兩階段提交、Raft 選舉、銀行轉帳；**每個都配一個故意有 bug 的變體** |

> 前線層級是**建議方向而非硬性順序**。若判斷有更有價值的改善點（效能、錯誤訊息品質、
> 文件、額外測試覆蓋），可自行選擇——只要能在計分板上留下可量測的推進。

---

## 前線 API 藍圖

以下是各層預期的形狀。**`tests/test_frontier.py` 才是最終規格**——藍圖與測試衝突時以測試為準。

### L1 —— 探索核心

```python
Checker(model, invariants=(), max_depth=None, max_states=None, search="bfs")
```

- `search` 為 `"bfs"`（預設）或 `"dfs"`，其他值拋 `ValueError`；`max_depth < 0`、`max_states < 1` 亦然。
- `Result.complete` —— **語意是「這次搜尋是否看遍了所有可達狀態」**，只有佇列真正見底才是 `True`。
  被 `max_depth` / `max_states` 截斷要為 `False`；**因為找到違反而提前收工（`stop_on_first`）
  也要為 `False`** —— 提前停下來同樣沒看完。

  > **人類裁決（2026-07-26）**：目前的實作在 `stop_on_first` 命中違反時回報 `complete=True`。
  > 實測 `Checker(Counter(限1000), [under_2])` 只探索了 1001 個可達狀態中的 3 個，卻宣稱窮舉完畢。
  > 這正是本專案要防的那類缺陷。**這是缺陷，請修。** 前線測試沒有涵蓋這個情境
  > （裁判不會因此變紅，但它仍然是錯的），修好後請在 `tests/test_extra.py` 補一條守住它。
- `Result.deadlocks` —— 無任何啟用動作的狀態，決定性排序。**搜尋被截斷時一律回傳空 tuple**
  （沒看完的地方不能宣稱那裡沒有死結）。
- `Result.search` —— 實際採用的策略名稱。

### L2 —— 安全性質與反例

```python
Checker(model, invariants, stop_on_first=True)
```

- `Result.violations` —— tuple。`stop_on_first=True` 時最多一筆；`False` 時蒐集全部。
- **最短反例保證**：BFS 找到的反例深度必須是最小的。
- `Violation.error` —— 述詞自身拋例外時記錄該例外，否則為 `None`；`format()` 要帶出錯誤訊息。

### L3 —— 建模語言

```python
from crucible.dsl import Spec, action

class Mutex(Spec):
    nodes = ("n1", "n2")

    def init(self):
        return State({"pc.n1": "idle", "pc.n2": "idle"})   # 單一狀態或可迭代皆可

    @action(params="nodes")          # 展開成 enter(n1)、enter(n2)
    def enter(self, s, node):
        if s["pc." + node] != "idle":
            return []                # 空清單 == 未啟用
        return [s.set("pc." + node, "critical")]
```

`params` 指向類別屬性名；該屬性不存在要拋例外。無 `params` 時動作名即方法名。

```python
from crucible import net

net.empty()                          # 空訊息袋（可雜湊，可放進 State）
net.send(state, "net", ("hello",))   # 回傳新 state
net.pending(state, "net")            # tuple，決定性排序
net.deliver(state, "net", ("hello",))# 移除一份；不存在則拋例外
```

訊息袋是**多重集合**：送出順序不影響相等性，但重複訊息要分別計數。

### L4 —— 反例最小化

```python
from crucible.minimize import shrink
shrink(model, invariants, trace) -> Trace
```

輸出必須仍是合法且違反的軌跡、不得比輸入長、必須是決定性且冪等的。

### L5 —— 時序性質

```python
from crucible.temporal import Always, Eventually, LeadsTo, weak_fair
Checker(model, properties=[...], fairness=[weak_fair("inc")])
```

- liveness 反例是 **lasso**：`Violation.cycle_start` 是循環起點在 `trace.states` 中的索引，
  且 `trace.states[cycle_start] == trace.states[-1]`。安全性反例的 `cycle_start` 為 `None`。
- `weak_fair` 指向不存在的動作要拋例外。

### L6 —— 歸約

```python
from crucible.reduce import symmetry, partial_order
symmetry(model, groups=[("n1", "n2", "n3")]) -> Model
partial_order(model) -> Model
```

**歸約的唯一驗收標準是結論一致**：歸約後的判定必須與未歸約完全相同，而且狀態數確實下降。
砍掉狀態卻改變判定，比不做歸約更糟。

### L7 —— 故障注入

```python
from crucible.faults import with_faults, MessageLoss, MessageDuplication, Crash, Partition
with_faults(model, [MessageLoss(budget=1)]) -> Model
```

- 故障用量記在狀態的 `faults.used` 欄位，不得超過預算總和；`budget=0` 等同關閉；負預算拋例外。
- 注入故障後的模型仍是普通 `Model`，反例照樣要能獨立重播。

### L8 —— 協定庫

```python
from crucible.protocols import catalog, peterson, peterson_broken, ...
catalog() -> Iterable[str]
peterson() -> (Model, Iterable[Invariant])
```

五組：`peterson`、`dekker`、`two_phase_commit`、`raft_election`、`bank_transfer`，
各配一個 `_broken` 變體。**錯誤版必須與正確版用完全相同的不變量受審**——換一把尺就等於沒抓到。
模型要小到能窮舉完（`complete` 為 `True`），反例要短到人類讀得完（≤ 20 步）。

---

## 不變式（任何一輪都不得違反）

1. **純標準函式庫** —— 不得 `pip install`，不得 import 任何第三方套件。
2. **回歸網不得破** —— `tests/test_core.py` 必須永遠全綠。
3. **不得竄改裁判** —— `scoreboard.py`、`tests/test_core.py`、`tests/test_frontier.py` 是驗收基準，
   **不可修改**。任何改動都會被自動還原並記為違規。
   - 若真心認為某條測試寫錯了，**不要改它**——在回覆裡說明理由，由人類裁決。
   - **可以也歡迎**新增自己的測試檔（如 `tests/test_extra.py`），會計入 `extra` 分數。
4. **不連網、不碰工作目錄以外的檔案。**
5. **決定性不得退化** —— 任何引入 `set` 迭代序、`hash()` 隨機化、時間、亂數的做法都是缺陷。
   若需亂數，必須是固定種子且可重現。
6. **不得執行 `git commit`** —— 外層流程會在閘門綠燈後自動原子提交。你只管改檔案。

---

## 驗收方式

```bash
python scoreboard.py
```

輸出 JSON：`core`（回歸網，必須全綠）與 `frontier`（前線，轉綠即為進展）。
`core_green` 為 `false` 時該輪進展分直接歸零。
