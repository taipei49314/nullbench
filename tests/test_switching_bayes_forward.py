"""Append-only preregistration and reveal-only settlement tests."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from itertools import islice
import json
from pathlib import Path

import pytest

from engine.games import LOTTO649, SUPER
from engine.ledger import Ledger
from research.switching_bayes import (
    run_switching_bayes_study,
    write_results,
)
from research.switching_bayes_forward import (
    reconcile_registry,
    verify_registry,
)


BASE = Path(__file__).parent.parent
SOURCES = {
    SUPER: BASE / "simulation" / "results" / "super.jsonl",
    LOTTO649: BASE / "simulation" / "results" / "lotto649.jsonl",
}


def _events(game: str, count: int) -> list[dict]:
    with SOURCES[game].open(encoding="utf-8") as handle:
        return [json.loads(line) for line in islice(handle, count)]


@dataclass(frozen=True)
class Draw:
    game: str
    period: int
    date: str
    numbers: tuple[int, ...]
    special: int | None


class Store:
    def __init__(self, events_by_game):
        self.events_by_game = events_by_game

    def draws(self, game):
        return [
            Draw(
                game=game,
                period=int(event["reveal"]["period"]),
                date=event["reveal"]["date"],
                numbers=tuple(event["reveal"]["numbers"]),
                special=event["reveal"]["special"],
            )
            for event in self.events_by_game.get(game, [])
        ]


@pytest.fixture
def registry_setup(tmp_path):
    ledgers = {}
    events = {}
    for game, source in SOURCES.items():
        events[game] = _events(game, 83)
        target = tmp_path / f"{game}.jsonl"
        with source.open(encoding="utf-8") as handle:
            target.write_text(
                "".join(islice(handle, 82)),
                encoding="utf-8",
            )
        ledgers[game] = target
    study = run_switching_bayes_study(
        ledgers,
        base=BASE,
        verify_ledgers=False,
    )
    write_results(study, tmp_path / "research" / "results")
    manifest = {
        "games": {
            game: {
                "next_decision": events[game][82]["decision"],
            }
            for game in (SUPER, LOTTO649)
        }
    }
    return tmp_path, events, manifest


def test_registry_preregisters_once_then_settles_only_after_reveal(
    registry_setup,
):
    root, events, manifest = registry_setup
    empty_store = Store({SUPER: [], LOTTO649: []})
    first = reconcile_registry(
        root,
        empty_store,
        manifest,
        registered_at="2000-01-01T00:00:00+08:00",
    )
    repeated = reconcile_registry(
        root,
        empty_store,
        manifest,
        registered_at="2000-01-01T00:00:01+08:00",
    )

    assert first["status"]["verification"] == {
        "chain_valid": True,
        "events": 2,
        "registrations": 2,
        "settlements": 0,
        "pending": 2,
    }
    assert all(
        row["status"] == "created"
        for row in first["registrations"].values()
    )
    assert all(
        row["status"] == "existing"
        for row in repeated["registrations"].values()
    )

    revealed_store = Store(
        {
            game: [events[game][82]]
            for game in (SUPER, LOTTO649)
        }
    )
    settled = reconcile_registry(
        root,
        revealed_store,
        manifest,
        registered_at="2000-01-01T00:00:02+08:00",
    )
    assert settled["settlements_created"] == 2
    assert settled["status"]["verification"]["settlements"] == 2
    assert settled["status"]["verification"]["pending"] == 0
    assert len(settled["status"]["recent_scores"]) == 2


def test_registry_detects_tamper(registry_setup):
    root, _, manifest = registry_setup
    reconcile_registry(
        root,
        Store({SUPER: [], LOTTO649: []}),
        manifest,
        registered_at="2000-01-01T00:00:00+08:00",
    )
    path = (
        root
        / "simulation"
        / "forward"
        / "switching_bayes.jsonl"
    )
    lines = path.read_text(encoding="utf-8").splitlines()
    event = json.loads(lines[0])
    event["content"]["target"]["period"] += 1
    lines[0] = json.dumps(event, ensure_ascii=False)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="hash chain|content hash"):
        verify_registry(Ledger(path))


def test_same_target_cannot_be_backfilled_with_a_new_candidate(
    registry_setup,
):
    root, _, manifest = registry_setup
    first = reconcile_registry(
        root,
        Store({SUPER: [], LOTTO649: []}),
        manifest,
        registered_at="2000-01-01T00:00:00+08:00",
    )
    changed = deepcopy(manifest)
    changed["games"][SUPER]["next_decision"]["decision_hash"] = "f" * 64
    repeated = reconcile_registry(
        root,
        Store({SUPER: [], LOTTO649: []}),
        changed,
        registered_at="2000-01-01T00:00:01+08:00",
    )

    assert (
        repeated["registrations"][SUPER]["registration_hash"]
        == first["registrations"][SUPER]["registration_hash"]
    )
