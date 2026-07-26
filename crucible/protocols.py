"""Small deterministic protocol models used as executable examples.

Each builder returns a finite :class:`~crucible.model.Model` together with the
invariants that judge it.  The ``*_broken`` builders deliberately change only
the transition that contains the bug; they keep the same invariant as their
correct twin so that the comparison is meaningful.
"""

from __future__ import annotations

from typing import Iterable

from .model import Action, Invariant, Model
from .state import State


_CORRECT = (
    "peterson",
    "dekker",
    "two_phase_commit",
    "raft_election",
    "bank_transfer",
)


def catalog() -> tuple[str, ...]:
    """Return every protocol builder name in a stable order."""

    return _CORRECT + tuple(name + "_broken" for name in _CORRECT)


class _Peterson(Model):
    def __init__(self, broken: bool = False) -> None:
        self.broken = broken

    def init(self) -> Iterable[State]:
        yield State(
            {
                "want0": False,
                "want1": False,
                "turn": 0,
                "cs0": False,
                "cs1": False,
            }
        )

    def actions(self) -> Iterable[Action]:
        yield Action("p0.enter", self._p0_enter_enabled, self._p0_enter)
        yield Action("p0.exit", lambda s: s["cs0"], self._p0_exit)
        yield Action("p0.request", self._p0_request_enabled, self._p0_request)
        yield Action("p1.enter", self._p1_enter_enabled, self._p1_enter)
        yield Action("p1.exit", lambda s: s["cs1"], self._p1_exit)
        yield Action("p1.request", self._p1_request_enabled, self._p1_request)

    @staticmethod
    def _p0_request_enabled(state: State) -> bool:
        return not state["want0"] and not state["cs0"]

    @staticmethod
    def _p1_request_enabled(state: State) -> bool:
        return not state["want1"] and not state["cs1"]

    @staticmethod
    def _p0_request(state: State) -> Iterable[State]:
        yield state.update(want0=True, turn=1)

    @staticmethod
    def _p1_request(state: State) -> Iterable[State]:
        yield state.update(want1=True, turn=0)

    def _p0_enter_enabled(self, state: State) -> bool:
        return state["want0"] and not state["cs0"] and (
            self.broken or not state["want1"] or state["turn"] == 0
        )

    def _p1_enter_enabled(self, state: State) -> bool:
        return state["want1"] and not state["cs1"] and (
            self.broken or not state["want0"] or state["turn"] == 1
        )

    @staticmethod
    def _p0_enter(state: State) -> Iterable[State]:
        yield state.set("cs0", True)

    @staticmethod
    def _p1_enter(state: State) -> Iterable[State]:
        yield state.set("cs1", True)

    @staticmethod
    def _p0_exit(state: State) -> Iterable[State]:
        yield state.update(cs0=False, want0=False, turn=1)

    @staticmethod
    def _p1_exit(state: State) -> Iterable[State]:
        yield state.update(cs1=False, want1=False, turn=0)


class _Dekker(_Peterson):
    """The same finite critical-section skeleton with Dekker guards."""

    def _p0_enter_enabled(self, state: State) -> bool:
        return state["want0"] and not state["cs0"] and (
            self.broken or not state["want1"] or state["turn"] == 0
        )

    def _p1_enter_enabled(self, state: State) -> bool:
        return state["want1"] and not state["cs1"] and (
            self.broken or not state["want0"] or state["turn"] == 1
        )


class _TwoPhaseCommit(Model):
    def __init__(self, broken: bool = False) -> None:
        self.broken = broken

    def init(self) -> Iterable[State]:
        yield State({"coord": "init", "p0": "working", "p1": "working"})

    def actions(self) -> Iterable[Action]:
        yield Action(
            "commit",
            self._commit_enabled,
            self._commit_successors,
        )
        yield Action("p0.vote_yes", lambda s: self._vote_enabled(s, "p0"), self._p0_vote)
        yield Action("p1.vote_yes", lambda s: self._vote_enabled(s, "p1"), self._p1_vote)
        yield Action(
            "prepare",
            lambda s: s["coord"] == "init",
            lambda s: [s.set("coord", "prepared")],
        )

    @staticmethod
    def _vote_enabled(state: State, participant: str) -> bool:
        return state["coord"] == "prepared" and state[participant] == "working"

    @staticmethod
    def _p0_vote(state: State) -> Iterable[State]:
        yield state.set("p0", "yes")

    @staticmethod
    def _p1_vote(state: State) -> Iterable[State]:
        yield state.set("p1", "yes")

    def _commit_enabled(self, state: State) -> bool:
        if state["coord"] != "prepared":
            return False
        if self.broken:
            return state["p0"] == "yes" or state["p1"] == "yes"
        return state["p0"] == "yes" and state["p1"] == "yes"

    def _commit_successors(self, state: State) -> Iterable[State]:
        if self.broken:
            yield state.update(coord="committed", p0="committed")
        else:
            yield state.update(coord="committed", p0="committed", p1="committed")


class _RaftElection(Model):
    def __init__(self, broken: bool = False) -> None:
        self.broken = broken

    def init(self) -> Iterable[State]:
        yield State({"votes0": 0, "votes1": 0, "leader0": False, "leader1": False})

    def actions(self) -> Iterable[Action]:
        yield Action("elect0", self._elect0_enabled, lambda s: [s.set("leader0", True)])
        yield Action("elect1", self._elect1_enabled, lambda s: [s.set("leader1", True)])
        yield Action("vote0.node1", lambda s: s["votes0"] < 2, self._vote0)
        yield Action("vote0.node2", lambda s: s["votes0"] < 2, self._vote0)
        yield Action("vote1.node1", lambda s: s["votes1"] < 2, self._vote1)
        yield Action("vote1.node2", lambda s: s["votes1"] < 2, self._vote1)

    def _elect0_enabled(self, state: State) -> bool:
        return state["votes0"] >= 2 and not state["leader0"] and (
            self.broken or not state["leader1"]
        )

    def _elect1_enabled(self, state: State) -> bool:
        return state["votes1"] >= 2 and not state["leader1"] and (
            self.broken or not state["leader0"]
        )

    @staticmethod
    def _vote0(state: State) -> Iterable[State]:
        yield state.set("votes0", state["votes0"] + 1)

    @staticmethod
    def _vote1(state: State) -> Iterable[State]:
        yield state.set("votes1", state["votes1"] + 1)


class _BankTransfer(Model):
    def __init__(self, broken: bool = False) -> None:
        self.broken = broken

    def init(self) -> Iterable[State]:
        yield State({"a": 5, "b": 5, "done": False})

    def actions(self) -> Iterable[Action]:
        yield Action("transfer.a_to_b", lambda s: not s["done"] and s["a"] > 0, self._transfer)

    def _transfer(self, state: State) -> Iterable[State]:
        if self.broken:
            yield state.update(a=state["a"] - 1, done=True)
        else:
            yield state.update(a=state["a"] - 1, b=state["b"] + 1, done=True)


def _mutex_invariants() -> tuple[Invariant, ...]:
    return (Invariant("mutual_exclusion", lambda s: not (s["cs0"] and s["cs1"])),)


def _commit_invariants() -> tuple[Invariant, ...]:
    return (
        Invariant(
            "atomic_commit",
            lambda s: not (
                (s["p0"] == "committed" and s["p1"] != "committed")
                or (s["p1"] == "committed" and s["p0"] != "committed")
            ),
        ),
    )


def _election_invariants() -> tuple[Invariant, ...]:
    return (Invariant("single_leader", lambda s: not (s["leader0"] and s["leader1"])),)


def _bank_invariants() -> tuple[Invariant, ...]:
    return (
        Invariant(
            "conservation",
            lambda s: s["a"] >= 0 and s["b"] >= 0 and s["a"] + s["b"] == 10,
        ),
    )


def peterson() -> tuple[Model, Iterable[Invariant]]:
    return _Peterson(), _mutex_invariants()


def peterson_broken() -> tuple[Model, Iterable[Invariant]]:
    return _Peterson(broken=True), _mutex_invariants()


def dekker() -> tuple[Model, Iterable[Invariant]]:
    return _Dekker(), _mutex_invariants()


def dekker_broken() -> tuple[Model, Iterable[Invariant]]:
    return _Dekker(broken=True), _mutex_invariants()


def two_phase_commit() -> tuple[Model, Iterable[Invariant]]:
    return _TwoPhaseCommit(), _commit_invariants()


def two_phase_commit_broken() -> tuple[Model, Iterable[Invariant]]:
    return _TwoPhaseCommit(broken=True), _commit_invariants()


def raft_election() -> tuple[Model, Iterable[Invariant]]:
    return _RaftElection(), _election_invariants()


def raft_election_broken() -> tuple[Model, Iterable[Invariant]]:
    return _RaftElection(broken=True), _election_invariants()


def bank_transfer() -> tuple[Model, Iterable[Invariant]]:
    return _BankTransfer(), _bank_invariants()


def bank_transfer_broken() -> tuple[Model, Iterable[Invariant]]:
    return _BankTransfer(broken=True), _bank_invariants()


__all__ = [
    "bank_transfer",
    "bank_transfer_broken",
    "catalog",
    "dekker",
    "dekker_broken",
    "peterson",
    "peterson_broken",
    "raft_election",
    "raft_election_broken",
    "two_phase_commit",
    "two_phase_commit_broken",
]
