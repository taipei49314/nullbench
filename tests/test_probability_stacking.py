"""機率堆疊的資料契約、時間邊界與結構測試。"""
from __future__ import annotations

from copy import deepcopy
from itertools import islice
import json
import math
from pathlib import Path

import pytest

from engine.agent_loop import AGENT_IDS, canonical_hash
from engine.games import LOTTO649, POOL, SPECIAL_POOL, SUPER
from research.gates import tree_sha256
from research.probability_stacking import (
    DEBATE_EXPERT,
    EXPERT_IDS,
    UNIFORM_EXPERT,
    build_probability_score_capsule,
    expert_distributions,
    mixture_distribution,
    portfolio_from_distribution,
    run_probability_stacking,
    select_probability_stacked_portfolio,
    settle_probability_score_capsule,
    update_log_weights,
    validate_forward_candidate,
    validate_probability_score_capsule,
    verify_probability_score_result,
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


def _rehash_decision(decision: dict) -> None:
    payload = {
        key: value
        for key, value in decision.items()
        if key != "decision_hash"
    }
    decision["decision_hash"] = canonical_hash(payload)


@pytest.fixture(scope="module")
def smoke_study(tmp_path_factory):
    root = tmp_path_factory.mktemp("probability-stacking")
    ledgers = {}
    for game, source_path in SOURCES.items():
        target = root / f"{game}.jsonl"
        with source_path.open(encoding="utf-8") as source:
            target.write_text(
                "".join(islice(source, 82)),
                encoding="utf-8",
            )
        ledgers[game] = target
    result = run_probability_stacking(
        ledgers,
        base=BASE,
        verify_ledgers=False,
    )
    return root, result


@pytest.mark.parametrize("game", [SUPER, LOTTO649])
def test_expert_distributions_are_complete_positive_and_normalized(game):
    decision = _events(game, 1)[0]["decision"]
    distributions = expert_distributions(game, decision)

    assert set(distributions) == set(EXPERT_IDS)
    assert set(AGENT_IDS) < set(distributions)
    assert DEBATE_EXPERT in distributions
    assert UNIFORM_EXPERT in distributions
    for distribution in distributions.values():
        assert set(distribution) == set(range(1, POOL[game] + 1))
        assert all(
            math.isfinite(probability) and probability > 0
            for probability in distribution.values()
        )
        assert math.fsum(distribution.values()) == pytest.approx(
            1.0,
            abs=1e-12,
        )


def test_super_special_experts_are_complete_positive_and_normalized():
    decision = _events(SUPER, 1)[0]["decision"]
    distributions = expert_distributions(
        SUPER,
        decision,
        dimension="special",
    )

    for distribution in distributions.values():
        assert set(distribution) == set(
            range(1, SPECIAL_POOL[SUPER] + 1)
        )
        assert math.fsum(distribution.values()) == pytest.approx(
            1.0,
            abs=1e-12,
        )


def test_weights_update_only_after_reveal_and_are_deterministic():
    event = _events(SUPER, 1)[0]
    experts = expert_distributions(SUPER, event["decision"])
    initial = {expert: 0.0 for expert in EXPERT_IDS}
    before = mixture_distribution(experts, initial)

    first_weights, first_losses = update_log_weights(
        initial,
        experts,
        event["reveal"]["numbers"],
        sequence=1,
    )
    repeated_weights, repeated_losses = update_log_weights(
        initial,
        experts,
        event["reveal"]["numbers"],
        sequence=1,
    )

    assert before == mixture_distribution(experts, initial)
    assert first_weights == repeated_weights
    assert first_losses == repeated_losses
    assert mixture_distribution(experts, first_weights) != before


@pytest.mark.parametrize("game", [SUPER, LOTTO649])
def test_portfolio_is_five_legal_disjoint_tickets(game):
    event = _events(game, 1)[0]
    logs = {expert: 0.0 for expert in EXPERT_IDS}
    main = mixture_distribution(
        expert_distributions(game, event["decision"]),
        logs,
    )
    special = (
        mixture_distribution(
            expert_distributions(
                SUPER,
                event["decision"],
                dimension="special",
            ),
            logs,
        )
        if game == SUPER
        else None
    )
    tickets, metadata = portfolio_from_distribution(
        game,
        main,
        special,
    )

    assert len(tickets) == 5
    assert metadata["structure"]["main_union_size"] == 30
    assert (
        metadata["structure"]["maximum_pairwise_main_overlap"]
        == 0
    )
    assert len(
        {
            number
            for ticket in tickets
            for number in ticket["numbers"]
        }
    ) == 30
    if game == SUPER:
        assert len({ticket["special"] for ticket in tickets}) == 5
    else:
        assert all(ticket["special"] is None for ticket in tickets)


def test_incomplete_debate_is_rejected_even_with_recomputed_hash():
    decision = deepcopy(_events(SUPER, 1)[0]["decision"])
    decision["critiques"].pop()
    _rehash_decision(decision)

    with pytest.raises(ValueError, match="60"):
        expert_distributions(SUPER, decision)


def test_tampered_decision_hash_and_score_are_rejected():
    decision = deepcopy(_events(LOTTO649, 1)[0]["decision"])
    decision["proposals"][0]["numbers"][0] = 49
    with pytest.raises(ValueError, match="decision_hash"):
        expert_distributions(LOTTO649, decision)

    decision = deepcopy(_events(LOTTO649, 1)[0]["decision"])
    decision["adjudication"]["candidate_scores"][0][
        "debate_score"
    ] = None
    _rehash_decision(decision)
    with pytest.raises(ValueError, match="辯論分數"):
        expert_distributions(LOTTO649, decision)


def test_smoke_study_profiles_history_without_promoting_it(smoke_study):
    _, result = smoke_study

    assert result["data_quality"]["status"] == "pass"
    assert result["conclusion"]["status"] == "future_shadow_only"
    assert (
        result["conclusion"]["historical_promotion_eligible"]
        is False
    )
    assert result["records_integrity"]["unchanged"] is True
    for game in (SUPER, LOTTO649):
        assert result["prequential_summary"][game]["draws"] == 82
        model = result["final_models"][game]
        assert set(model["main_weights"]) == set(EXPERT_IDS)
        assert math.fsum(model["main_weights"].values()) == pytest.approx(
            1.0,
            abs=1e-12,
        )
    validate_forward_candidate(
        result["future_forward_shadow_candidate"]
    )


@pytest.mark.parametrize("game", [SUPER, LOTTO649])
def test_future_candidate_selects_only_strictly_later_draw(
    smoke_study,
    game,
):
    _, result = smoke_study
    future_decision = _events(game, 83)[-1]["decision"]
    tickets, metadata = select_probability_stacked_portfolio(
        game,
        future_decision,
        result["future_forward_shadow_candidate"],
    )

    assert len(tickets) == 5
    assert metadata["structure"]["main_union_size"] == 30
    assert metadata["use"] == "future_forward_shadow_only"
    assert (
        metadata["candidate_hash"]
        == result["future_forward_shadow_candidate"]["candidate_hash"]
    )
    capsule = metadata["score_capsule"]
    validate_probability_score_capsule(
        capsule,
        game=game,
        target=future_decision["target"],
        candidate_hash=metadata["candidate_hash"],
        source_decision_hash=future_decision["decision_hash"],
    )
    assert len(capsule["main_probability_mass"]) == POOL[game]
    assert math.fsum(capsule["main_probability_mass"]) == pytest.approx(
        1.0,
        abs=1e-12,
    )


@pytest.mark.parametrize("game", [SUPER, LOTTO649])
def test_frozen_probability_score_has_correct_uniform_and_signal_direction(
    game,
):
    pool = POOL[game]
    actual = list(range(1, 7))
    focused = {
        number: (
            0.1
            if number in actual
            else 0.4 / (pool - len(actual))
        )
        for number in range(1, pool + 1)
    }
    special = (
        {
            number: 0.5 if number == 1 else 0.5 / 7
            for number in range(1, 9)
        }
        if game == SUPER
        else None
    )
    target = {"date": "2099-01-02", "period": 2}
    capsule = build_probability_score_capsule(
        game=game,
        target=target,
        candidate_hash="a" * 64,
        source_decision_hash="b" * 64,
        main_distribution=focused,
        special_distribution=special,
    )
    result = settle_probability_score_capsule(
        capsule,
        game=game,
        target=target,
        candidate_hash="a" * 64,
        source_decision_hash="b" * 64,
        actual_main=actual,
        actual_special=1 if game == SUPER else None,
        eligible=True,
    )

    verify_probability_score_result(result, game=game)
    assert result["main_regret_vs_uniform"] < 0
    assert result["main_verdict"] == "better_than_uniform"
    if game == SUPER:
        assert result["special_regret_vs_uniform"] < 0
        assert result["special_verdict"] == "better_than_uniform"
    else:
        assert result["special_verdict"] == "not_applicable"


def test_probability_score_capsule_rejects_post_registration_tamper():
    distribution = {number: 1 / 38 for number in range(1, 39)}
    target = {"date": "2099-01-02", "period": 2}
    capsule = build_probability_score_capsule(
        game=SUPER,
        target=target,
        candidate_hash="a" * 64,
        source_decision_hash="b" * 64,
        main_distribution=distribution,
        special_distribution={
            number: 1 / 8 for number in range(1, 9)
        },
    )
    capsule["main_probability_mass"][0] += 0.01

    with pytest.raises(ValueError, match="雜湊"):
        validate_probability_score_capsule(
            capsule,
            game=SUPER,
            target=target,
            candidate_hash="a" * 64,
            source_decision_hash="b" * 64,
        )


def test_candidate_rejects_tamper_and_same_day_target(smoke_study):
    _, result = smoke_study
    candidate = deepcopy(
        result["future_forward_shadow_candidate"]
    )
    candidate["models"][SUPER]["main_weights"][UNIFORM_EXPERT] += 0.1
    with pytest.raises(ValueError):
        validate_forward_candidate(candidate)

    candidate = deepcopy(
        result["future_forward_shadow_candidate"]
    )
    decision = deepcopy(_events(SUPER, 83)[-1]["decision"])
    decision["target"]["date"] = candidate["fitted_through"][SUPER]
    _rehash_decision(decision)
    with pytest.raises(ValueError, match="含目標期"):
        select_probability_stacked_portfolio(
            SUPER,
            decision,
            candidate,
        )


def test_write_results_is_exact_and_records_are_read_only(
    smoke_study,
):
    root, result = smoke_study
    before = tree_sha256(BASE / "records")
    output = write_results(result, root / "results")

    assert json.loads(output.read_text(encoding="utf-8")) == result
    assert tree_sha256(BASE / "records") == before
