"""同 30 號五注分組的結構不變、無前視與封存研究測試。"""
from __future__ import annotations

from itertools import islice
import json
from pathlib import Path

import pytest

from engine.games import LOTTO649, SUPER
from research.partition_signal import (
    PARTITIONER_NAMES,
    PartitionSignalConfig,
    _initial_pair_state,
    _tickets_from_partition,
    _update_pair_state,
    candidate_partitions,
    run_partition_signal_study,
    write_results,
)
from research.portfolio_coverage import portfolio_structure


BASE = Path(__file__).parent.parent
SIMULATION = BASE / "simulation" / "results"


def _events(game: str, count: int = 61) -> list[dict]:
    with (SIMULATION / f"{game}.jsonl").open(
        encoding="utf-8"
    ) as handle:
        return [
            json.loads(line) for line in islice(handle, count)
        ]


@pytest.mark.parametrize(
    ("game", "any_prize", "three_main"),
    [
        (SUPER, 0.5429629500836931, 0.1920413839918484),
        (LOTTO649, 0.15296613117321764, 0.09290168005643094),
    ],
)
def test_partitioners_are_deterministic_reveal_free_and_structurally_equal(
    game,
    any_prize,
    three_main,
):
    events = _events(game)
    state = _initial_pair_state(game)
    for event in events[:60]:
        _update_pair_state(state, event["reveal"]["numbers"])
    decision = events[60]["decision"]

    first = candidate_partitions(game, decision, state)
    second = candidate_partitions(game, decision, state)

    assert first == second
    assert tuple(first) == PARTITIONER_NAMES
    assert (
        "reveal" not in candidate_partitions.__code__.co_varnames
    )
    selected_sets = {
        frozenset(number for group in groups for number in group)
        for groups in first.values()
    }
    assert len(selected_sets) == 1
    for groups in first.values():
        structure = portfolio_structure(
            game,
            _tickets_from_partition(game, decision, groups),
        )
        assert structure["main_union_size"] == 30
        assert structure["maximum_pairwise_main_overlap"] == 0
        assert structure["exact_any_prize"] == pytest.approx(
            any_prize
        )
        assert structure[
            "exact_at_least_three_main"
        ] == pytest.approx(three_main)


@pytest.fixture(scope="module")
def smoke_result(tmp_path_factory):
    temp = tmp_path_factory.mktemp("partition-signal")
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
    result = run_partition_signal_study(
        ledgers,
        base=BASE,
        config=PartitionSignalConfig(
            warmup_draws=60,
            bootstrap_samples=100,
            bootstrap_block=3,
        ),
        verify_ledgers=False,
    )
    paths = write_results(result, temp / "results")
    return result, paths


def test_smoke_study_has_fixed_candidates_splits_and_integrity(
    smoke_result,
):
    result, paths = smoke_result

    assert result["data_quality"]["status"] == "pass"
    assert result["records_integrity"]["unchanged"] is True
    assert result["methodology"]["partitioners"] == list(
        PARTITIONER_NAMES
    )
    assert {
        (row["game"], row["split"], row["partitioner"])
        for row in result["summary"]
    } == {
        (game, split, partitioner)
        for game in (SUPER, LOTTO649)
        for split in ("development", "holdout")
        for partitioner in PARTITIONER_NAMES
    }
    assert all(path.exists() for path in paths.values())


def test_smoke_decision_does_not_select_from_holdout_after_failure(
    smoke_result,
):
    result, _ = smoke_result

    for game in (SUPER, LOTTO649):
        decision = result[
            "development_selection_and_holdout"
        ][game]
        assert decision["development_selected_partitioner"] in (
            PARTITIONER_NAMES
        )
        assert isinstance(decision["promotion_eligible"], bool)
        if decision["promotion_eligible"] is False:
            assert decision["decision"] == "retain_round_robin"
