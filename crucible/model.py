"""模型與性質的宣告介面。

一個 `Model` 就是「初始狀態」加上「動作集合」。動作用 guard(`enabled`)與
後繼函式(`successors`)描述,後繼可回傳多個狀態以表達非決定性。
"""

from __future__ import annotations

from typing import Callable, Iterable

from .state import State


class ModelError(Exception):
    """模型宣告本身有問題(例如動作重名)。"""


class Action:
    """一個具名的狀態轉移。

    `enabled(state) -> bool` 是 guard;`successors(state) -> Iterable[State]` 產生後繼。
    後繼回傳空序列等同於未啟用。
    """

    __slots__ = ("name", "_enabled", "_successors")

    def __init__(
        self,
        name: str,
        enabled: Callable[[State], bool],
        successors: Callable[[State], Iterable[State]],
    ) -> None:
        if not isinstance(name, str) or not name:
            raise ModelError(f"action name must be a non-empty str, got {name!r}")
        self.name = name
        self._enabled = enabled
        self._successors = successors

    def enabled(self, state: State) -> bool:
        return bool(self._enabled(state))

    def successors(self, state: State) -> tuple[State, ...]:
        """回傳後繼狀態。順序即為探索順序,因此必須是決定性的。"""
        result = tuple(self._successors(state))
        for item in result:
            if not isinstance(item, State):
                raise ModelError(
                    f"action {self.name!r} yielded {type(item).__name__}, expected State"
                )
        return result

    def __repr__(self) -> str:
        return f"Action({self.name!r})"


class Model:
    """待檢查的協定模型。子類別覆寫 `init` 與 `actions`。"""

    def init(self) -> Iterable[State]:
        raise NotImplementedError("Model.init must be overridden")

    def actions(self) -> Iterable[Action]:
        raise NotImplementedError("Model.actions must be overridden")

    # -- 給檢查器用的正規化入口 ---------------------------------------------

    def initial_states(self) -> tuple[State, ...]:
        """初始狀態,保持 `init()` 的產出順序(去重但不重排)。"""
        seen: set[State] = set()
        ordered: list[State] = []
        for state in self.init():
            if not isinstance(state, State):
                raise ModelError(
                    f"init() yielded {type(state).__name__}, expected State"
                )
            if state not in seen:
                seen.add(state)
                ordered.append(state)
        if not ordered:
            raise ModelError("model has no initial state")
        return tuple(ordered)

    def action_list(self) -> tuple[Action, ...]:
        """動作集合,依名稱排序 —— 探索順序不得受宣告順序或 dict 迭代序影響。"""
        actions = tuple(self.actions())
        names = [a.name for a in actions]
        duplicates = sorted({n for n in names if names.count(n) > 1})
        if duplicates:
            raise ModelError(f"duplicate action names: {', '.join(duplicates)}")
        return tuple(sorted(actions, key=lambda a: a.name))


class Invariant:
    """狀態述詞。每個被發現的狀態都會被檢查。

    述詞自身拋出例外時視為違反(fail-closed)—— 靜默吞掉例外會讓檢查器
    宣稱「檢查過」但其實什麼都沒驗到。
    """

    __slots__ = ("name", "_predicate")

    def __init__(self, name: str, predicate: Callable[[State], bool]) -> None:
        if not isinstance(name, str) or not name:
            raise ModelError(f"invariant name must be a non-empty str, got {name!r}")
        self.name = name
        self._predicate = predicate

    def holds(self, state: State) -> bool:
        try:
            return bool(self._predicate(state))
        except Exception:
            return False

    def __repr__(self) -> str:
        return f"Invariant({self.name!r})"
