"""Deterministic state-space reductions.

The functions in this module return ordinary :class:`~crucible.model.Model`
wrappers.  They do not inspect the checker's internals, so traces produced
from a reduced model can still be replayed through that model's own actions.

Reduction is deliberately conservative where no reduction is justified:
symmetry only identifies states related by the explicitly supplied node
permutations, and partial-order reduction selects one action only when every
currently enabled action is pairwise commuting at the current state.
"""

from __future__ import annotations

from itertools import permutations, product
from typing import Any, Iterable, Sequence

from .model import Action, Model
from .state import State


class _ModelWrapper(Model):
    """Base class for wrappers that preserve the original action names."""

    def __init__(self, model: Model) -> None:
        if not isinstance(model, Model):
            raise TypeError("model must be a Model")
        self._model = model
        # Normalize once.  Apart from avoiding repeated generator consumption,
        # this makes wrapper construction independent of later model mutation.
        self._base_actions = model.action_list()

    def init(self) -> Iterable[State]:
        return self._model.initial_states()


class _ActionView(Action):
    """An action whose successors are transformed by a state reducer."""

    def __init__(self, base: Action, transform) -> None:
        self._base = base
        self._transform = transform
        super().__init__(base.name, base.enabled, self._successors)

    def _successors(self, state: State) -> tuple[State, ...]:
        return tuple(self._transform(successor) for successor in self._base.successors(state))


class _SymmetryModel(_ModelWrapper):
    def __init__(self, model: Model, groups: tuple[tuple[str, ...], ...]) -> None:
        super().__init__(model)
        self._canonical = _Canonicalizer(groups)
        self._views = tuple(_ActionView(action, self._canonical.state) for action in self._base_actions)

    def init(self) -> Iterable[State]:
        return tuple(self._canonical.state(state) for state in self._model.initial_states())

    def actions(self) -> Iterable[Action]:
        return self._views


class _Canonicalizer:
    """Compute a representative under a fixed product of permutation groups."""

    def __init__(self, groups: tuple[tuple[str, ...], ...]) -> None:
        self._groups = groups
        self._maps: tuple[tuple[tuple[str, str], ...], ...] = tuple(
            tuple(
                tuple(zip(group, permutation))
                for permutation in permutations(group)
            )
            for group in groups
        )

    def state(self, state: State) -> State:
        if not self._maps:
            return state

        best: State | None = None
        best_key: str | None = None
        choices = product(*(maps for maps in self._maps))
        for selected in choices:
            rename: dict[str, str] = {}
            for mapping in selected:
                for source, target in mapping:
                    rename[source] = target
            candidate_data = tuple(
                (
                    _rename_key(key, rename),
                    _rename_value(value, rename),
                )
                for key, value in state.items()
            )
            candidate = State(dict(candidate_data))
            key = repr(candidate)
            if best is None or key < (best_key or ""):
                best = candidate
                best_key = key
        return best if best is not None else state


class _PartialOrderModel(_ModelWrapper):
    def __init__(self, model: Model) -> None:
        super().__init__(model)
        self._views = tuple(
            _PartialOrderAction(action, self._base_actions, self._selected_names)
            for action in self._base_actions
        )

    def actions(self) -> Iterable[Action]:
        return self._views

    def _selected_names(self, state: State) -> tuple[str, ...]:
        enabled: list[tuple[Action, tuple[State, ...]]] = []
        for action in self._base_actions:
            if not action.enabled(state):
                continue
            successors = action.successors(state)
            if successors:
                enabled.append((action, successors))

        if len(enabled) <= 1:
            return tuple(action.name for action, _ in enabled)

        # A single action is a safe persistent choice for this local product
        # only when all enabled actions commute with it.  If any pair is not
        # demonstrably independent, retain the full enabled set.
        for index, (left, left_successors) in enumerate(enabled):
            for right, right_successors in enabled[index + 1 :]:
                if not _commute(left, left_successors, right, right_successors):
                    return tuple(action.name for action, _ in enabled)
        return (enabled[0][0].name,)


class _PartialOrderAction(Action):
    def __init__(self, base: Action, all_actions: tuple[Action, ...], selected) -> None:
        self._base = base
        self._all_actions = all_actions
        self._selected = selected
        super().__init__(base.name, self._enabled, self._successors)

    def _enabled(self, state: State) -> bool:
        return self.name in self._selected(state)

    def _successors(self, state: State) -> tuple[State, ...]:
        if self.name not in self._selected(state):
            return ()
        return self._base.successors(state)


def _commute(
    left: Action,
    left_successors: tuple[State, ...],
    right: Action,
    right_successors: tuple[State, ...],
) -> bool:
    """Check local diamond commutation for possibly nondeterministic actions."""

    for left_state in left_successors:
        if not right.enabled(left_state):
            return False
        after_left = right.successors(left_state)
        if not after_left:
            return False
        for right_state in right_successors:
            if not left.enabled(right_state):
                return False
            after_right = left.successors(right_state)
            if not after_right:
                return False
            if not _same_states(after_left, after_right):
                return False
    return True


def _same_states(left: Sequence[State], right: Sequence[State]) -> bool:
    """Compare successor collections without depending on iteration order."""

    left_unique = _unique_states(left)
    right_unique = _unique_states(right)
    if len(left_unique) != len(right_unique):
        return False
    return all(any(candidate == other for other in right_unique) for candidate in left_unique)


def _unique_states(states: Sequence[State]) -> tuple[State, ...]:
    unique: list[State] = []
    for state in states:
        if state not in unique:
            unique.append(state)
    return tuple(unique)


def _rename_key(key: str, rename: dict[str, str]) -> str:
    """Rename node tokens in structured variable names such as ``pc.n1``."""
    # Longest first prevents a node called ``n1`` from matching the prefix of
    # a node called ``n10``.  Replacements are scanned against the original
    # key, so a permutation such as n1 <-> n2 is applied simultaneously rather
    # than cycling through the mapping one name at a time.
    names = sorted(rename, key=lambda name: (-len(name), name))
    pieces: list[str] = []
    index = 0
    while index < len(key):
        matched = False
        for name in names:
            if not key.startswith(name, index):
                continue
            before = key[index - 1] if index else ""
            end = index + len(name)
            after = key[end] if end < len(key) else ""
            if not (_is_token_boundary(before) and _is_token_boundary(after)):
                continue
            pieces.append(rename[name])
            index = end
            matched = True
            break
        if not matched:
            pieces.append(key[index])
            index += 1
    return "".join(pieces)


def _is_token_boundary(character: str) -> bool:
    return not character or not (character.isalnum() or character == "_")


def _rename_value(value: Any, rename: dict[str, str]) -> Any:
    if isinstance(value, str):
        return rename.get(value, value)
    if isinstance(value, tuple):
        return tuple(_rename_value(item, rename) for item in value)
    if isinstance(value, frozenset):
        return frozenset(_rename_value(item, rename) for item in value)
    return value


def _normalize_groups(groups: Iterable[Iterable[str]]) -> tuple[tuple[str, ...], ...]:
    try:
        raw_groups = tuple(tuple(group) for group in groups)
    except TypeError as exc:
        raise TypeError("groups must be an iterable of node groups") from exc

    seen: set[str] = set()
    normalized: list[tuple[str, ...]] = []
    for group in raw_groups:
        if len(group) < 2:
            raise ValueError("each symmetry group must contain at least two nodes")
        for node in group:
            if not isinstance(node, str) or not node:
                raise TypeError("symmetry nodes must be non-empty strings")
            if node in seen:
                raise ValueError(f"symmetry node appears in more than one group: {node!r}")
            seen.add(node)
        if len(set(group)) != len(group):
            raise ValueError("symmetry groups must not contain duplicate nodes")
        normalized.append(group)
    return tuple(normalized)


def symmetry(model: Model, groups: Iterable[Iterable[str]]) -> Model:
    """Return a model quotienting states under the supplied node groups.

    A group is interpreted as a set of interchangeable node identifiers.  A
    model passed here must be equivariant under those renamings; invariants
    should likewise be invariant under the same symmetry.
    """

    return _SymmetryModel(model, _normalize_groups(groups))


def partial_order(model: Model) -> Model:
    """Return a deterministic local partial-order reduction of ``model``."""

    return _PartialOrderModel(model)


__all__ = ["partial_order", "symmetry"]
