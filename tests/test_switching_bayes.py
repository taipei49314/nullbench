"""Exact-outcome, timing, recovery, and artifact tests for v2."""
from __future__ import annotations

from copy import deepcopy
from itertools import islice
import json
import math
from pathlib import Path

import pytest

from engine.agent_loop import canonical_hash
from engine.games import LOTTO649, POOL, SPECIAL_POOL, SUPER
from research.gates import tree_sha256
from research.switching_bayes import (
    EXPERT_IDS,
    FIXED_SHARE,
    UNIFORM_EXPERT,
    build_score_capsule,
    fixed_share_update,
    forecast,
    initial_weights,
    main_outcome_log_probabilities,
    mixture_label_distribution,
    mixture_outcome_log_probability,
    run_switching_bayes_study,
    select_shadow_portfolio,
    settle_score_capsule,
    snapshot_expert_distributions,
    static_expert_regret_bound,
    validate_forward_candidate,
    validate_score_capsule,
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
    root = tmp_path_factory.mktemp("switching-bayes")
    ledgers = {}
    for game, source in SOURCES.items():
        target = root / f"{game}.jsonl"
        with source.open(encoding="utf-8") as handle:
            target.write_text(
                "".join(islice(handle, 82)),
                encoding="utf-8",
            )
        ledgers[game] = target
    before = tree_sha256(BASE / "records")
    result = run_switching_bayes_study(
        ledgers,
        base=BASE,
        verify_ledgers=False,
    )
    return root, before, result


@pytest.mark.parametrize("game", [SUPER, LOTTO649])
def test_full_snapshot_experts_are_unique_complete_and_normalized(game):
    decision = _events(game, 1)[0]["decision"]
    experts = snapshot_expert_distributions(game, decision)

    assert set(experts) == set(EXPERT_IDS)
    assert "independent_null" not in experts
    assert UNIFORM_EXPERT in experts
    for distribution in experts.values():
        assert set(distribution) == set(range(1, POOL[game] + 1))
        assert math.fsum(distribution.values()) == pytest.approx(
            1.0,
            abs=1e-12,
        )
        assert all(value > 0 for value in distribution.values())


def test_special_snapshot_experts_are_complete():
    decision = _events(SUPER, 1)[0]["decision"]
    experts = snapshot_expert_distributions(
        SUPER,
        decision,
        dimension="special",
    )
    for distribution in experts.values():
        assert len(distribution) == SPECIAL_POOL[SUPER]
        assert math.fsum(distribution.values()) == pytest.approx(
            1.0,
            abs=1e-12,
        )


def test_exact_subset_mixture_and_fixed_share_update_are_coherent():
    event = _events(SUPER, 1)[0]
    experts = snapshot_expert_distributions(
        SUPER,
        event["decision"],
    )
    weights = initial_weights()
    logs = main_outcome_log_probabilities(
        experts,
        event["reveal"]["numbers"],
    )
    mixture_log = mixture_outcome_log_probability(logs, weights)
    expected = math.log(
        math.fsum(
            weights[expert] * math.exp(logs[expert])
            for expert in EXPERT_IDS
        )
    )
    next_prior, posterior = fixed_share_update(weights, logs)

    assert mixture_log == pytest.approx(expected, abs=3e-15)
    assert math.fsum(posterior.values()) == pytest.approx(1.0)
    assert math.fsum(next_prior.values()) == pytest.approx(1.0)
    assert min(next_prior.values()) >= (
        FIXED_SHARE / len(EXPERT_IDS) - 1e-15
    )


def test_fixed_share_recovers_an_expert_after_prior_collapse():
    floor = FIXED_SHARE / len(EXPERT_IDS)
    weights = {
        expert: floor
        for expert in EXPERT_IDS
    }
    weights[UNIFORM_EXPERT] += 1.0 - math.fsum(weights.values())
    winner = EXPERT_IDS[0]
    logs = {
        expert: (-1.0 if expert == winner else -20.0)
        for expert in EXPERT_IDS
    }
    next_prior, posterior = fixed_share_update(weights, logs)

    assert posterior[winner] > 0.999
    assert next_prior[winner] > 0.99
    assert all(value >= floor - 1e-15 for value in next_prior.values())


def test_label_mixture_is_not_the_outcome_likelihood_shortcut():
    event = _events(LOTTO649, 1)[0]
    experts = snapshot_expert_distributions(
        LOTTO649,
        event["decision"],
    )
    weights = initial_weights()
    mixed = mixture_label_distribution(experts, weights)

    assert math.fsum(mixed.values()) == pytest.approx(1.0)
    expert_logs = main_outcome_log_probabilities(
        experts,
        event["reveal"]["numbers"],
    )
    exact = mixture_outcome_log_probability(
        expert_logs,
        weights,
    )
    shortcut = main_outcome_log_probabilities(
        {expert: mixed for expert in EXPERT_IDS},
        event["reveal"]["numbers"],
    )[EXPERT_IDS[0]]
    assert exact != pytest.approx(shortcut, abs=1e-12)


def test_static_expert_bound_is_finite_and_increases_with_recovery():
    assert static_expert_regret_bound(1) == pytest.approx(
        math.log(len(EXPERT_IDS))
    )
    assert static_expert_regret_bound(208) > (
        static_expert_regret_bound(1)
    )


def test_smoke_walk_forward_is_future_only_and_preserves_records(
    smoke_study,
):
    _, before, result = smoke_study

    assert result["data_quality"]["status"] == "pass"
    assert result["decision"]["status"] == "future_shadow_only"
    assert result["decision"]["belief_layer_promoted"] is False
    assert result["records_integrity"]["before"] == before
    assert result["records_integrity"]["unchanged"] is True
    for game in (SUPER, LOTTO649):
        summary = result["prequential_summary"][game]
        assert summary["draws"] == 82
        assert summary["main_bound_pass"] is True
        assert summary["minimum_observed_next_prior_weight"] >= (
            FIXED_SHARE / len(EXPERT_IDS) - 1e-15
        )
    validate_forward_candidate(
        result["future_forward_shadow_candidate"]
    )


@pytest.mark.parametrize("game", [SUPER, LOTTO649])
def test_future_forecast_portfolio_and_exact_score_capsule(
    smoke_study,
    game,
):
    _, _, result = smoke_study
    candidate = result["future_forward_shadow_candidate"]
    event = _events(game, 83)[-1]
    prediction = forecast(game, event["decision"], candidate)
    tickets, metadata = select_shadow_portfolio(
        game,
        event["decision"],
        candidate,
    )
    capsule = build_score_capsule(prediction)
    validate_score_capsule(capsule)
    score = settle_score_capsule(
        capsule,
        actual_main=event["reveal"]["numbers"],
        actual_special=(
            event["reveal"]["special"]
            if game == SUPER
            else None
        ),
    )

    assert len(tickets) == 5
    assert metadata["structure"]["main_union_size"] == 30
    assert score["result_hash"] == canonical_hash(
        {
            key: value
            for key, value in score.items()
            if key != "result_hash"
        }
    )
    assert math.fsum(
        score["next_main_prior_weights"].values()
    ) == pytest.approx(1.0)


def test_tamper_and_same_day_forecast_fail_closed(smoke_study):
    _, _, result = smoke_study
    candidate = deepcopy(result["future_forward_shadow_candidate"])
    candidate["models"][SUPER]["main_prior_weights"][
        UNIFORM_EXPERT
    ] += 0.1
    with pytest.raises(ValueError):
        validate_forward_candidate(candidate)

    candidate = result["future_forward_shadow_candidate"]
    decision = deepcopy(_events(SUPER, 83)[-1]["decision"])
    decision["target"]["date"] = candidate["fitted_through"][SUPER]
    payload = {
        key: value
        for key, value in decision.items()
        if key != "decision_hash"
    }
    decision["decision_hash"] = canonical_hash(payload)
    with pytest.raises(ValueError, match="含目標期"):
        forecast(SUPER, decision, candidate)


def test_score_capsule_tamper_and_result_write_are_detected(
    smoke_study,
):
    root, _, result = smoke_study
    candidate = result["future_forward_shadow_candidate"]
    event = _events(SUPER, 83)[-1]
    capsule = build_score_capsule(
        forecast(SUPER, event["decision"], candidate)
    )
    capsule["main_expert_probability_mass"][
        EXPERT_IDS[0]
    ][0] += 0.01
    with pytest.raises(ValueError, match="契約"):
        validate_score_capsule(capsule)

    path = write_results(result, root / "out")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["experiment_id"] == result["experiment_id"]
