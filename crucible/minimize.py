"""Deterministic counterexample trace minimization.

The minimizer works on action names rather than copying states from the input
trace.  Every candidate is replayed through the model, so a returned trace is
an actual model execution and not a stitched-together display artifact.
"""

from __future__ import annotations

from typing import Iterable

from .checker import Trace
from .model import Invariant, Model
from .state import State


def shrink(
    model: Model, invariants: Iterable[Invariant], trace: Trace
) -> Trace:
    """Return a shorter deterministic trace with the same safety violation.

    The implementation uses delta debugging: it tries contiguous removals in
    source order, growing the partition count when no removal works.  A
    candidate is accepted only when the named actions can be replayed from the
    original initial state and some supplied invariant fails at its final
    state.  Action successor order is preserved while replaying, which makes
    the selected counterexample deterministic even for nondeterministic
    actions.
    """

    if not isinstance(trace, Trace):
        raise TypeError("trace must be a Trace")

    invariant_list = tuple(invariants)
    actions = {action.name: action for action in model.action_list()}
    names = tuple(name for name, _ in trace.steps)

    # Validate the input before attempting to minimize it.  In particular,
    # this prevents returning a plausible-looking trace for a malformed input.
    if trace.initial not in model.initial_states():
        raise ValueError("trace does not start from a declared initial state")
    if _replay_with_targets(trace.initial, trace.steps, actions) is None:
        raise ValueError("trace contains an invalid action or successor")
    if not _violates(trace.final, invariant_list):
        raise ValueError("trace final state does not violate an invariant")

    current = names
    if not current:
        return Trace(trace.initial, ())

    # Classic ddmin.  The partition and candidate order are fixed, so the
    # result does not depend on hash randomization or container iteration.
    partitions = 2
    while len(current) >= 2:
        chunk_size = (len(current) + partitions - 1) // partitions
        reduced = False
        for start in range(0, len(current), chunk_size):
            candidate = current[:start] + current[start + chunk_size :]
            replayed = _find_violating_trace(
                trace.initial, candidate, actions, invariant_list
            )
            if replayed is None:
                continue
            current = candidate
            reduced = True
            partitions = max(partitions - 1, 2)
            break

        if reduced:
            continue
        if partitions >= len(current):
            break
        partitions = min(len(current), partitions * 2)

    result = _find_violating_trace(
        trace.initial, current, actions, invariant_list
    )
    # `current` starts from a validated violating trace and is only replaced
    # by validated candidates, so this is a defensive invariant check.
    if result is None:  # pragma: no cover - protects the public contract
        raise RuntimeError("minimization lost the counterexample")
    return result


def _replay_with_targets(
    initial: State,
    steps: tuple[tuple[str, State], ...],
    actions: dict[str, object],
) -> Trace | None:
    """Validate the exact state sequence carried by an input trace."""

    current = initial
    for name, expected in steps:
        action = actions.get(name)
        if action is None:
            return None
        if not action.enabled(current):
            return None
        if expected not in action.successors(current):
            return None
        current = expected
    return Trace(initial, steps)


def _find_violating_trace(
    initial: State,
    names: tuple[str, ...],
    actions: dict[str, object],
    invariants: tuple[Invariant, ...],
) -> Trace | None:
    """Replay an action sequence and return its first violating path.

    Successor branches are explored in declaration order.  The visited set is
    used only for membership checks; it is never iterated, so it cannot affect
    deterministic output.
    """

    stack: list[tuple[int, State, tuple[tuple[str, State], ...]]] = [
        (0, initial, ())
    ]
    visited: set[tuple[int, State]] = set()

    while stack:
        index, current, steps = stack.pop()
        marker = (index, current)
        if marker in visited:
            continue
        visited.add(marker)

        if index == len(names):
            if _violates(current, invariants):
                return Trace(initial, steps)
            continue

        name = names[index]
        action = actions.get(name)
        if action is None or not action.enabled(current):
            continue
        successors = action.successors(current)
        # Reverse only for stack scheduling; the model's original order is
        # therefore the order in which paths are selected.
        for successor in reversed(successors):
            stack.append((index + 1, successor, steps + ((name, successor),)))

    return None


def _violates(state: State, invariants: tuple[Invariant, ...]) -> bool:
    """Apply the same fail-closed invariant semantics as the checker."""

    return any(not invariant.evaluate(state)[0] for invariant in invariants)


__all__ = ["shrink"]
