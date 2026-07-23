"""條件轉移排序的 lookahead、巢狀切分與校準測試。"""
from __future__ import annotations

from itertools import islice
import json
from pathlib import Path

import pytest

from engine.games import LOTTO649, SUPER
from research.gates import tree_sha256
from research.label_signal import _tickets_from_ranking
from research.portfolio_coverage import portfolio_structure
from research.transition_signal import (
    TRANSITION_CANDIDATES,
    TransitionSignalConfig,
    _initial_transition_state,
    _update_transition_state,
    candidate_transition_rankings,
    run_transition_signal_study,
    transition_protocol_reference,
    verify_transition_protocol,
    write_results,
)


BASE = Path(__file__).parent.parent
SIMULATION = BASE / "simulation" / "results"


def _events(game: str, count: int) -> list[dict]:
    with (SIMULATION / f"{game}.jsonl").open(
        encoding="utf-8"
    ) as handle:
        return [
            json.loads(line) for line in islice(handle, count)
        ]


@pytest.mark.parametrize("game", [SUPER, LOTTO649])
def test_transition_rankings_are_deterministic_complete_and_reveal_free(
    game,
):
    events = _events(game, 61)
    state = _initial_transition_state(game)
    for event in events[:60]:
        _update_transition_state(
            state, event["reveal"]["numbers"]
        )

    first = candidate_transition_rankings(
        game, events[60]["decision"], state
    )
    second = candidate_transition_rankings(
        game, events[60]["decision"], state
    )

    assert first == second
    assert tuple(first) == TRANSITION_CANDIDATES
    assert all(
        len(ranking) == len(set(ranking)) == (
            38 if game == SUPER else 49
        )
        for ranking in first.values()
    )
    assert (
        "reveal"
        not in candidate_transition_rankings.__code__.co_varnames
    )


def test_lag_transition_learns_only_after_reveal():
    state = _initial_transition_state(SUPER)
    source = [1, 2, 3, 4, 5, 6]
    target = [9, 10, 11, 12, 13, 14]
    for _ in range(80):
        _update_transition_state(state, source)
        _update_transition_state(state, target)
    _update_transition_state(state, source)
    event = _events(SUPER, 1)[0]

    ranking = candidate_transition_rankings(
        SUPER, event["decision"], state
    )["lag1_all_lift"]

    assert set(target) <= set(ranking[:12])
    before = state["all"][1]["transitions"]
    candidate_transition_rankings(
        SUPER, event["decision"], state
    )
    assert state["all"][1]["transitions"] == before


def test_transition_protocol_is_tamper_evident():
    reference = transition_protocol_reference()
    verify_transition_protocol(reference)
    forged = dict(reference)
    forged["prior_strength"] = 1.0
    with pytest.raises(ValueError, match="預註冊契約"):
        verify_transition_protocol(forged)


@pytest.mark.parametrize("game", [SUPER, LOTTO649])
def test_transition_portfolio_preserves_disjoint_structure(game):
    events = _events(game, 61)
    state = _initial_transition_state(game)
    for event in events[:60]:
        _update_transition_state(
            state, event["reveal"]["numbers"]
        )
    ranking = candidate_transition_rankings(
        game, events[60]["decision"], state
    )[TRANSITION_CANDIDATES[0]]
    structure = portfolio_structure(
        game,
        _tickets_from_ranking(
            game, events[60]["decision"], ranking
        ),
    )

    assert structure["main_union_size"] == 30
    assert structure["maximum_pairwise_main_overlap"] == 0


@pytest.fixture(scope="module")
def smoke_result(tmp_path_factory):
    temp = tmp_path_factory.mktemp("transition-signal")
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
    result = run_transition_signal_study(
        ledgers,
        base=BASE,
        config=TransitionSignalConfig(
            warmup_draws=60,
            bootstrap_samples=100,
            bootstrap_block=3,
        ),
        verify_ledgers=False,
    )
    paths = write_results(result, temp / "results")
    return result, paths


def test_smoke_profiles_nested_splits_and_preserves_records(
    smoke_result,
):
    result, paths = smoke_result

    assert result["data_quality"]["status"] == "pass"
    assert result["records_integrity"]["unchanged"] is True
    assert result["protocol"] == transition_protocol_reference()
    for game in (SUPER, LOTTO649):
        split = result["data_quality"]["split_profiles"][game]
        assert split["holdout_draws"] == 7
        assert split["inner_validation_draws"] == 5
        assert result["decisions"][game][
            "inner_selection_used_holdout"
        ] is False
    assert all(path.exists() for path in paths.values())


def test_smoke_corrects_all_sixteen_holdout_tests(smoke_result):
    result, _ = smoke_result
    rows = result["candidate_holdout"]

    assert len(rows) == 2 * len(TRANSITION_CANDIDATES)
    assert {
        (row["game"], row["candidate"]) for row in rows
    } == {
        (game, candidate)
        for game in (SUPER, LOTTO649)
        for candidate in TRANSITION_CANDIDATES
    }
    assert all(
        0
        <= row["holdout_raw_exact_null_one_sided_p_value"]
        <= 1
        and 0
        <= row[
            "holm_adjusted_exact_null_one_sided_p_value"
        ]
        <= 1
        for row in rows
    )


def test_smoke_forward_protocol_is_shadow_only_and_hashed(
    smoke_result,
):
    result, _ = smoke_result
    forward = result["future_forward_shadow_protocol"]

    assert len(forward["candidate_hash"]) == 64
    assert forward["promotion_eligible"] is False
    assert forward["use"] == "future_forward_shadow_only"
    assert set(forward["algorithms"]) == {SUPER, LOTTO649}
    assert forward["registration_eligible"] is any(
        candidate != "consensus"
        for candidate in forward["algorithms"].values()
    )
    assert tree_sha256(BASE / "records") == result[
        "records_integrity"
    ]["after_sha256"]
