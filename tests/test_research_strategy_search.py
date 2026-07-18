"""階段 2：無前視、策略搜尋與決定性閘門的完整測試。"""
from dataclasses import replace
from pathlib import Path

import pytest

from engine.games import LOTTO649, SUPER
from engine.store import DrawStore, monday_of
from research.backtest import (
    CURRENT,
    UNIFORM,
    Policy,
    _rank_family,
    build_contexts,
    build_final_policies,
    coarse_candidates,
    evaluate_policies,
    generate_policy_tickets,
    homogeneous_policies,
    refine_candidates,
    strategy_determinism_probe,
)
from research.gates import (
    StageGateError,
    build_strategy_search_gate,
    require_gate,
)


DATA = Path(__file__).parent.parent / "data"
FAMILIES = ("hot", "cold", "balance", "antipop")


@pytest.fixture(scope="module")
def contexts_by_game():
    store = DrawStore(DATA)
    return {
        game: build_contexts(game, store.draws(game))
        for game in (SUPER, LOTTO649)
    }


def _winner_map():
    return {
        "hot": CURRENT["hot"],
        "cold": CURRENT["cold"],
        "balance": CURRENT["balance"],
        "antipop": CURRENT["antipop"],
    }


def _policies_by_game():
    winners = _winner_map()
    ranked = [CURRENT["hot"], CURRENT["cold"], CURRENT["antipop"]]
    return {
        game: build_final_policies(winners, ranked)
        for game in (SUPER, LOTTO649)
    }


def test_all_contexts_have_exact_split_boundaries_and_no_lookahead(
    contexts_by_game,
):
    for contexts in contexts_by_game.values():
        n = len(contexts)
        splits = [context.split for context in contexts]
        assert splits[: n // 2] == ["train"] * (n // 2)
        assert splits[n // 2 : n // 2 + n // 4] == ["validation"] * (
            n // 4
        )
        assert splits[n // 2 + n // 4 :] == ["holdout"] * (
            n - n // 2 - n // 4
        )
        for context in contexts:
            cutoff = monday_of(context.week).isoformat()
            assert all(draw.date < cutoff for draw in context.history)


def test_context_build_is_invariant_to_input_order():
    draws = DrawStore(DATA).draws(SUPER)[:80]
    normal = build_contexts(SUPER, draws)
    shuffled = build_contexts(SUPER, list(reversed(draws)))
    assert normal == shuffled


def test_future_outcome_change_cannot_change_prior_context_or_tickets():
    draws = DrawStore(DATA).draws(SUPER)[:120]
    original = build_contexts(SUPER, draws)
    future = draws[-1]
    mutated = list(draws)
    mutated[-1] = replace(
        future,
        numbers=tuple(reversed(future.numbers)),
        special=1 if future.special != 1 else 2,
    )
    changed = build_contexts(SUPER, mutated)
    policy = Policy("random_5", (UNIFORM,) * 5)
    for left, right in zip(original[:-1], changed[:-1]):
        assert left == right
        assert generate_policy_tickets(policy, left, 0) == generate_policy_tickets(
            policy, right, 0
        )


def test_shared_uniform_slots_use_common_random_numbers(contexts_by_game):
    context = contexts_by_game[SUPER][100]
    left = Policy("left", (UNIFORM, CURRENT["hot"], UNIFORM, UNIFORM, UNIFORM))
    right = Policy(
        "right", (UNIFORM, CURRENT["cold"], UNIFORM, UNIFORM, UNIFORM)
    )
    left_tickets = generate_policy_tickets(left, context, replicate=3)
    right_tickets = generate_policy_tickets(right, context, replicate=3)
    assert left_tickets[0] == right_tickets[0]
    assert left_tickets[2:] == right_tickets[2:]


def test_policy_evaluation_is_order_invariant(contexts_by_game):
    contexts = contexts_by_game[SUPER][100:103]
    policies = [
        Policy("random_5", (UNIFORM,) * 5),
        Policy("hot_5", (CURRENT["hot"],) * 5),
    ]
    forward = evaluate_policies(contexts, policies, replicates=2)
    reverse = evaluate_policies(contexts, list(reversed(policies)), replicates=2)
    key = lambda row: (row.week, row.policy_id, row.replicate)
    assert {key(row): row for row in forward} == {key(row): row for row in reverse}


def test_refinement_is_unique_and_centered_on_training_winners():
    winners = _winner_map()
    refined = refine_candidates(winners)
    assert len({candidate.candidate_id for candidate in refined}) == len(refined)
    assert {candidate.family for candidate in refined} == {
        "uniform",
        *FAMILIES,
    }
    assert any(
        candidate.family == "hot"
        and candidate.get("window") == winners["hot"].get("window")
        for candidate in refined
    )
    assert any(
        candidate.family == "cold"
        and candidate.get("gamma") == winners["cold"].get("gamma")
        for candidate in refined
    )


def test_family_ranking_uses_train_even_when_holdout_disagrees():
    hot = [candidate for candidate in coarse_candidates() if candidate.family == "hot"][:2]
    summaries = []
    for candidate, train_delta, holdout_delta in (
        (hot[0], 0.2, -1.0),
        (hot[1], 0.1, 1.0),
    ):
        for split, delta in (("train", train_delta), ("holdout", holdout_delta)):
            summaries.append(
                {
                    "policy_id": f"candidate__{candidate.candidate_id}",
                    "game": SUPER,
                    "split": split,
                    "delta_robust_roi_mean": delta,
                }
            )
    assert _rank_family(summaries, hot, SUPER, "hot")[0] == hot[0]


def test_strategy_search_gate_passes_complete_structure(contexts_by_game):
    policies = _policies_by_game()
    winners = {game: _winner_map() for game in (SUPER, LOTTO649)}
    probe = strategy_determinism_probe(contexts_by_game, policies)
    gate = build_strategy_search_gate(
        contexts_by_game,
        coarse_candidates(),
        winners,
        winners,
        policies,
        probe,
    )
    require_gate(gate)
    assert gate["status"] == "pass"
    assert probe["comparisons"] == 10
    assert all(len(digest) == 64 for digest in probe["ticket_sha256"].values())


def test_strategy_search_gate_rejects_leak_or_bad_policy(contexts_by_game):
    policies = _policies_by_game()
    winners = {game: _winner_map() for game in (SUPER, LOTTO649)}
    leaked = {game: list(contexts) for game, contexts in contexts_by_game.items()}
    context = leaked[SUPER][1]
    leaked[SUPER][1] = replace(
        context,
        history=context.history + (context.draws[0],),
    )
    bad_policies = {game: list(items) for game, items in policies.items()}
    bad_policies[LOTTO649][0] = {
        "policy_id": "random_5",
        "slots": [UNIFORM.as_dict()] * 4,
    }
    gate = build_strategy_search_gate(
        leaked,
        coarse_candidates(),
        winners,
        winners,
        bad_policies,
        {"passed": False, "comparisons": 10},
    )
    with pytest.raises(StageGateError, match="super.no_lookahead"):
        require_gate(gate)
