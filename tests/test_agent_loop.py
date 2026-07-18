"""逐期 agent 辯論閉環：決策、揭曉後檢討與完整回放測試。"""
from dataclasses import replace
from pathlib import Path

import pytest

from engine.agent_loop import (
    AGENT_IDS,
    PROPOSALS_PER_AGENT,
    SELECTED_TICKETS,
    conduct_debate,
    initial_state,
    next_target,
    replay_game,
    review_after_reveal,
    target_from_draw,
    verify_replay,
)
from engine.games import LOTTO649, SUPER, Draw, validate_pick
from engine.store import DrawStore


DATA = Path(__file__).parent.parent / "data"


@pytest.fixture(scope="module")
def store():
    return DrawStore(DATA)


@pytest.mark.parametrize("game,index", [(SUPER, 80), (LOTTO649, 80)])
def test_agents_propose_cross_debate_and_select_five_valid_tickets(store, game, index):
    draws = store.draws(game)
    target = draws[index]
    decision = conduct_debate(
        game, target_from_draw(target), draws[:index], initial_state()
    )

    assert len(decision["proposals"]) == len(AGENT_IDS) * PROPOSALS_PER_AGENT
    assert {proposal["agent"] for proposal in decision["proposals"]} == set(AGENT_IDS)
    assert all(
        sum(proposal["agent"] == agent for proposal in decision["proposals"])
        == PROPOSALS_PER_AGENT
        for agent in AGENT_IDS
    )
    assert len(decision["critiques"]) == (
        len(AGENT_IDS) * (len(AGENT_IDS) - 1) * PROPOSALS_PER_AGENT
    )
    proposal_agents = {
        proposal["proposal_id"]: proposal["agent"]
        for proposal in decision["proposals"]
    }
    assert all(
        critique["critic"] != proposal_agents[critique["target"]]
        for critique in decision["critiques"]
    )

    tickets = decision["selected_tickets"]
    assert len(tickets) == SELECTED_TICKETS
    assert len({tuple(ticket["numbers"]) for ticket in tickets}) == SELECTED_TICKETS
    for ticket in tickets:
        validate_pick(game, ticket["numbers"], ticket["special"])


def test_decision_is_deterministic_and_blind_to_target_outcome(store):
    draws = store.draws(SUPER)
    target = draws[100]
    history = draws[:100]
    state = initial_state()
    original = conduct_debate(SUPER, target_from_draw(target), history, state)
    replayed = conduct_debate(SUPER, target_from_draw(target), history, state)
    changed_outcome = replace(
        target,
        numbers=tuple(reversed(target.numbers)),
        special=1 if target.special != 1 else 2,
    )
    changed = conduct_debate(
        SUPER, target_from_draw(changed_outcome), history, state
    )

    assert original == replayed == changed
    with pytest.raises(ValueError, match="未來資料洩漏"):
        conduct_debate(SUPER, target_from_draw(target), draws[:101], state)


def test_feedback_updates_only_after_reveal_and_flows_to_next_draw(store):
    draws = store.draws(LOTTO649)
    state = initial_state()
    before = initial_state()
    decision = conduct_debate(
        LOTTO649, target_from_draw(draws[60]), draws[:60], state
    )

    assert state == before
    assert decision["state_before"]["draws_reviewed"] == 0

    review, after = review_after_reveal(decision, draws[60], state)
    assert state == before
    assert after["draws_reviewed"] == 1
    assert all(after["agents"][agent]["reviews"] == 1 for agent in AGENT_IDS)
    assert review["state_before"] == decision["state_before"]
    assert review["state_after"]["draws_reviewed"] == 1

    next_decision = conduct_debate(
        LOTTO649, target_from_draw(draws[61]), draws[:61], after
    )
    assert next_decision["state_before"] == review["state_after"]
    assert decision["decision_hash"] == conduct_debate(
        LOTTO649, target_from_draw(draws[60]), draws[:60], state
    )["decision_hash"]


def test_replay_covers_every_draw_without_gaps_and_hash_chain_verifies(
    tmp_path, store
):
    draws = store.draws(SUPER)[:12]
    output = tmp_path / "super.jsonl"
    summary = replay_game(SUPER, draws, output, collect_events=True)
    verified = verify_replay(output, expected_draws=len(draws))

    assert summary["draws_replayed"] == len(draws)
    assert len(summary["events"]) == len(draws)
    assert [event["sequence"] for event in summary["events"]] == list(
        range(1, len(draws) + 1)
    )
    assert [
        event["decision"]["history_count"] for event in summary["events"]
    ] == list(range(len(draws)))
    assert [
        event["decision"]["target"]["period"] for event in summary["events"]
    ] == [draw.period for draw in draws]
    assert verified["last_event_hash"] == summary["last_event_hash"]
    assert verified["ledger_sha256"] == summary["ledger_sha256"]
    assert summary["next_decision"]["history_count"] == len(draws)


def test_replay_artifact_is_bit_identical(store, tmp_path):
    draws = store.draws(LOTTO649)[:10]
    left = tmp_path / "left.jsonl"
    right = tmp_path / "right.jsonl"
    first = replay_game(LOTTO649, draws, left)
    second = replay_game(LOTTO649, list(reversed(draws)), right)

    assert left.read_bytes() == right.read_bytes()
    assert first["last_event_hash"] == second["last_event_hash"]
    assert first["next_decision"] == second["next_decision"]


def test_next_target_rolls_period_number_at_roc_year_boundary():
    latest = Draw(
        game=LOTTO649,
        period=115000120,
        date="2026-12-29",
        numbers=(1, 2, 3, 4, 5, 6),
        special=7,
    )
    assert next_target(LOTTO649, latest) == {
        "date": "2027-01-01",
        "period": 116000001,
    }
