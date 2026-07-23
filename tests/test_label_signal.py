"""30 號標籤排序的 walk-forward、零模型與封存測試。"""
from __future__ import annotations

from itertools import islice
import json
import math
from pathlib import Path

import pytest

from engine.games import LOTTO649, SUPER
from research.label_signal import (
    METRICS,
    RANKER_NAMES,
    LabelSignalConfig,
    _binomial_upper_tail,
    _hypergeometric_total_upper_tail,
    _initial_history_state,
    _update_history_state,
    candidate_rankings,
    run_label_signal_study,
    write_results,
)


BASE = Path(__file__).parent.parent
SIMULATION = BASE / "simulation" / "results"


def _event(game: str, sequence: int = 61) -> dict:
    with (SIMULATION / f"{game}.jsonl").open(
        encoding="utf-8"
    ) as handle:
        return json.loads(next(islice(handle, sequence - 1, sequence)))


@pytest.mark.parametrize("game", [SUPER, LOTTO649])
def test_rankers_are_deterministic_complete_and_reveal_free(game):
    state = _initial_history_state(game)
    for sequence in range(1, 61):
        event = _event(game, sequence)
        _update_history_state(state, event["reveal"]["numbers"])
    decision = _event(game, 61)["decision"]

    first = candidate_rankings(game, decision, state)
    second = candidate_rankings(game, decision, state)

    assert first == second
    assert tuple(first) == RANKER_NAMES
    assert all(
        len(ranking) == len(set(ranking)) == (
            38 if game == SUPER else 49
        )
        for ranking in first.values()
    )
    assert "reveal" not in candidate_rankings.__code__.co_varnames


def test_hypergeometric_total_tail_matches_direct_two_period_convolution():
    pool = 12
    selected = 7
    drawn = 3
    single_counts = [
        math.comb(selected, hits)
        * math.comb(pool - selected, drawn - hits)
        for hits in range(drawn + 1)
    ]
    denominator = math.comb(pool, drawn) ** 2
    expected = (
        sum(
            left_count * right_count
            for left, left_count in enumerate(single_counts)
            for right, right_count in enumerate(single_counts)
            if left + right >= 4
        )
        / denominator
    )

    assert _hypergeometric_total_upper_tail(
        pool=pool,
        selected=selected,
        drawn=drawn,
        periods=2,
        observed=4,
    ) == pytest.approx(expected)


def test_binomial_upper_tail_matches_closed_form():
    assert _binomial_upper_tail(4, 3, 0.25) == pytest.approx(
        4 * 0.25**3 * 0.75 + 0.25**4
    )


@pytest.fixture(scope="module")
def smoke_result(tmp_path_factory):
    temp = tmp_path_factory.mktemp("label-signal")
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
    result = run_label_signal_study(
        ledgers,
        base=BASE,
        config=LabelSignalConfig(
            warmup_draws=60,
            bootstrap_samples=100,
            bootstrap_block=3,
        ),
        verify_ledgers=False,
    )
    paths = write_results(result, temp / "results")
    return result, paths


def test_smoke_study_freezes_splits_rankers_and_preserves_records(
    smoke_result,
):
    result, paths = smoke_result

    assert result["data_quality"]["status"] == "pass"
    assert result["records_integrity"]["unchanged"] is True
    assert result["methodology"]["rankers"] == list(RANKER_NAMES)
    assert {
        (row["game"], row["split"], row["ranker"])
        for row in result["summary"]
    } == {
        (game, split, ranker)
        for game in (SUPER, LOTTO649)
        for split in ("development", "holdout")
        for ranker in RANKER_NAMES
    }
    assert all(
        metric in row
        for row in result["summary"]
        for metric in METRICS
    )
    assert all(path.exists() for path in paths.values())


def test_smoke_null_evidence_is_bounded_and_holdout_only(
    smoke_result,
):
    result, _ = smoke_result

    for game in (SUPER, LOTTO649):
        evidence = result[
            "consensus_holdout_vs_exact_uniform_null"
        ][game]
        profile = result["data_quality"]["split_profiles"][game]
        assert evidence["draws"] == profile["holdout_draws"]
        assert all(
            0 <= value <= 1
            for value in evidence[
                "raw_one_sided_p_values"
            ].values()
        )
        assert all(
            0 <= value <= 1
            for value in evidence[
                "holm_adjusted_one_sided_p_values"
            ].values()
        )
        assert isinstance(
            evidence["predictive_label_signal_supported"], bool
        )
