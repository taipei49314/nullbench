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
from .temporal import Always, Eventually, LeadsTo, WeakFairness


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

    __slots__ = ("invariant", "trace", "error", "cycle_start")

    def __init__(
        self,
        invariant: str,
        trace: Trace,
        error: Exception | None = None,
        cycle_start: int | None = None,
    ) -> None:
        self.invariant = invariant
        self.trace = trace
        self.error = error
        self.cycle_start = cycle_start

    def __repr__(self) -> str:
        return f"Violation({self.invariant!r}, depth={len(self.trace)})"

    def format(self) -> str:
        detail = f"invariant {self.invariant!r} violated"
        if self.error is not None:
            detail += (
                f" (predicate error: {type(self.error).__name__}: {self.error})"
            )
        return f"{detail}:\n{self.trace.format()}"


class Result:
    """一次檢查的結果。"""

    __slots__ = (
        "violation",
        "states_explored",
        "max_depth_reached",
        "complete",
        "deadlocks",
        "search",
        "violations",
    )

    def __init__(
        self,
        violation: Violation | None,
        states_explored: int,
        max_depth_reached: int,
        complete: bool = True,
        deadlocks: Sequence[State] = (),
        search: str = "bfs",
        violations: Sequence[Violation] = (),
    ) -> None:
        collected = tuple(violations)
        if violation is not None and not collected:
            collected = (violation,)
        elif violation is None and collected:
            violation = collected[0]
        self.violation = violation
        self.states_explored = states_explored
        self.max_depth_reached = max_depth_reached
        self.complete = bool(complete)
        self.deadlocks: tuple[State, ...] = tuple(deadlocks)
        self.search = search
        self.violations: tuple[Violation, ...] = collected

    @property
    def ok(self) -> bool:
        return self.violation is None

    def __repr__(self) -> str:
        verdict = "ok" if self.ok else f"violated:{self.violation.invariant}"
        return (
            f"Result({verdict}, states={self.states_explored}, "
            f"depth={self.max_depth_reached}, complete={self.complete})"
        )


class Checker:
    """對模型做廣度優先窮舉,回報第一個(即最短的)不變量違反。"""

    def __init__(
        self,
        model: Model,
        invariants: Iterable[Invariant] = (),
        max_depth: int | None = None,
        max_states: int | None = None,
        search: str = "bfs",
        stop_on_first: bool = True,
        properties: Iterable[object] = (),
        fairness: Iterable[WeakFairness] = (),
    ) -> None:
        self.model = model
        self.invariants: tuple[Invariant, ...] = tuple(invariants)
        self.max_depth = max_depth
        self.max_states = max_states
        self.search = search
        self.stop_on_first = bool(stop_on_first)
        self.properties: tuple[object, ...] = tuple(properties)
        self.fairness: tuple[WeakFairness, ...] = tuple(fairness)
        for prop in self.properties:
            if not isinstance(prop, (Always, Eventually, LeadsTo)):
                raise TypeError("properties must be Always, Eventually, or LeadsTo")
        for assumption in self.fairness:
            if not isinstance(assumption, WeakFairness):
                raise TypeError("fairness must contain weak_fair assumptions")
        if max_depth is not None and max_depth < 0:
            raise ValueError("max_depth must be non-negative")
        if max_states is not None and max_states < 1:
            raise ValueError("max_states must be at least 1")
        if search not in ("bfs", "dfs"):
            raise ValueError("search must be 'bfs' or 'dfs'")

    def check(self) -> Result:
        initials = self.model.initial_states()
        actions: tuple[Action, ...] = self.model.action_list()

        if self.search == "dfs":
            result = self._check_dfs(initials, actions)
        else:
            result = self._check_bfs(initials, actions)

        # A bounded search cannot establish a liveness property.  Likewise,
        # a safety violation found in stop-on-first mode is already the result
        # the caller requested.
        liveness = tuple(
            prop for prop in self.properties if isinstance(prop, (Eventually, LeadsTo))
        )
        if result.violation is not None or not result.complete or not liveness:
            return result

        temporal = self._temporal_violation(initials, actions, liveness)
        if temporal is None:
            return result
        return Result(
            temporal,
            result.states_explored,
            result.max_depth_reached,
            complete=result.complete,
            deadlocks=result.deadlocks,
            search=result.search,
            violations=(temporal,),
        )

    def _check_bfs(
        self, initials: tuple[State, ...], actions: tuple[Action, ...]
    ) -> Result:
        """以先進先出的 frontier 做窮舉，保留最短反例保證。"""

        # parent[state] = (前驅狀態, 動作名, 來源初始狀態) —— 用來回溯軌跡。
        parent: dict[State, tuple[State | None, str | None, State]] = {}
        queue: deque[tuple[State, int]] = deque()
        deadlocks: list[State] = []
        violations: list[Violation] = []
        max_depth = 0
        truncated = False

        for state in initials:
            if state in parent:
                continue
            if self.max_states is not None and len(parent) >= self.max_states:
                truncated = True
                break
            parent[state] = (None, None, state)
            max_depth = max(max_depth, 0)
            found = self._violations_at(state, parent)
            if found:
                if self.stop_on_first:
                    return self._result(
                        found[0], parent, max_depth, truncated, violations=found[:1]
                    )
                violations.extend(found)
            queue.append((state, 0))

        while queue:
            state, depth = queue.popleft()
            max_depth = max(max_depth, depth)

            if self.max_depth is not None and depth >= self.max_depth:
                has_successor = self._has_successor(state, actions)
                if has_successor:
                    truncated = True
                continue

            has_successor = False
            for action in actions:
                if not action.enabled(state):
                    continue
                successors = action.successors(state)
                if not successors:
                    continue
                has_successor = True
                for succ in successors:
                    if succ in parent:
                        continue
                    if self.max_states is not None and len(parent) >= self.max_states:
                        truncated = True
                        return self._result(
                            None,
                            parent,
                            max_depth,
                            truncated,
                            deadlocks,
                            violations=violations,
                        )
                    parent[succ] = (state, action.name, parent[state][2])
                    max_depth = max(max_depth, depth + 1)
                    found = self._violations_at(succ, parent)
                    if found:
                        if self.stop_on_first:
                            return self._result(
                                found[0],
                                parent,
                                max_depth,
                                truncated,
                                violations=found[:1],
                            )
                        violations.extend(found)
                    queue.append((succ, depth + 1))

            if not has_successor:
                deadlocks.append(state)

        return self._result(
            None, parent, max_depth, truncated, deadlocks, violations=violations
        )

    def _check_dfs(
        self, initials: tuple[State, ...], actions: tuple[Action, ...]
    ) -> Result:
        """以後進先出的 frontier 做 deterministic depth-first search。"""

        parent: dict[State, tuple[State | None, str | None, State]] = {}
        stack: list[tuple[State, int]] = []
        deadlocks: list[State] = []
        violations: list[Violation] = []
        max_depth = 0
        truncated = False

        # 先依宣告順序收集，再反向壓入，讓第一個初始狀態先被處理。
        selected_initials: list[State] = []
        for state in initials:
            if state in parent:
                continue
            if self.max_states is not None and len(parent) >= self.max_states:
                truncated = True
                break
            parent[state] = (None, None, state)
            selected_initials.append(state)
        stack.extend((state, 0) for state in reversed(selected_initials))

        while stack:
            state, depth = stack.pop()
            max_depth = max(max_depth, depth)

            found = self._violations_at(state, parent)
            if found:
                if self.stop_on_first:
                    return self._result(
                        found[0], parent, max_depth, truncated, violations=found[:1]
                    )
                violations.extend(found)

            if self.max_depth is not None and depth >= self.max_depth:
                has_successor = self._has_successor(state, actions)
                if has_successor:
                    truncated = True
                continue

            has_successor = False
            children: list[tuple[State, int]] = []
            for action in actions:
                if not action.enabled(state):
                    continue
                successors = action.successors(state)
                if not successors:
                    continue
                has_successor = True
                for succ in successors:
                    if succ in parent:
                        continue
                    if self.max_states is not None and len(parent) >= self.max_states:
                        truncated = True
                        return self._result(
                            None,
                            parent,
                            max_depth,
                            truncated,
                            deadlocks,
                            violations=violations,
                        )
                    parent[succ] = (state, action.name, parent[state][2])
                    max_depth = max(max_depth, depth + 1)
                    children.append((succ, depth + 1))

            if not has_successor:
                deadlocks.append(state)

            # Keep the model's deterministic action/successor order.
            stack.extend(reversed(children))

        return self._result(
            None, parent, max_depth, truncated, deadlocks, violations=violations
        )

    def _result(
        self,
        violation: Violation | None,
        parent: dict[State, tuple[State | None, str | None, State]],
        max_depth: int,
        truncated: bool,
        deadlocks: Sequence[State] = (),
        violations: Sequence[Violation] = (),
    ) -> Result:
        # Deadlocks are meaningful only after every reachable state was checked.
        ordered_deadlocks = tuple(sorted(deadlocks, key=repr)) if not truncated else ()
        return Result(
            violation,
            len(parent),
            max_depth,
            complete=(
                not truncated
                and not (self.stop_on_first and violation is not None)
            ),
            deadlocks=ordered_deadlocks,
            search=self.search,
            violations=violations,
        )

    @staticmethod
    def _has_successor(state: State, actions: tuple[Action, ...]) -> bool:
        """Return whether any enabled action has at least one real successor."""
        for action in actions:
            if action.enabled(state) and action.successors(state):
                return True
        return False

    def _temporal_violation(
        self,
        initials: tuple[State, ...],
        actions: tuple[Action, ...],
        properties: tuple[Eventually | LeadsTo, ...],
    ) -> Violation | None:
        """Check liveness properties over the completely explored graph.

        A liveness counterexample is searched as a deterministic lasso in the
        subgraph where the obligation remains pending.  The search keeps the
        model's action and successor order, so the reported trace is directly
        replayable by callers.
        """
        action_names = tuple(action.name for action in actions)
        for assumption in self.fairness:
            if assumption.action not in action_names:
                raise ValueError(
                    f"fairness refers to unknown action {assumption.action!r}"
                )

        states, transitions, enabled, parent = self._temporal_graph(initials, actions)

        for prop in properties:
            if isinstance(prop, Eventually):
                roots = tuple(state for state in initials if not self._holds(prop, state))
                root_info = {
                    state: (state, ()) for state in roots
                }

                def expand(state: State) -> tuple[tuple[str, State], ...]:
                    return tuple(
                        (name, successor)
                        for name, successor in transitions[state]
                        if not self._holds(prop, successor)
                    )

                violation = self._find_bad_lasso(
                    prop.name,
                    roots,
                    root_info,
                    expand,
                    transitions,
                    enabled,
                    lambda state: state,
                )
            else:
                roots = tuple(
                    state
                    for state in states
                    if not self._holds(prop.goal, state) and self._holds(prop, state)
                )
                root_info = {
                    state: self._path_from_parent(state, parent) for state in roots
                }

                def expand(state: State) -> tuple[tuple[str, State], ...]:
                    return tuple(
                        (name, successor)
                        for name, successor in transitions[state]
                        if not self._holds(prop.goal, successor)
                    )

                violation = self._find_bad_lasso(
                    prop.name,
                    roots,
                    root_info,
                    expand,
                    transitions,
                    enabled,
                    lambda state: state,
                )

            if violation is not None:
                return violation
        return None

    def _find_bad_lasso(
        self,
        name: str,
        roots: Sequence[State],
        root_info: dict[State, tuple[State, tuple[tuple[str, State], ...]]],
        expand,
        transitions: dict[State, tuple[tuple[str, State], ...]],
        enabled: dict[State, tuple[str, ...]],
        state_of,
    ) -> Violation | None:
        """Find the first fair cycle (or bad terminal) in a pending graph."""
        if not roots:
            return None

        # Product nodes are State objects for the current temporal
        # properties.  Keeping this helper generic makes the ordering rules
        # explicit and leaves room for richer temporal products later.
        parent: dict[object, tuple[object | None, str | None]] = {}
        root_of: dict[object, State] = {}
        queue: deque[object] = deque()
        for root in roots:
            if root in parent:
                continue
            parent[root] = (None, None)
            root_of[root] = root
            queue.append(root)

        adjacency: dict[object, tuple[tuple[str, object], ...]] = {}
        order: list[object] = []
        while queue:
            node = queue.popleft()
            order.append(node)
            edges = tuple(expand(state_of(node)))
            adjacency[node] = edges
            for action, successor in edges:
                if successor in parent:
                    continue
                parent[successor] = (node, action)
                root_of[successor] = root_of[node]
                queue.append(successor)

        for candidate in order:
            cycle = self._cycle_from(candidate, adjacency, state_of)
            if cycle and self._cycle_is_fair(candidate, cycle, enabled, state_of):
                initial, prefix = self._prefix_to(
                    candidate, parent, root_of, root_info, state_of
                )
                cycle_start = len(prefix)
                return Violation(
                    name,
                    Trace(initial, prefix + cycle),
                    cycle_start=cycle_start,
                )

            # A finite path that ends in a deadlock before its obligation is
            # met is also a liveness counterexample, but a state with outgoing
            # edges into the satisfied region is not a deadlock here.
            state = state_of(candidate)
            if not transitions[state]:
                initial, prefix = self._prefix_to(
                    candidate, parent, root_of, root_info, state_of
                )
                return Violation(name, Trace(initial, prefix))
        return None

    def _cycle_is_fair(
        self,
        start: object,
        cycle: tuple[tuple[str, object], ...],
        enabled: dict[State, tuple[str, ...]],
        state_of,
    ) -> bool:
        cycle_nodes = [start]
        cycle_nodes.extend(successor for _, successor in cycle[:-1])
        cycle_states = [state_of(node) for node in cycle_nodes]
        cycle_actions = {action for action, _ in cycle}
        for assumption in self.fairness:
            continuously_enabled = all(
                assumption.action in enabled[state] for state in cycle_states
            )
            if continuously_enabled and assumption.action not in cycle_actions:
                return False
        return True

    @staticmethod
    def _cycle_from(
        start: object,
        adjacency: dict[object, tuple[tuple[str, object], ...]],
        state_of,
    ) -> tuple[tuple[str, object], ...] | None:
        """Return the shortest deterministic path from start back to start."""
        queue: deque[object] = deque([start])
        seen = {start}
        paths: dict[object, tuple[tuple[str, object], ...]] = {start: ()}
        while queue:
            node = queue.popleft()
            path = paths[node]
            for action, successor in adjacency.get(node, ()):
                edge = (action, successor)
                if successor == start:
                    return path + (edge,)
                if successor in seen:
                    continue
                seen.add(successor)
                paths[successor] = path + (edge,)
                queue.append(successor)
        return None

    @staticmethod
    def _prefix_to(
        node: object,
        parent: dict[object, tuple[object | None, str | None]],
        root_of: dict[object, State],
        root_info: dict[State, tuple[State, tuple[tuple[str, State], ...]]],
        state_of,
    ) -> tuple[State, tuple[tuple[str, State], ...]]:
        tail: list[tuple[str, State]] = []
        cursor = node
        while parent[cursor][0] is not None:
            previous, action = parent[cursor]
            tail.append((action or "?", state_of(cursor)))
            cursor = previous
        initial, prefix = root_info[root_of[node]]
        return initial, prefix + tuple(reversed(tail))

    @staticmethod
    def _path_from_parent(
        state: State,
        parent: dict[State, tuple[State | None, str | None, State]],
    ) -> tuple[State, tuple[tuple[str, State], ...]]:
        steps: list[tuple[str, State]] = []
        cursor = state
        while True:
            previous, action, root = parent[cursor]
            if previous is None:
                return root, tuple(reversed(steps))
            steps.append((action or "?", cursor))
            cursor = previous

    @staticmethod
    def _temporal_graph(
        initials: tuple[State, ...], actions: tuple[Action, ...]
    ) -> tuple[
        tuple[State, ...],
        dict[State, tuple[tuple[str, State], ...]],
        dict[State, tuple[str, ...]],
        dict[State, tuple[State | None, str | None, State]],
    ]:
        states: list[State] = []
        seen: set[State] = set()
        parent: dict[State, tuple[State | None, str | None, State]] = {}
        for state in initials:
            if state in seen:
                continue
            seen.add(state)
            states.append(state)
            parent[state] = (None, None, state)

        transitions: dict[State, tuple[tuple[str, State], ...]] = {}
        enabled: dict[State, tuple[str, ...]] = {}
        index = 0
        while index < len(states):
            state = states[index]
            index += 1
            edges: list[tuple[str, State]] = []
            enabled_names: list[str] = []
            for action in actions:
                if not action.enabled(state):
                    continue
                successors = action.successors(state)
                if not successors:
                    continue
                enabled_names.append(action.name)
                for successor in successors:
                    edges.append((action.name, successor))
                    if successor in seen:
                        continue
                    seen.add(successor)
                    states.append(successor)
                    parent[successor] = (state, action.name, parent[state][2])
            transitions[state] = tuple(edges)
            enabled[state] = tuple(enabled_names)
        return tuple(states), transitions, enabled, parent

    @staticmethod
    def _holds(property_or_predicate, state: State) -> bool:
        predicate = getattr(property_or_predicate, "predicate", property_or_predicate)
        try:
            return bool(predicate(state))
        except Exception:
            return False

    # -- 內部 ---------------------------------------------------------------

    def _violations_at(
        self,
        state: State,
        parent: dict[State, tuple[State | None, str | None, State]],
    ) -> tuple[Violation, ...]:
        """依宣告順序回報第一個不成立的不變量。"""
        violations: list[Violation] = []
        checks = self.invariants + tuple(
            prop for prop in self.properties if isinstance(prop, Always)
        )
        for invariant in checks:
            if isinstance(invariant, Invariant):
                holds, error = invariant.evaluate(state)
            else:
                try:
                    holds, error = bool(invariant.predicate(state)), None
                except Exception as exc:
                    holds, error = False, exc
            if not holds:
                violations.append(
                    Violation(
                        invariant.name,
                        self._trace_to(state, parent),
                        error,
                    )
                )
        return tuple(violations)

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
