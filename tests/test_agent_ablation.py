"""Agent 數量消融：組合、無前視、評等、基準與統計測試。"""
from __future__ import annotations

from itertools import islice
import json
from pathlib import Path

import pytest

from engine.agent_loop import AGENT_IDS
from engine.games import LOTTO649, SUPER
from research.agent_ablation import (
    AblationConfig,
    adjudicate_council,
    agent_subsets,
    block_bootstrap_ci,
    portfolio_metrics,
    random_baseline_metrics,
    run_ablation,
    subset_id,
    update_subset_ratings,
    write_results,
)


BASE = Path(__file__).parent.parent
SIMULATION = BASE / "simulation" / "results"


def _event(game: str, sequence: int) -> dict:
    with (SIMULATION / f"{game}.jsonl").open(encoding="utf-8") as handle:
        line = next(islice(handle, sequence - 1, sequence))
    return json.loads(line)


def _copy_prefix(source: Path, target: Path, lines: int) -> None:
    with source.open(encoding="utf-8") as read_handle:
        selected = list(islice(read_handle, lines))
    target.write_text("".join(selected), encoding="utf-8")


def test_all_agent_subsets_are_covered_once():
    subsets = agent_subsets()
    assert len(subsets) == 26
    assert len(set(subsets)) == len(subsets)
    assert {len(subset) for subset in subsets} == {2, 3, 4, 5}
    assert {
        size: sum(len(subset) == size for subset in subsets)
        for size in range(2, 6)
    } == {2: 10, 3: 10, 4: 5, 5: 1}
    assert all(tuple(sorted(subset)) == subset for subset in subsets)


@pytest.mark.parametrize("game", [SUPER, LOTTO649])
def test_subset_adjudication_uses_only_members_and_never_receives_reveal(game):
    event = _event(game, 61)
    decision = event["decision"]
    subset = ("balance_engineer", "random_monk")
    ratings = {agent: 1.0 for agent in AGENT_IDS}

    first = adjudicate_council(
        decision["proposals"], decision["critiques"], ratings, subset
    )
    changed_reveal = {
        **event["reveal"],
        "numbers": list(reversed(event["reveal"]["numbers"])),
    }
    second = adjudicate_council(
        decision["proposals"], decision["critiques"], ratings, subset
    )

    assert first == second
    assert changed_reveal != event["reveal"]
    assert len(first) == 5
    assert {ticket["source_agent"] for ticket in first} <= set(subset)
    assert len({tuple(ticket["numbers"]) for ticket in first}) == 5


def test_subset_rating_update_is_local_deterministic_and_post_reveal():
    ratings = {agent: 1.0 for agent in AGENT_IDS}
    qualities = {
        "antipop_taoist": 2.0,
        "balance_engineer": 1.0,
        "cold_keeper": 3.0,
        "hot_hunter": 0.0,
        "random_monk": 2.0,
    }
    subset = ("antipop_taoist", "cold_keeper")
    updated = update_subset_ratings(ratings, qualities, subset)

    assert updated == update_subset_ratings(ratings, qualities, subset)
    assert updated["cold_keeper"] > updated["antipop_taoist"]
    assert all(
        updated[agent] == 1.0 for agent in set(AGENT_IDS) - set(subset)
    )
    assert ratings == {agent: 1.0 for agent in AGENT_IDS}


def test_portfolio_metrics_match_known_super_outcome():
    reveal = {
        "date": "2026-01-01",
        "period": 115000001,
        "numbers": [1, 2, 3, 4, 5, 6],
        "special": 8,
    }
    tickets = [
        {"numbers": [1, 2, 3, 10, 11, 12], "special": 8},
        {"numbers": [4, 5, 20, 21, 22, 23], "special": 1},
        {"numbers": [6, 13, 14, 15, 16, 17], "special": 2},
        {"numbers": [7, 8, 9, 18, 19, 24], "special": 3},
        {"numbers": [25, 26, 27, 28, 29, 30], "special": 4},
    ]
    result = portfolio_metrics(SUPER, tickets, reveal)

    assert result["best_main_hits"] == 3
    assert result["total_main_hits"] == 6
    assert result["any_three_plus"] == 1
    assert result["special_hit_tickets"] == 1
    assert result["union_main_hits"] == 6
    assert result["union_size"] == 30
    assert result["any_prize"] == 1


@pytest.mark.parametrize("game", [SUPER, LOTTO649])
def test_random_baseline_is_deterministic(game):
    event = _event(game, 61)
    first = random_baseline_metrics(game, event["reveal"], 7)
    second = random_baseline_metrics(game, event["reveal"], 7)

    assert first == second
    assert 0 <= first["best_main_hits"] <= 6
    assert 0 <= first["union_main_hits"] <= 6
    assert 6 <= first["union_size"] <= 30


def test_block_bootstrap_is_deterministic_and_detects_clear_direction():
    differences = [0.2 + (index % 4) * 0.01 for index in range(80)]
    first = block_bootstrap_ci(
        differences, samples=300, block=13, seed="test"
    )
    second = block_bootstrap_ci(
        differences, samples=300, block=13, seed="test"
    )

    assert first == second
    assert first[0] > 0
    assert first[0] <= sum(differences) / len(differences) <= first[1]


@pytest.fixture(scope="module")
def smoke_result(tmp_path_factory):
    temp = tmp_path_factory.mktemp("agent-ablation")
    ledgers = {}
    for game in (SUPER, LOTTO649):
        target = temp / f"{game}.jsonl"
        _copy_prefix(SIMULATION / f"{game}.jsonl", target, 82)
        ledgers[game] = target
    result = run_ablation(
        ledgers,
        base=BASE,
        config=AblationConfig(
            warmup_draws=60,
            null_replicates=2,
            bootstrap_samples=100,
            bootstrap_block=3,
        ),
        verify_ledgers=False,
    )
    paths = write_results(result, temp / "results")
    return result, paths


def test_smoke_study_has_time_split_all_counts_and_no_records_write(smoke_result):
    result, paths = smoke_result

    assert result["data_quality"]["status"] == "pass"
    assert result["records_integrity"]["unchanged"] is True
    assert result["methodology"]["agent_subsets"] == 26
    assert result["conclusion"]["status"] in {"supported", "not_supported"}
    assert {
        (row["game"], row["split"], row["agent_count"])
        for row in result["count_summary"]
    } == {
        (game, split, size)
        for game in (SUPER, LOTTO649)
        for split in ("development", "holdout")
        for size in range(2, 6)
    }
    assert all(path.exists() for path in paths.values())
    assert all(
        result["data_quality"]["split_profiles"][game]["holdout_draws"] == 7
        for game in (SUPER, LOTTO649)
    )


def test_development_winner_is_selected_without_holdout_reranking(smoke_result):
    result, _ = smoke_result
    for game in (SUPER, LOTTO649):
        selected = result["selected_development_winners"][game]
        development = [
            row
            for row in result["subset_summary"]
            if row["game"] == game and row["split"] == "development"
        ]
        expected = sorted(
            development,
            key=lambda row: (
                -row["best_main_hits"],
                -row["total_main_hits"],
                -row["any_three_plus"],
                row["subset_id"],
            ),
        )[0]
        assert selected["subset_id"] == expected["subset_id"]
        assert (
            selected["holdout"]["subset_id"]
            == selected["development"]["subset_id"]
        )
        assert subset_id(tuple(selected["agents"])) == selected["subset_id"]
