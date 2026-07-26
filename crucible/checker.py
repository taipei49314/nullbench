"""狀態空間探索與安全性質檢查。

L0 地基:廣度優先窮舉、狀態去重、不變量檢查、反例軌跡重建。

廣度優先是刻意的選擇 —— 它讓「第一個找到的反例」同時就是**最短**的反例,
而最短反例是人類能讀懂的反例。
"""

from __future__ import annotations

from collections import deque
from typing import Iterable, Sequence

from .model import Action, Invariant, Model
from .state import State


class Trace:
    """從某個初始狀態走到目標狀態的一條路徑。"""

    __slots__ = ("initial", "steps")

    def __init__(self, initial: State, steps: Sequence[tuple[str, State]]) -> None:
        self.initial = initial
        self.steps: tuple[tuple[str, State], ...] = tuple(steps)

    @property
    def final(self) -> State:
        return self.steps[-1][1] if self.steps else self.initial

    @property
    def states(self) -> tuple[State, ...]:
        return (self.initial,) + tuple(s for _, s in self.steps)

    def __len__(self) -> int:
        return len(self.steps)

    def __repr__(self) -> str:
        return f"Trace(len={len(self.steps)}, final={self.final!r})"

    def format(self) -> str:
        """人類可讀的軌跡輸出。"""
        lines = [f"  0. (init) {self.initial!r}"]
        for i, (action, state) in enumerate(self.steps, start=1):
            lines.append(f"  {i}. {action} -> {state!r}")
        return "\n".join(lines)


class Violation:
    """一個不變量被違反的證據。"""

    __slots__ = ("invariant", "trace")

    def __init__(self, invariant: str, trace: Trace) -> None:
        self.invariant = invariant
        self.trace = trace

    def __repr__(self) -> str:
        return f"Violation({self.invariant!r}, depth={len(self.trace)})"

    def format(self) -> str:
        return f"invariant {self.invariant!r} violated:\n{self.trace.format()}"


class Result:
    """一次檢查的結果。"""

    __slots__ = ("violation", "states_explored", "max_depth_reached")

    def __init__(
        self,
        violation: Violation | None,
        states_explored: int,
        max_depth_reached: int,
    ) -> None:
        self.violation = violation
        self.states_explored = states_explored
        self.max_depth_reached = max_depth_reached

    @property
    def ok(self) -> bool:
        return self.violation is None

    def __repr__(self) -> str:
        verdict = "ok" if self.ok else f"violated:{self.violation.invariant}"
        return f"Result({verdict}, states={self.states_explored}, depth={self.max_depth_reached})"


class Checker:
    """對模型做廣度優先窮舉,回報第一個(即最短的)不變量違反。"""

    def __init__(self, model: Model, invariants: Iterable[Invariant] = ()) -> None:
        self.model = model
        self.invariants: tuple[Invariant, ...] = tuple(invariants)

    def check(self) -> Result:
        initials = self.model.initial_states()
        actions: tuple[Action, ...] = self.model.action_list()

        # parent[state] = (前驅狀態, 動作名, 來源初始狀態) —— 用來回溯軌跡。
        parent: dict[State, tuple[State | None, str | None, State]] = {}
        queue: deque[tuple[State, int]] = deque()
        max_depth = 0

        for state in initials:
            if state in parent:
                continue
            parent[state] = (None, None, state)
            violation = self._first_violation(state, parent)
            if violation is not None:
                return Result(violation, len(parent), 0)
            queue.append((state, 0))

        while queue:
            state, depth = queue.popleft()
            max_depth = max(max_depth, depth)
            for action in actions:
                if not action.enabled(state):
                    continue
                for succ in action.successors(state):
                    if succ in parent:
                        continue
                    parent[succ] = (state, action.name, parent[state][2])
                    violation = self._first_violation(succ, parent)
                    if violation is not None:
                        return Result(violation, len(parent), max(max_depth, depth + 1))
                    queue.append((succ, depth + 1))

        return Result(None, len(parent), max_depth)

    # -- 內部 ---------------------------------------------------------------

    def _first_violation(
        self,
        state: State,
        parent: dict[State, tuple[State | None, str | None, State]],
    ) -> Violation | None:
        """依宣告順序回報第一個不成立的不變量。"""
        for invariant in self.invariants:
            if not invariant.holds(state):
                return Violation(invariant.name, self._trace_to(state, parent))
        return None

    @staticmethod
    def _trace_to(
        state: State,
        parent: dict[State, tuple[State | None, str | None, State]],
    ) -> Trace:
        steps: list[tuple[str, State]] = []
        cursor = state
        while True:
            prev, action, root = parent[cursor]
            if prev is None:
                return Trace(root, tuple(reversed(steps)))
            steps.append((action or "?", cursor))
            cursor = prev
