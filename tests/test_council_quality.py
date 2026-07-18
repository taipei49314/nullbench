"""Agent 品質、覆蓋替換、辯論校準與裁判敏感度研究。"""
from __future__ import annotations

from itertools import islice
import json
from pathlib import Path

import pytest

from engine.agent_loop import AGENT_IDS
from engine.games import LOTTO649, SUPER, Draw
from research.council_quality import (
    CANDIDATE_AGENT_ID,
    QualityConfig,
    _adjudicate_variant,
    build_coverage_proposals,
    replacement_council,
    run_quality_study,
    write_results,
)


BASE = Path(__file__).parent.parent
SIMULATION = BASE / "simulation" / "results"


def _event(game: str, sequence: int) -> dict:
    with (SIMULATION / f"{game}.jsonl").open(encoding="utf-8") as handle:
        return json.loads(next(islice(handle, sequence - 1, sequence)))


def _history(game: str, lines: int) -> list[Draw]:
    draws = []
    with (SIMULATION / f"{game}.jsonl").open(encoding="utf-8") as handle:
        for line in islice(handle, lines):
            reveal = json.loads(line)["reveal"]
            draws.append(
                Draw(
                    game=game,
                    period=int(reveal["period"]),
                    date=reveal["date"],
                    numbers=tuple(reveal["numbers"]),
                    special=int(reveal["special"]),
                )
            )
    return draws


def _copy_prefix(source: Path, target: Path, lines: int) -> None:
    with source.open(encoding="utf-8") as handle:
        target.write_text(
            "".join(islice(handle, lines)),
            encoding="utf-8",
        )


@pytest.mark.parametrize("game", [SUPER, LOTTO649])
def test_coverage_candidate_is_deterministic_legal_and_reveal_free(game):
    event = _event(game, 61)
    existing = [
        proposal
        for proposal in event["decision"]["proposals"]
        if proposal["agent"] != "hot_hunter"
    ]
    first = build_coverage_proposals(
        game,
        event["decision"]["target"],
        existing,
        samples_per_variant=20,
    )
    second = build_coverage_proposals(
        game,
        event["decision"]["target"],
        existing,
        samples_per_variant=20,
    )

    assert first == second
    assert len(first) == 3
    assert {proposal["agent"] for proposal in first} == {
        CANDIDATE_AGENT_ID
    }
    assert len({tuple(proposal["numbers"]) for proposal in first}) == 3
    assert all(len(proposal["numbers"]) == 6 for proposal in first)
    assert "reveal" not in build_coverage_proposals.__code__.co_varnames


@pytest.mark.parametrize("game", [SUPER, LOTTO649])
def test_replacement_council_restores_fifteen_proposals_and_sixty_critiques(
    game,
):
    event = _event(game, 61)
    tickets, proposals, critiques = replacement_council(
        game,
        event["decision"]["target"],
        _history(game, 60),
        event["decision"],
        "hot_hunter",
    )

    assert len(proposals) == 15
    assert len(critiques) == 60
    assert len(tickets) == 5
    assert "hot_hunter" not in {
        proposal["agent"] for proposal in proposals
    }
    assert CANDIDATE_AGENT_ID in {
        proposal["agent"] for proposal in proposals
    }
    critique_counts = {}
    for critique in critiques:
        critique_counts[critique["target"]] = (
            critique_counts.get(critique["target"], 0) + 1
        )
    assert set(critique_counts.values()) == {4}


@pytest.mark.parametrize("game", [SUPER, LOTTO649])
def test_default_sensitivity_adjudicator_exactly_matches_replay(game):
    event = _event(game, 61)
    decision = event["decision"]
    ratings = {
        agent: float(state["rating"])
        for agent, state in decision["state_before"]["agents"].items()
    }
    tickets = _adjudicate_variant(
        decision["proposals"],
        decision["critiques"],
        ratings,
    )
    assert tickets == decision["selected_tickets"]


@pytest.fixture(scope="module")
def smoke_result(tmp_path_factory):
    temp = tmp_path_factory.mktemp("council-quality")
    ledgers = {}
    for game in (SUPER, LOTTO649):
        target = temp / f"{game}.jsonl"
        _copy_prefix(SIMULATION / f"{game}.jsonl", target, 82)
        ledgers[game] = target
    result = run_quality_study(
        ledgers,
        base=BASE,
        config=QualityConfig(
            warmup_draws=60,
            bootstrap_samples=100,
            bootstrap_block=3,
        ),
        verify_ledgers=False,
    )
    paths = write_results(result, temp / "results")
    return result, paths


def test_smoke_study_covers_all_agents_critics_variants_and_splits(
    smoke_result,
):
    result, paths = smoke_result
    assert result["data_quality"]["status"] == "pass"
    assert result["records_integrity"]["unchanged"] is True
    assert len(result["agent_quality"]) == 2 * 2 * 5
    assert len(result["critic_quality"]) == 2 * 2 * 5
    assert len(result["critic_pair_redundancy"]) == 2 * 2 * 10
    assert len(result["judge_sensitivity"]) == 2 * 2 * 5
    assert result["conclusion"]["status"] in {
        "promote_candidate",
        "retain_current_council",
    }
    assert all(path.exists() for path in paths.values())
    assert not list(paths["json"].parent.glob("*.tmp"))
    assert all(
        result["data_quality"]["split_profiles"][game]["holdout_draws"] == 7
        for game in (SUPER, LOTTO649)
    )


def test_replacement_is_selected_on_development_then_frozen_for_holdout(
    smoke_result,
):
    result, _ = smoke_result
    for game in (SUPER, LOTTO649):
        selected = result["selected_replacements"][game]
        development = [
            row
            for row in result["agent_quality"]
            if row["game"] == game and row["split"] == "development"
        ]
        expected = sorted(
            development,
            key=lambda row: (
                -row["replacement_delta_best_main_hits"],
                -row["replacement_delta_union_main_hits"],
                -row["replacement_delta_union_size"],
                row["agent"],
            ),
        )[0]
        assert selected["removed_agent"] == expected["agent"]
        assert (
            selected["holdout"]["agent"]
            == selected["development"]["agent"]
        )
        assert len(result["recent_holdout_trace"][game]) == 7
        assert set(selected["development"]["agent"] for _ in [0]) <= set(
            AGENT_IDS
        )
