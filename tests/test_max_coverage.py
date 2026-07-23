"""Agent 共識完全分散五注研究測試。"""
from itertools import islice
import json
from pathlib import Path

import pytest

from engine.games import LOTTO649, SUPER
from research.max_coverage import (
    OFFICIAL_RULE_URLS,
    _support_rows,
    run_max_coverage_study,
    select_consensus_disjoint_portfolio,
)
from research.portfolio_coverage import (
    CoverageConfig,
    _pair_any_prize_intersection_probability,
)


BASE = Path(__file__).parent.parent
SIMULATION = BASE / "simulation" / "results"


@pytest.fixture(scope="module")
def manifest():
    return json.loads(
        (SIMULATION / "manifest.json").read_text(encoding="utf-8")
    )


@pytest.mark.parametrize(
    ("game", "any_prize", "three_main"),
    [
        (SUPER, 0.5429629500836931, 0.1920413839918484),
        (LOTTO649, 0.15296613117321764, 0.09290168005643094),
    ],
)
def test_consensus_selector_is_deterministic_disjoint_and_exact(
    game,
    any_prize,
    three_main,
    manifest,
):
    decision = manifest["games"][game]["next_decision"]
    first, first_meta = select_consensus_disjoint_portfolio(
        game, decision
    )
    second, second_meta = select_consensus_disjoint_portfolio(
        game, decision
    )

    assert first == second
    assert first_meta == second_meta
    assert len(set().union(*(set(row["numbers"]) for row in first))) == 30
    assert all(
        set(left["numbers"]).isdisjoint(right["numbers"])
        for index, left in enumerate(first)
        for right in first[index + 1 :]
    )
    assert {
        number
        for ticket in first
        for number in ticket["numbers"]
    } == {
        row["number"] for row in _support_rows(game, decision)[:30]
    }
    assert first_meta["structure"]["exact_any_prize"] == pytest.approx(
        any_prize
    )
    assert first_meta["structure"][
        "exact_at_least_three_main"
    ] == pytest.approx(three_main)
    assert len(first_meta["support_evidence_hash"]) == 64
    assert first_meta["structural_optimum_proof"][
        "experiment_id"
    ] == "five-ticket-structural-optimum-proof-v1"
    assert len(
        first_meta["structural_optimum_proof"]["certificate_hash"]
    ) == 64
    if game == SUPER:
        assert len({ticket["special"] for ticket in first}) == 5
    else:
        assert all(ticket["special"] is None for ticket in first)
    assert (
        "reveal"
        not in select_consensus_disjoint_portfolio.__code__.co_varnames
    )


@pytest.mark.parametrize("game", [SUPER, LOTTO649])
def test_disjoint_structure_globally_minimizes_each_pair_intersection(
    game,
):
    if game == SUPER:
        minimum = _pair_any_prize_intersection_probability(
            game, 0, False
        )
        alternatives = [
            _pair_any_prize_intersection_probability(
                game, overlap, same_special
            )
            for overlap in range(6)
            for same_special in (False, True)
            if (overlap, same_special) != (0, False)
        ]
    else:
        minimum = _pair_any_prize_intersection_probability(
            game, 0, None
        )
        alternatives = [
            _pair_any_prize_intersection_probability(
                game, overlap, None
            )
            for overlap in range(1, 6)
        ]

    assert all(value > minimum for value in alternatives)


@pytest.fixture(scope="module")
def smoke_result(tmp_path_factory):
    temp = tmp_path_factory.mktemp("max-coverage")
    ledgers = {}
    for game in (SUPER, LOTTO649):
        target = temp / f"{game}.jsonl"
        with (SIMULATION / f"{game}.jsonl").open(
            encoding="utf-8"
        ) as source:
            target.write_text(
                "".join(islice(source, 82)),
                encoding="utf-8",
            )
        ledgers[game] = target
    return run_max_coverage_study(
        ledgers,
        base=BASE,
        config=CoverageConfig(
            warmup_draws=60,
            bootstrap_samples=100,
            bootstrap_block=3,
        ),
        verify_ledgers=False,
    )


def test_smoke_study_has_both_splits_and_preserves_records(
    smoke_result,
):
    assert smoke_result["records_integrity"]["unchanged"] is True
    assert (
        smoke_result["methodology"]["official_prize_rules"]
        == OFFICIAL_RULE_URLS
    )
    assert {
        (row["game"], row["split"])
        for row in smoke_result["summary"]
    } == {
        (SUPER, "development"),
        (SUPER, "holdout"),
        (LOTTO649, "development"),
        (LOTTO649, "holdout"),
    }
    assert all(
        row["structural_non_decrease_rate"] == 1.0
        and row["max_union_size"] == 30
        and row[
            "minimum_max_minus_proposal_coverage_exact_any_prize"
        ]
        >= -1e-15
        and row[
            "minimum_max_minus_proposal_coverage_exact_three_main"
        ]
        >= -1e-15
        for row in smoke_result["summary"]
    )
