"""研究層測試：隔離、決定性、時間切片與最小端到端。"""
from dataclasses import replace
from pathlib import Path

from engine.games import SUPER, validate_pick
from engine.store import DrawStore
from research.backtest import (
    CURRENT,
    Policy,
    UNIFORM,
    build_contexts,
    coarse_candidates,
    evaluate_policies,
    generate_policy_tickets,
    profile_data,
    summarize,
)

DATA = Path(__file__).parent.parent / "data"


def test_candidate_grid_ids_unique():
    candidates = coarse_candidates()
    assert len(candidates) == 31
    assert len({candidate.candidate_id for candidate in candidates}) == len(candidates)
    assert {"uniform", "hot", "cold", "balance", "antipop"} == {
        candidate.family for candidate in candidates
    }


def test_contexts_are_walk_forward_and_cover_all_draws():
    draws = DrawStore(DATA).draws(SUPER)
    contexts = build_contexts(SUPER, draws)
    assert sum(len(context.draws) for context in contexts) == len(draws)
    assert contexts[0].history == ()
    for context in contexts[1:20]:
        assert all(draw.date < min(item.date for item in context.draws) for draw in context.history)
    assert {context.split for context in contexts} == {"train", "validation", "holdout"}


def test_policy_generation_is_deterministic_and_valid():
    context = build_contexts(SUPER, DrawStore(DATA).draws(SUPER))[100]
    policy = Policy(
        "current",
        (
            UNIFORM,
            CURRENT["antipop"],
            CURRENT["balance"],
            CURRENT["cold"],
            CURRENT["hot"],
        ),
    )
    first = generate_policy_tickets(policy, context, replicate=0)
    second = generate_policy_tickets(policy, context, replicate=0)
    assert first == second
    assert len(first) == 5
    for ticket in first:
        validate_pick(SUPER, ticket["numbers"], ticket["special"])


def test_small_evaluation_and_summary():
    contexts = build_contexts(SUPER, DrawStore(DATA).draws(SUPER))
    # 每個 split 各取幾週，確保彙總三段都有 random_5 配對基準。
    sample = []
    for split in ("train", "validation", "holdout"):
        sample.extend([c for c in contexts if c.split == split][:3])
    policies = [
        Policy("random_5", (UNIFORM,) * 5),
        Policy("hot_5", (CURRENT["hot"],) * 5),
    ]
    results = evaluate_policies(sample, policies, replicates=2)
    summaries = summarize(results, bootstrap_samples=20)
    assert len(results) == len(sample) * len(policies) * 2
    assert len(summaries) == 2 * 3
    assert all(-1 <= row["raw_roi_mean"] for row in summaries)
    random_rows = [row for row in summaries if row["policy_id"] == "random_5"]
    assert all(row["delta_robust_roi_mean"] == 0 for row in random_rows)


def test_data_profile_passes():
    draws = DrawStore(DATA).draws(SUPER)
    profile = profile_data(SUPER, draws)
    assert profile["quality_status"] == "pass"
    assert profile["duplicate_periods"] == 0
    assert profile["invalid_numbers"] == 0
