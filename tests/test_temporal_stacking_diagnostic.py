"""時間自適應機率 stacking 的時序、分數與 artifact 契約測試。"""
from __future__ import annotations

from copy import deepcopy
from itertools import islice
import json
from pathlib import Path

import pytest

from engine.agent_loop import canonical_hash
from engine.games import LOTTO649, POOL, SUPER
from research.gates import tree_sha256
from research.probability_stacking import EXPERT_IDS, UNIFORM_EXPERT
from research.temporal_stacking_diagnostic import (
    METHODS,
    STREAMS,
    build_conclusion,
    evaluate_stream,
    initial_method_state,
    run_temporal_stacking_diagnostic,
    update_method_state,
    validate_result,
    write_results,
)


BASE = Path(__file__).parent.parent
SOURCES = {
    SUPER: BASE / "simulation" / "results" / "super.jsonl",
    LOTTO649: BASE / "simulation" / "results" / "lotto649.jsonl",
}


def _events(game: str, count: int) -> list[dict]:
    with SOURCES[game].open(encoding="utf-8") as handle:
        return [json.loads(line) for line in islice(handle, count)]


@pytest.fixture(scope="module")
def smoke_study(tmp_path_factory):
    root = tmp_path_factory.mktemp("temporal-stacking")
    ledgers = {}
    for game, source in SOURCES.items():
        target = root / f"{game}.jsonl"
        with source.open(encoding="utf-8") as handle:
            target.write_text(
                "".join(islice(handle, 40)),
                encoding="utf-8",
            )
        ledgers[game] = target
    result = run_temporal_stacking_diagnostic(
        ledgers,
        base=BASE,
        verify_ledgers=False,
        bootstrap_samples=50,
    )
    return root, result


def test_fixed_method_and_stream_family_is_complete():
    assert len(METHODS) == 9
    assert len(set(METHODS)) == 9
    assert set(STREAMS) == {
        "super_main",
        "super_special",
        "lotto649_main",
    }
    for method in METHODS:
        state = initial_method_state(method)
        assert state["method"] == method
        assert set(state["logs"]) == set(EXPERT_IDS)
        assert state["sequence"] == 0


def test_future_reveal_cannot_change_earlier_forecasts():
    original = _events(SUPER, 12)
    changed = deepcopy(original)
    changed[-1]["reveal"]["numbers"] = [1, 2, 3, 4, 5, 6]
    first = evaluate_stream(
        original,
        game=SUPER,
        dimension="main",
        bootstrap_samples=20,
    )
    second = evaluate_stream(
        changed,
        game=SUPER,
        dimension="main",
        bootstrap_samples=20,
    )

    for method in METHODS:
        assert first["traces"][method][:-1] == (
            second["traces"][method][:-1]
        )


def test_evaluation_is_deterministic():
    events = _events(LOTTO649, 16)
    first = evaluate_stream(
        events,
        game=LOTTO649,
        dimension="main",
        bootstrap_samples=25,
    )
    second = evaluate_stream(
        events,
        game=LOTTO649,
        dimension="main",
        bootstrap_samples=25,
    )
    assert first == second


def test_rolling_window_forgets_expired_regret():
    state = initial_method_state("subset_rolling_52")
    distribution = {
        number: 1 / POOL[SUPER]
        for number in range(1, POOL[SUPER] + 1)
    }
    distributions = {
        expert: distribution for expert in EXPERT_IDS
    }
    for sequence in range(1, 54):
        regrets = {expert: 0.0 for expert in EXPERT_IDS}
        if sequence == 1:
            regrets[EXPERT_IDS[0]] = 10.0
        state = update_method_state(
            state,
            distributions=distributions,
            actual=[1, 2, 3, 4, 5, 6],
            expert_regrets=regrets,
            sequence=sequence,
        )

    assert len(state["history"]) == 52
    assert all(value == 0.0 for value in state["logs"].values())


@pytest.mark.parametrize(
    ("game", "dimension"),
    [(SUPER, "main"), (SUPER, "special"), (LOTTO649, "main")],
)
def test_uniform_control_is_exact_zero(game, dimension):
    row = next(
        row
        for row in evaluate_stream(
            _events(game, 20),
            game=game,
            dimension=dimension,
            bootstrap_samples=20,
        )["rows"]
        if row["method"] == "uniform"
    )
    assert row["mean_regret_nats"] == 0.0
    assert row["bootstrap_95_low"] == 0.0
    assert row["bootstrap_95_high"] == 0.0
    assert row["final_uniform_expert_weight"] == 1.0
    assert row["final_e_value"] == pytest.approx(1.0, abs=1e-12)
    assert row["maximum_e_value"] == pytest.approx(1.0, abs=1e-12)


def test_smoke_study_is_descriptive_complete_and_read_only(
    smoke_study,
):
    _, result = smoke_study
    validate_result(result)
    assert len(result["diagnostic_rows"]) == 27
    assert result["conclusion"] == build_conclusion(
        result["diagnostic_rows"]
    )
    assert (
        result["conclusion"]["historical_promotion_eligible"]
        is False
    )
    assert (
        result["conclusion"]["watcher_integration_allowed"]
        is False
    )
    assert result["records_integrity"]["unchanged"] is True


def test_result_rejects_semantic_tamper_even_with_recomputed_hash(
    smoke_study,
):
    _, result = smoke_study
    tampered = deepcopy(result)
    uniform = next(
        row
        for row in tampered["diagnostic_rows"]
        if row["method"] == "uniform"
    )
    uniform["mean_regret_nats"] = -0.01
    uniform["mean_information_gain_nats"] = 0.01
    tampered["audit_hash"] = canonical_hash(
        {
            key: value
            for key, value in tampered.items()
            if key != "audit_hash"
        }
    )
    with pytest.raises(ValueError, match="均勻控制組"):
        validate_result(tampered)


def test_write_results_is_exact_and_records_remain_unchanged(
    smoke_study,
):
    root, result = smoke_study
    before = tree_sha256(BASE / "records")
    path = write_results(result, root / "results")

    assert json.loads(path.read_text(encoding="utf-8")) == result
    assert tree_sha256(BASE / "records") == before


def test_invalid_chronology_is_rejected():
    events = _events(SUPER, 3)
    events[2]["reveal"]["date"] = events[1]["reveal"]["date"]
    events[2]["reveal"]["period"] = events[1]["reveal"]["period"]
    events[2]["decision"]["target"] = deepcopy(events[2]["reveal"])
    events[2]["decision"]["target"].pop("numbers", None)
    events[2]["decision"]["target"].pop("special", None)

    with pytest.raises(ValueError):
        evaluate_stream(
            events,
            game=SUPER,
            dimension="main",
            bootstrap_samples=10,
        )
