"""Deterministic fault-injection model wrappers.

Faults are model actions rather than checker special cases.  That keeps every
counterexample produced by a fault-enabled model replayable through the model
itself, just like an ordinary action trace.
"""

from __future__ import annotations

from typing import Iterable, Sequence

from .model import Action, Model
from .net import MessageBag, deliver, send
from .state import State


_USED_KEY = "faults.used"
_USAGE_PREFIX = "faults.used."


class FaultError(ValueError):
    """Raised when a fault declaration is malformed."""


class Fault:
    """Base class for a bounded, state-changing fault action."""

    kind = "fault"

    def __init__(self, budget: int = 1) -> None:
        if isinstance(budget, bool) or not isinstance(budget, int):
            raise TypeError("fault budget must be an integer")
        if budget < 0:
            raise ValueError("fault budget must be non-negative")
        self.budget = budget

    def candidates(self, state: State) -> tuple[object, ...]:
        """Return deterministic choices available in *state*."""

        return ()

    def apply(self, state: State, choice: object) -> State:
        """Apply one fault choice, without updating the usage counters."""

        raise NotImplementedError


class MessageLoss(Fault):
    """Drop one pending message from any :mod:`crucible.net` channel."""

    kind = "message_loss"

    def candidates(self, state: State) -> tuple[tuple[str, object], ...]:
        choices: list[tuple[str, object]] = []
        for channel, value in state.items():
            if not isinstance(value, MessageBag):
                continue
            for message in value.pending():
                choice = (channel, message)
                if choice not in choices:
                    choices.append(choice)
        return tuple(choices)

    def apply(self, state: State, choice: object) -> State:
        channel, message = _message_choice(choice, self.kind)
        return deliver(state, channel, message)


class MessageDuplication(Fault):
    """Duplicate one pending message in any :mod:`crucible.net` channel."""

    kind = "message_duplication"

    def candidates(self, state: State) -> tuple[tuple[str, object], ...]:
        choices: list[tuple[str, object]] = []
        for channel, value in state.items():
            if not isinstance(value, MessageBag):
                continue
            for message in value.pending():
                choice = (channel, message)
                if choice not in choices:
                    choices.append(choice)
        return tuple(choices)

    def apply(self, state: State, choice: object) -> State:
        channel, message = _message_choice(choice, self.kind)
        return send(state, channel, message)


class Crash(Fault):
    """Crash one declared node and record it in the model state.

    The marker is deliberately explicit (``faults.crashed.<node>``), so a
    protocol can use it in its own guards without any checker-specific logic.
    A node can only be crashed once by the same declaration.
    """

    kind = "crash"

    def __init__(self, nodes: Iterable[str], budget: int = 1) -> None:
        super().__init__(budget)
        self.nodes = _nodes(nodes)

    def candidates(self, state: State) -> tuple[str, ...]:
        return tuple(
            node
            for node in self.nodes
            if not state.get(_crashed_key(node), False)
        )

    def apply(self, state: State, choice: object) -> State:
        if not isinstance(choice, str) or choice not in self.nodes:
            raise FaultError(f"invalid crash choice: {choice!r}")
        return state.set(_crashed_key(choice), True)


class Partition(Fault):
    """Install a declared network partition and record its groups.

    The partition declaration is data for the model's protocol actions.  The
    wrapper records it as an immutable tuple; later rounds can use that marker
    to constrain delivery according to a protocol's addressing convention.
    """

    kind = "partition"

    def __init__(self, groups: Iterable[Iterable[str]], budget: int = 1) -> None:
        super().__init__(budget)
        self.groups = _groups(groups)

    def candidates(self, state: State) -> tuple[tuple[tuple[str, ...], ...], ...]:
        marker = _partition_key(self.groups)
        if state.get(marker, False):
            return ()
        return (self.groups,)

    def apply(self, state: State, choice: object) -> State:
        if choice != self.groups:
            raise FaultError(f"invalid partition choice: {choice!r}")
        return state.set(_partition_key(self.groups), True)


class _FaultModel(Model):
    """A normal Model which adds bounded fault actions to another model."""

    def __init__(self, model: Model, faults: tuple[Fault, ...]) -> None:
        if not isinstance(model, Model):
            raise TypeError("model must be a Model")
        self._model = model
        self._faults = faults
        self._base_actions = model.action_list()
        self._fault_names = _action_names(faults)

    def init(self) -> Iterable[State]:
        return tuple(self._with_metadata(state, (0,) * len(self._faults)) for state in self._model.initial_states())

    def actions(self) -> Iterable[Action]:
        for action in self._base_actions:
            yield Action(
                action.name,
                action.enabled,
                lambda state, base=action: self._base_successors(base, state),
            )
        for index, fault in enumerate(self._faults):
            yield Action(
                self._fault_names[index],
                lambda state, i=index, declared=fault: self._fault_enabled(
                    i, declared, state
                ),
                lambda state, i=index, declared=fault: self._fault_successors(
                    i, declared, state
                ),
            )

    def _base_successors(self, action: Action, state: State) -> tuple[State, ...]:
        usage = self._usage(state)
        return tuple(
            self._with_metadata(successor, usage, carry=state)
            for successor in action.successors(state)
        )

    def _fault_enabled(self, index: int, fault: Fault, state: State) -> bool:
        usage = self._usage(state)
        return usage[index] < fault.budget and bool(fault.candidates(state))

    def _fault_successors(
        self, index: int, fault: Fault, state: State
    ) -> tuple[State, ...]:
        usage = self._usage(state)
        if usage[index] >= fault.budget:
            return ()
        successors: list[State] = []
        for choice in fault.candidates(state):
            successor = self._with_metadata(
                fault.apply(state, choice),
                _increment(usage, index),
            )
            if successor not in successors:
                successors.append(successor)
        return tuple(successors)

    def _usage(self, state: State) -> tuple[int, ...]:
        values: list[int] = []
        for index in range(len(self._faults)):
            value = state.get(_usage_key(index), 0)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                value = 0
            values.append(value)
        return tuple(values)

    @staticmethod
    def _with_metadata(
        state: State,
        usage: Sequence[int],
        carry: State | None = None,
    ) -> State:
        data = state.to_dict()
        if carry is not None:
            for key, value in carry.items():
                if key.startswith("faults."):
                    data[key] = value
        data[_USED_KEY] = sum(usage)
        for index, value in enumerate(usage):
            data[_usage_key(index)] = value
        return State(data)


def with_faults(model: Model, faults: Iterable[Fault]) -> Model:
    """Return an ordinary model with the declared deterministic fault actions."""

    if not isinstance(model, Model):
        raise TypeError("model must be a Model")
    try:
        declared = tuple(faults)
    except TypeError as exc:
        raise TypeError("faults must be an iterable of Fault objects") from exc
    for fault in declared:
        if not isinstance(fault, Fault):
            raise TypeError("faults must contain Fault objects")

    # A zero budget is an explicitly disabled fault.  Do not wrap the model
    # for disabled declarations: otherwise the wrapper would still add
    # ``faults.used`` metadata and could change the explored state space even
    # though no fault transition is reachable.
    active = tuple(fault for fault in declared if fault.budget > 0)
    if not active:
        return model
    return _FaultModel(model, active)


def _message_choice(choice: object, kind: str) -> tuple[str, object]:
    if not isinstance(choice, tuple) or len(choice) != 2 or not isinstance(choice[0], str):
        raise FaultError(f"invalid {kind} choice: {choice!r}")
    return choice


def _increment(usage: Sequence[int], index: int) -> tuple[int, ...]:
    result = list(usage)
    result[index] += 1
    return tuple(result)


def _usage_key(index: int) -> str:
    return f"{_USAGE_PREFIX}{index}"


def _crashed_key(node: str) -> str:
    return f"faults.crashed.{node}"


def _partition_key(groups: tuple[tuple[str, ...], ...]) -> str:
    return "faults.partitioned." + ".".join(
        ",".join(group) for group in groups
    )


def _nodes(nodes: Iterable[str]) -> tuple[str, ...]:
    try:
        result = tuple(nodes)
    except TypeError as exc:
        raise TypeError("crash nodes must be an iterable of strings") from exc
    if not result or any(not isinstance(node, str) or not node for node in result):
        raise ValueError("crash nodes must contain non-empty strings")
    if len(set(result)) != len(result):
        raise ValueError("crash nodes must not contain duplicates")
    return result


def _groups(groups: Iterable[Iterable[str]]) -> tuple[tuple[str, ...], ...]:
    try:
        result = tuple(tuple(group) for group in groups)
    except TypeError as exc:
        raise TypeError("partition groups must be an iterable of node groups") from exc
    if len(result) < 2:
        raise ValueError("a partition needs at least two groups")
    all_nodes: list[str] = []
    for group in result:
        if not group or any(not isinstance(node, str) or not node for node in group):
            raise ValueError("partition groups must contain non-empty strings")
        if len(set(group)) != len(group):
            raise ValueError("partition groups must not contain duplicates")
        all_nodes.extend(group)
    if len(set(all_nodes)) != len(all_nodes):
        raise ValueError("a node may occur in only one partition group")
    return result


def _action_names(faults: Sequence[Fault]) -> tuple[str, ...]:
    counts: dict[str, int] = {}
    for fault in faults:
        counts[fault.kind] = counts.get(fault.kind, 0) + 1
    seen: dict[str, int] = {}
    names: list[str] = []
    for fault in faults:
        seen[fault.kind] = seen.get(fault.kind, 0) + 1
        name = f"fault.{fault.kind}"
        if counts[fault.kind] > 1:
            name += f"[{seen[fault.kind]}]"
        names.append(name)
    return tuple(names)


__all__ = [
    "Crash",
    "Fault",
    "FaultError",
    "MessageDuplication",
    "MessageLoss",
    "Partition",
    "with_faults",
]
