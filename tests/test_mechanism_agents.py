"""未知生成機制假說的機率、可重現性與公平契約。"""
from pathlib import Path
import random

import pytest

from engine.games import LOTTO649, PICK_N, POOL, SPECIAL_POOL, SUPER, validate_pick
from engine.mechanism_agents import (
    HYPOTHESES,
    HYPOTHESIS_IDS,
    build_hypothesis_context,
    propose,
    public_hypothesis_snapshots,
)
from engine.store import DrawStore


DATA = Path(__file__).parent.parent / "data"


@pytest.fixture(scope="module")
def store():
    return DrawStore(DATA)


@pytest.mark.parametrize("game", [SUPER, LOTTO649])
def test_probability_snapshots_are_normalized_and_cover_h0_to_h4(store, game):
    context = build_hypothesis_context(game, store.draws(game)[:120])
    snapshots = public_hypothesis_snapshots(context)

    assert [snapshot["code"] for snapshot in snapshots] == [
        "H0",
        "H1",
        "H2",
        "H3",
        "H4",
    ]
    assert {snapshot["id"] for snapshot in snapshots} == set(
        HYPOTHESIS_IDS
    )
    for snapshot in snapshots:
        assert len(snapshot["main_probabilities"]) == POOL[game]
        assert sum(snapshot["main_probabilities"]) == pytest.approx(
            PICK_N,
            abs=1e-7,
        )
        assert all(
            0 <= probability <= 1
            for probability in snapshot["main_probabilities"]
        )
        if game == SUPER:
            assert len(snapshot["special_probabilities"]) == SPECIAL_POOL[SUPER]
            assert sum(snapshot["special_probabilities"]) == pytest.approx(
                1,
                abs=1e-7,
            )
        else:
            assert snapshot["special_probabilities"] is None


def test_h0_is_uniform_but_not_privileged_by_the_model_contract(store):
    context = build_hypothesis_context(SUPER, store.draws(SUPER)[:120])
    h0 = context["models"]["independent_null"]

    assert set(HYPOTHESES) == set(HYPOTHESIS_IDS)
    assert len(HYPOTHESIS_IDS) == 5
    assert len(set(h0["main_probabilities"].values())) == 1
    assert all(
        hypothesis in context["models"]
        for hypothesis in HYPOTHESIS_IDS
    )


@pytest.mark.parametrize("game", [SUPER, LOTTO649])
@pytest.mark.parametrize("hypothesis", HYPOTHESIS_IDS)
def test_hypothesis_proposals_are_deterministic_and_legal(
    store,
    game,
    hypothesis,
):
    context = build_hypothesis_context(game, store.draws(game)[:120])
    first = propose(hypothesis, game, random.Random(42), context)
    second = propose(hypothesis, game, random.Random(42), context)

    assert first == second
    validate_pick(game, first["numbers"], first["special"])
    assert first["meta"]["hypothesis_code"].startswith("H")
    assert len(first["meta"]["distribution_hash"]) == 64


def test_alternative_hypotheses_can_depart_from_uniform_after_history(store):
    context = build_hypothesis_context(
        LOTTO649,
        store.draws(LOTTO649)[:180],
    )
    uniform = context["models"]["independent_null"]["main_probabilities"]

    assert all(
        context["models"][hypothesis]["main_probabilities"] != uniform
        for hypothesis in HYPOTHESIS_IDS
        if hypothesis != "independent_null"
    )
