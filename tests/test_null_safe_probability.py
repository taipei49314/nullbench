"""公平零模型安全機率閘門的 likelihood、時間邊界與候選測試。"""
from __future__ import annotations

from copy import deepcopy
from itertools import combinations, islice
import json
import math
from pathlib import Path

import pytest

from engine.agent_loop import canonical_hash
from engine.games import LOTTO649, POOL, SUPER
from research.gates import tree_sha256
from research.max_coverage import (
    select_consensus_disjoint_portfolio,
)
from research.null_safe_probability import (
    ACTIVATION_E_THRESHOLD,
    E_PROCESS_PROTOCOL_ID,
    START_WEIGHT_NORMALIZER,
    advance_forward_candidate,
    build_forward_state_artifact,
    build_null_safe_score_capsule,
    forecast_null_safe_distributions,
    gate_is_active,
    initial_e_process_state,
    null_safe_distribution,
    restart_e_process_step,
    run_null_safe_probability,
    select_null_safe_portfolio,
    settle_null_safe_score_capsule,
    subset_log_likelihood_ratio_vs_uniform,
    validate_e_process_state,
    validate_forward_candidate,
    validate_forward_state_artifact,
    validate_null_safe_score_capsule,
    verify_null_safe_score_result,
    weighted_subset_log_probability,
    write_results,
)
from research.probability_stacking import _softmax


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


def _formal_candidates() -> tuple[dict, dict]:
    null_safe = json.loads(
        (
            BASE
            / "research"
            / "results"
            / "null_safe_probability.json"
        ).read_text(encoding="utf-8")
    )["future_forward_shadow_candidate"]
    stacking = json.loads(
        (
            BASE
            / "research"
            / "results"
            / "probability_stacking.json"
        ).read_text(encoding="utf-8")
    )["future_forward_shadow_candidate"]
    return null_safe, stacking


def _newer_stacking_candidate(
    stacking: dict,
    *,
    through: dict[str, str],
    nudge_weights: bool = False,
) -> dict:
    payload = deepcopy(stacking)
    payload.pop("candidate_hash")
    payload["fitted_through"] = deepcopy(through)
    if nudge_weights:
        main_log_weights = payload["models"][SUPER][
            "main_log_weights"
        ]
        main_log_weights["temporal_dependency"] += 0.125
        payload["models"][SUPER]["main_weights"] = _softmax(
            main_log_weights
        )
    return {
        **payload,
        "candidate_hash": canonical_hash(payload),
    }


def _score_settlement(
    prior_candidate: dict,
    *,
    game: str,
    target: dict,
) -> dict:
    decision = deepcopy(_events(game, 83)[-1]["decision"])
    decision["target"] = deepcopy(target)
    _rehash_decision(decision)
    forecast = forecast_null_safe_distributions(
        game,
        decision,
        prior_candidate,
    )
    model = prior_candidate["models"][game]
    capsule = build_null_safe_score_capsule(
        game=game,
        target=target,
        candidate_hash=prior_candidate["candidate_hash"],
        source_decision_hash=decision["decision_hash"],
        safe_main_distribution=forecast["main_distribution"],
        evidence_main_distribution=forecast[
            "main_mixture_distribution"
        ],
        main_e_process=model["main_e_process"],
        safe_special_distribution=forecast["special_distribution"],
        evidence_special_distribution=forecast[
            "special_mixture_distribution"
        ],
        special_e_process=(
            model["special_e_process"] if game == SUPER else None
        ),
    )
    score = settle_null_safe_score_capsule(
        capsule,
        game=game,
        target=target,
        candidate_hash=prior_candidate["candidate_hash"],
        source_decision_hash=decision["decision_hash"],
        actual_main=[1, 2, 3, 4, 5, 6],
        actual_special=1 if game == SUPER else None,
        eligible=True,
    )
    return {
        "game": game,
        "target": deepcopy(target),
        "registration_hash": "c" * 64,
        "proper_score": score,
    }


@pytest.fixture(scope="module")
def smoke_study(tmp_path_factory):
    root = tmp_path_factory.mktemp("null-safe-probability")
    ledgers = {}
    for game, source_path in SOURCES.items():
        target = root / f"{game}.jsonl"
        with source_path.open(encoding="utf-8") as source:
            target.write_text(
                "".join(islice(source, 82)),
                encoding="utf-8",
            )
        ledgers[game] = target
    result = run_null_safe_probability(
        ledgers,
        base=BASE,
        verify_ledgers=False,
    )
    return root, result


def test_weighted_subset_likelihood_is_normalized_and_uniform_is_zero_lr():
    distribution = {
        number: weight / 28
        for number, weight in enumerate(range(1, 8), 1)
    }
    probabilities = [
        math.exp(
            weighted_subset_log_probability(
                distribution,
                list(subset),
            )
        )
        for subset in combinations(range(1, 8), 6)
    ]

    assert math.fsum(probabilities) == pytest.approx(
        1.0,
        abs=1e-12,
    )
    uniform = {number: 1 / 7 for number in range(1, 8)}
    for subset in combinations(range(1, 8), 6):
        assert subset_log_likelihood_ratio_vs_uniform(
            uniform,
            list(subset),
        ) == pytest.approx(0.0, abs=1e-12)


def test_restart_e_process_matches_all_start_times_without_quadratic_state():
    state = initial_e_process_state()
    log_lrs = [math.log(1.2), math.log(0.8), math.log(1.5)]
    cumulative = []
    for index, log_lr in enumerate(log_lrs, 1):
        state = restart_e_process_step(state, log_lr)
        expected_active = math.fsum(
            START_WEIGHT_NORMALIZER
            / (start * start)
            * math.exp(math.fsum(log_lrs[start - 1 : index]))
            for start in range(1, index + 1)
        )
        allocated = math.fsum(
            START_WEIGHT_NORMALIZER / (start * start)
            for start in range(1, index + 1)
        )
        expected_e = expected_active + 1.0 - allocated
        cumulative.append(expected_e)
        assert math.exp(state["log_e_value"]) == pytest.approx(
            expected_e,
            rel=1e-12,
        )
        assert state["sequence"] == index
        assert set(state) == {
            "schema_version",
            "protocol_id",
            "sequence",
            "log_active_component_wealth",
            "allocated_start_weight",
            "log_e_value",
        }
        assert state["protocol_id"] == E_PROCESS_PROTOCOL_ID
    assert len(cumulative) == 3

    tampered = deepcopy(state)
    tampered["allocated_start_weight"] += 0.01
    with pytest.raises(ValueError, match="累積權重"):
        validate_e_process_state(tampered)


def test_restart_e_process_state_remains_valid_for_long_history():
    state = initial_e_process_state()
    for _ in range(5_000):
        state = restart_e_process_step(state, 0.0)

    validate_e_process_state(state)
    assert state["sequence"] == 5_000
    assert math.exp(state["log_e_value"]) == pytest.approx(
        1.0,
        abs=1e-10,
    )


def test_null_safe_distribution_uses_uniform_until_prior_evidence_crosses():
    mixture = {
        number: (
            0.2 if number == 1 else 0.8 / 7
        )
        for number in range(1, 9)
    }
    initial = initial_e_process_state()
    safe, active = null_safe_distribution(mixture, initial)

    assert active is False
    assert safe == {number: 1 / 8 for number in range(1, 9)}

    crossed = restart_e_process_step(
        initial,
        math.log(ACTIVATION_E_THRESHOLD * 2),
    )
    assert gate_is_active(crossed) is True
    safe, active = null_safe_distribution(mixture, crossed)
    assert active is True
    assert safe == mixture


def test_smoke_history_eliminates_unproven_regret_without_promoting(
    smoke_study,
):
    _, result = smoke_study

    assert result["data_quality"]["status"] == "pass"
    assert (
        result["conclusion"]["status"]
        == "candidate_ready_future_shadow"
    )
    assert (
        result["conclusion"]["historical_promotion_eligible"]
        is False
    )
    assert result["records_integrity"]["unchanged"] is True
    for game in (SUPER, LOTTO649):
        row = result["prequential_summary"][game]["main"]
        assert row["draws"] == 82
        assert row["uniform_log_loss"] == pytest.approx(
            math.log(math.comb(POOL[game], 6)),
            abs=1e-12,
        )
        assert row["existing_mixture_regret_vs_uniform"] == (
            pytest.approx(
                -row[
                    "cumulative_log_likelihood_ratio_vs_uniform"
                ]
                / row["draws"],
                abs=1e-12,
            )
        )
        assert row["null_safe_regret_vs_uniform"] == pytest.approx(
            0.0,
            abs=1e-12,
        )
        assert row["activation_periods"] == 0
        assert row["null_safe_improvement_vs_existing"] >= 0
    validate_forward_candidate(
        result["future_forward_shadow_candidate"]
    )


@pytest.mark.parametrize("game", [SUPER, LOTTO649])
def test_inactive_future_candidate_keeps_coverage_labels_and_uniform_score(
    smoke_study,
    game,
):
    _, result = smoke_study
    decision = _events(game, 83)[-1]["decision"]
    candidate = result["future_forward_shadow_candidate"]
    tickets, metadata = select_null_safe_portfolio(
        game,
        decision,
        candidate,
    )
    baseline, _ = select_consensus_disjoint_portfolio(
        game,
        decision,
    )

    assert [
        ticket["numbers"] for ticket in tickets
    ] == [ticket["numbers"] for ticket in baseline]
    assert [
        ticket["special"] for ticket in tickets
    ] == [ticket["special"] for ticket in baseline]
    assert metadata["main_gate_active"] is False
    assert metadata["ticket_label_source"] == "consensus_coverage"
    assert metadata["structure"]["main_union_size"] == 30
    assert metadata["structure"][
        "maximum_pairwise_main_overlap"
    ] == 0
    assert metadata["main_probability_mass"] == [
        1 / POOL[game]
    ] * POOL[game]
    assert len(metadata["support_evidence_hash"]) == 64


def test_candidate_rejects_tamper_and_same_day_target(smoke_study):
    _, result = smoke_study
    candidate = deepcopy(
        result["future_forward_shadow_candidate"]
    )
    candidate["models"][SUPER]["main_e_process"][
        "allocated_start_weight"
    ] += 0.01
    with pytest.raises(ValueError):
        validate_forward_candidate(candidate)

    candidate = deepcopy(
        result["future_forward_shadow_candidate"]
    )
    decision = deepcopy(_events(SUPER, 83)[-1]["decision"])
    decision["target"]["date"] = candidate["fitted_through"][SUPER]
    _rehash_decision(decision)
    with pytest.raises(ValueError, match="含目標期"):
        select_null_safe_portfolio(
            SUPER,
            decision,
            candidate,
        )


@pytest.mark.parametrize("game", [SUPER, LOTTO649])
def test_candidate_treats_serialized_weights_as_informational(game):
    candidate, _ = _formal_candidates()
    candidate = deepcopy(candidate)
    model = candidate["models"][game]
    model["main_weights"] = {
        expert: 0.0 for expert in model["main_weights"]
    }
    payload = {
        key: value
        for key, value in candidate.items()
        if key != "candidate_hash"
    }
    candidate["candidate_hash"] = canonical_hash(payload)

    assert validate_forward_candidate(candidate) == candidate


def test_candidate_rejects_invalid_main_log_weights():
    candidate, _ = _formal_candidates()
    candidate = deepcopy(candidate)
    expert = next(
        iter(candidate["models"][SUPER]["main_log_weights"])
    )
    candidate["models"][SUPER]["main_log_weights"][expert] = float(
        "nan"
    )

    with pytest.raises(ValueError, match="null-safe candidate 主號模型不符"):
        validate_forward_candidate(candidate)


@pytest.mark.parametrize("game", [SUPER, LOTTO649])
def test_forward_score_capsule_separates_safe_forecast_from_evidence_update(
    game,
):
    domain = POOL[game]
    evidence_main = {
        number: (
            2.0 / (domain + 1)
            if number == 1
            else 1.0 / (domain + 1)
        )
        for number in range(1, domain + 1)
    }
    main_state = initial_e_process_state()
    safe_main, active = null_safe_distribution(
        evidence_main,
        main_state,
    )
    if game == SUPER:
        evidence_special = {
            number: (2.0 / 9 if number == 1 else 1.0 / 9)
            for number in range(1, 9)
        }
        special_state = initial_e_process_state()
        safe_special, special_active = null_safe_distribution(
            evidence_special,
            special_state,
        )
    else:
        evidence_special = None
        special_state = None
        safe_special = None
        special_active = False
    capsule = build_null_safe_score_capsule(
        game=game,
        target={"date": "2099-01-01", "period": 1},
        candidate_hash="a" * 64,
        source_decision_hash="b" * 64,
        safe_main_distribution=safe_main,
        evidence_main_distribution=evidence_main,
        main_e_process=main_state,
        safe_special_distribution=safe_special,
        evidence_special_distribution=evidence_special,
        special_e_process=special_state,
    )

    assert active is False
    assert special_active is False
    assert capsule["main_gate_active"] is False
    assert capsule["safe_main_probability_mass"] == [
        1 / domain
    ] * domain
    assert (
        capsule["safe_main_probability_mass"]
        != capsule["evidence_main_probability_mass"]
    )
    validate_null_safe_score_capsule(
        capsule,
        game=game,
        target=capsule["target"],
        candidate_hash="a" * 64,
        source_decision_hash="b" * 64,
    )
    result = settle_null_safe_score_capsule(
        capsule,
        game=game,
        target=capsule["target"],
        candidate_hash="a" * 64,
        source_decision_hash="b" * 64,
        actual_main=[1, 2, 3, 4, 5, 6],
        actual_special=8 if game == SUPER else None,
        eligible=True,
    )

    assert result["main_safe_verdict"] == "tie_uniform"
    assert result["main_safe_regret_vs_uniform"] == pytest.approx(
        0.0,
        abs=1e-12,
    )
    assert result["main_prior_e_process"]["sequence"] == 0
    assert result["main_updated_e_process"]["sequence"] == 1
    assert math.isfinite(
        result["main_evidence_log_likelihood_ratio_vs_uniform"]
    )
    if game == SUPER:
        assert result["special_safe_verdict"] == "tie_uniform"
        assert result["special_updated_e_process"]["sequence"] == 1
    else:
        assert result["special_safe_verdict"] == "not_applicable"
    verify_null_safe_score_result(result, game=game)

    tampered = deepcopy(capsule)
    tampered["main_prior_e_process"]["sequence"] = 1
    tampered["capsule_hash"] = canonical_hash(
        {
            key: value
            for key, value in tampered.items()
            if key != "capsule_hash"
        }
    )
    with pytest.raises(ValueError):
        validate_null_safe_score_capsule(
            tampered,
            game=game,
            target=capsule["target"],
            candidate_hash="a" * 64,
            source_decision_hash="b" * 64,
        )


def test_forward_score_capsule_binds_safe_distribution_to_prior_gate():
    evidence = {
        number: (2.0 / 39 if number == 1 else 1.0 / 39)
        for number in range(1, 39)
    }
    crossed = restart_e_process_step(
        initial_e_process_state(),
        math.log(ACTIVATION_E_THRESHOLD * 2),
    )

    with pytest.raises(ValueError, match="prior gate"):
        build_null_safe_score_capsule(
            game=SUPER,
            target={"date": "2099-01-01", "period": 1},
            candidate_hash="a" * 64,
            source_decision_hash="b" * 64,
            safe_main_distribution={
                number: 1 / 38 for number in range(1, 39)
            },
            evidence_main_distribution=evidence,
            main_e_process=crossed,
            safe_special_distribution={
                number: 1 / 8 for number in range(1, 9)
            },
            evidence_special_distribution={
                number: 1 / 8 for number in range(1, 9)
            },
            special_e_process=initial_e_process_state(),
        )


def test_reveal_transition_matches_next_full_replay_state(
    smoke_study,
    tmp_path,
):
    _, result_82 = smoke_study
    candidate_82 = result_82["future_forward_shadow_candidate"]
    ledgers_83 = {}
    event_83 = {}
    for game, source_path in SOURCES.items():
        lines = source_path.read_text(encoding="utf-8").splitlines(
            keepends=True
        )[:83]
        target = tmp_path / f"{game}.jsonl"
        target.write_text("".join(lines), encoding="utf-8")
        ledgers_83[game] = target
        event_83[game] = json.loads(lines[-1])

    settled_scores = {}
    for game in (SUPER, LOTTO649):
        decision = event_83[game]["decision"]
        reveal = event_83[game]["reveal"]
        forecast = forecast_null_safe_distributions(
            game,
            decision,
            candidate_82,
        )
        model = candidate_82["models"][game]
        capsule = build_null_safe_score_capsule(
            game=game,
            target=decision["target"],
            candidate_hash=candidate_82["candidate_hash"],
            source_decision_hash=decision["decision_hash"],
            safe_main_distribution=forecast["main_distribution"],
            evidence_main_distribution=forecast[
                "main_mixture_distribution"
            ],
            main_e_process=model["main_e_process"],
            safe_special_distribution=forecast[
                "special_distribution"
            ],
            evidence_special_distribution=forecast[
                "special_mixture_distribution"
            ],
            special_e_process=(
                model["special_e_process"]
                if game == SUPER
                else None
            ),
        )
        settled_scores[game] = settle_null_safe_score_capsule(
            capsule,
            game=game,
            target=decision["target"],
            candidate_hash=candidate_82["candidate_hash"],
            source_decision_hash=decision["decision_hash"],
            actual_main=[int(number) for number in reveal["numbers"]],
            actual_special=(
                int(reveal["special"]) if game == SUPER else None
            ),
            eligible=True,
        )

    result_83 = run_null_safe_probability(
        ledgers_83,
        base=BASE,
        verify_ledgers=False,
    )
    for game in (SUPER, LOTTO649):
        assert result_83["final_models"][game][
            "main_e_process"
        ] == settled_scores[game]["main_updated_e_process"]
        if game == SUPER:
            assert result_83["final_models"][game][
                "special_e_process"
            ] == settled_scores[game][
                "special_updated_e_process"
            ]


def test_forward_state_refreshes_stacking_without_backfilling_v6_gap():
    prior, stacking = _formal_candidates()
    through = {
        SUPER: "2099-01-01",
        LOTTO649: "2099-01-02",
    }
    newer = _newer_stacking_candidate(
        stacking,
        through=through,
        nudge_weights=True,
    )

    advanced, applied = advance_forward_candidate(
        prior,
        newer,
        [],
    )

    assert applied == []
    assert advanced["fitted_through"] == through
    assert (
        advanced["models"][SUPER]["main_log_weights"]
        == newer["models"][SUPER]["main_log_weights"]
    )
    assert (
        advanced["models"][SUPER]["main_log_weights"]
        != prior["models"][SUPER]["main_log_weights"]
    )
    for game in (SUPER, LOTTO649):
        assert (
            advanced["models"][game]["main_e_process"]
            == prior["models"][game]["main_e_process"]
        )
        assert (
            advanced["models"][game]["main_gate_active"]
            == prior["models"][game]["main_gate_active"]
        )
    assert (
        advanced["models"][SUPER]["special_e_process"]
        == prior["models"][SUPER]["special_e_process"]
    )
    assert (
        advanced["models"][SUPER]["special_gate_active"]
        == prior["models"][SUPER]["special_gate_active"]
    )


def test_registered_v7_score_advances_once_and_is_idempotent():
    prior, stacking = _formal_candidates()
    target = {"date": "2099-01-01", "period": 990001}
    newer = _newer_stacking_candidate(
        stacking,
        through={
            SUPER: target["date"],
            LOTTO649: prior["fitted_through"][LOTTO649],
        },
    )
    settlement = _score_settlement(
        prior,
        game=SUPER,
        target=target,
    )

    advanced, applied = advance_forward_candidate(
        prior,
        newer,
        [settlement],
    )

    assert len(applied) == 1
    assert applied[0]["registration_hash"] == "c" * 64
    assert (
        advanced["models"][SUPER]["main_e_process"]
        == settlement["proper_score"]["main_updated_e_process"]
    )
    assert (
        advanced["models"][SUPER]["special_e_process"]
        == settlement["proper_score"]["special_updated_e_process"]
    )
    assert (
        advanced["models"][SUPER]["main_e_process"]["sequence"]
        == prior["models"][SUPER]["main_e_process"]["sequence"] + 1
    )

    repeated, repeated_applied = advance_forward_candidate(
        advanced,
        newer,
        [settlement],
    )
    assert repeated_applied == []
    assert repeated == advanced

    rebuilt = build_forward_state_artifact(
        prior,
        newer,
        [settlement],
    )
    assert rebuilt == build_forward_state_artifact(
        prior,
        newer,
        [settlement],
    )
    assert (
        rebuilt["future_forward_shadow_candidate"]
        == advanced
    )


def test_forward_state_rejects_discontinuous_registered_score():
    prior, stacking = _formal_candidates()
    target = {"date": "2099-01-01", "period": 990001}
    newer = _newer_stacking_candidate(
        stacking,
        through={
            SUPER: target["date"],
            LOTTO649: prior["fitted_through"][LOTTO649],
        },
    )
    settlement = _score_settlement(
        prior,
        game=SUPER,
        target=target,
    )
    score = settlement["proper_score"]
    score["main_prior_e_process"] = initial_e_process_state()
    score["main_updated_e_process"] = restart_e_process_step(
        score["main_prior_e_process"],
        score[
            "main_evidence_log_likelihood_ratio_vs_uniform"
        ],
    )
    score["main_next_gate_active"] = gate_is_active(
        score["main_updated_e_process"]
    )

    with pytest.raises(ValueError, match="prior state"):
        advance_forward_candidate(prior, newer, [settlement])


def test_forward_state_artifact_validates_and_rejects_tamper():
    prior, stacking = _formal_candidates()
    artifact = build_forward_state_artifact(prior, stacking, [])

    assert validate_forward_state_artifact(artifact) == artifact
    assert artifact["historical_backfill_allowed"] is False
    assert artifact["applied_transitions"] == []

    tampered = deepcopy(artifact)
    tampered["historical_backfill_allowed"] = True
    with pytest.raises(ValueError):
        validate_forward_state_artifact(tampered)

    tampered = deepcopy(artifact)
    tampered["future_forward_shadow_candidate"]["models"][SUPER][
        "main_e_process"
    ]["sequence"] += 1
    with pytest.raises(ValueError):
        validate_forward_state_artifact(tampered)


def test_write_results_is_exact_and_records_are_read_only(
    smoke_study,
):
    root, result = smoke_study
    before = tree_sha256(BASE / "records")
    output = write_results(result, root / "results")

    assert json.loads(output.read_text(encoding="utf-8")) == result
    assert tree_sha256(BASE / "records") == before
