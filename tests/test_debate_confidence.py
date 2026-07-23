"""辯論逐期信心研究的時間邊界、精確檢定與唯讀測試。"""
from __future__ import annotations

from itertools import islice
import json
import math
from pathlib import Path

import pytest

from engine.games import LOTTO649, POOL, SUPER
from research.debate_confidence import (
    DebateConfidenceConfig,
    _interaction_upper_tail,
    build_confidence_features,
    confidence_block_bootstrap_ci,
    fit_confidence_model,
    run_debate_confidence_study,
    score_confidence,
    sequential_safe_evidence,
    write_results,
)
from research.gates import tree_sha256


BASE = Path(__file__).parent.parent
SOURCES = {
    SUPER: BASE / "simulation" / "results" / "super.jsonl",
    LOTTO649: BASE / "simulation" / "results" / "lotto649.jsonl",
}


def _first_event(game: str) -> dict:
    with SOURCES[game].open(encoding="utf-8") as handle:
        return json.loads(next(handle))


@pytest.mark.parametrize("game", [SUPER, LOTTO649])
def test_feature_builder_is_pre_reveal_complete_and_deterministic(game):
    event = _first_event(game)
    first, ranking, quality = build_confidence_features(
        game, event["decision"]
    )
    second, second_ranking, _ = build_confidence_features(
        game, event["decision"]
    )

    assert first == second
    assert ranking == second_ranking
    assert sorted(ranking) == list(range(1, POOL[game] + 1))
    assert quality["proposals"] == 15
    assert quality["candidate_scores"] == 15
    assert quality["critiques"] == 60
    assert quality["unique_critique_pairs"] == 60
    assert quality["proposal_appearances_total"] == 90
    assert all(math.isfinite(value) for value in first.values())


@pytest.mark.parametrize("game", [SUPER, LOTTO649])
def test_future_reveal_tampering_cannot_change_confidence_features(game):
    event = _first_event(game)
    before = build_confidence_features(game, event["decision"])
    event["reveal"]["numbers"] = list(
        range(POOL[game] - 5, POOL[game] + 1)
    )
    after = build_confidence_features(game, event["decision"])

    assert after == before


def test_feature_builder_rejects_incomplete_cross_agent_critiques():
    event = _first_event(SUPER)
    event["decision"]["critiques"].pop()

    with pytest.raises(ValueError, match="60 筆"):
        build_confidence_features(SUPER, event["decision"])


def test_confidence_model_is_fitted_only_from_supplied_development():
    rows = [
        {
            "support_margin": float(index),
            "mean_candidate_disagreement": float(index % 3),
        }
        for index in range(1, 11)
    ]
    first = fit_confidence_model(rows)
    unrelated_future = [
        {
            "support_margin": 1_000_000.0,
            "mean_candidate_disagreement": -1_000_000.0,
        }
    ]
    second = fit_confidence_model(rows)

    assert first == second
    assert unrelated_future
    low_score, low_group = score_confidence(rows[0], first)
    high_score, high_group = score_confidence(rows[-1], first)
    assert low_score < high_score
    assert low_group in {"low", "middle"}
    assert high_group in {"high", "middle"}


def test_exact_interaction_matches_manual_one_draw_enumeration():
    pool = 10
    selected = 3
    high_periods = low_periods = 1
    observed_high = 2
    observed_low = 0

    actual = _interaction_upper_tail(
        pool=pool,
        selected=selected,
        high_periods=high_periods,
        low_periods=low_periods,
        high_observed=observed_high,
        low_observed=observed_low,
    )
    from research.debate_rank_calibration import (
        _single_hypergeometric,
    )

    distribution = _single_hypergeometric(pool, selected)
    expected = math.fsum(
        left_probability * right_probability
        for left_hits, left_probability in enumerate(distribution)
        for right_hits, right_probability in enumerate(distribution)
        if left_hits - right_hits >= 2
    )
    assert actual == pytest.approx(expected)


def test_confidence_block_bootstrap_is_deterministic():
    rows = [
        {
            "confidence_group": (
                "high"
                if index % 3 == 0
                else "low"
                if index % 3 == 1
                else "middle"
            ),
            "top_10_hits": float(index % 4),
        }
        for index in range(60)
    ]
    kwargs = {
        "metric": "top_10_hits",
        "expected": 1.5,
        "samples": 100,
        "block": 3,
        "seed": "fixed-seed",
    }

    assert confidence_block_bootstrap_ci(
        rows, **kwargs
    ) == confidence_block_bootstrap_ci(rows, **kwargs)


@pytest.mark.parametrize(
    "contrast", ["high_vs_null", "high_minus_low"]
)
def test_sequential_safe_e_value_stays_unit_mean_under_adaptive_groups(
    contrast,
):
    from research.debate_rank_calibration import (
        _single_hypergeometric,
    )

    distribution = _single_hypergeometric(POOL[SUPER], 10)
    expected_e = 0.0
    for first_hits, first_probability in enumerate(distribution):
        second_group = "high" if first_hits >= 2 else "low"
        for second_hits, second_probability in enumerate(
            distribution
        ):
            evidence = sequential_safe_evidence(
                SUPER,
                10,
                [
                    {
                        "confidence_group": "high",
                        "top_10_hits": float(first_hits),
                    },
                    {
                        "confidence_group": second_group,
                        "top_10_hits": float(second_hits),
                    },
                ],
                metric="top_10_hits",
                contrast=contrast,
            )
            expected_e += (
                first_probability
                * second_probability
                * evidence["mixture_e_value"]
            )
    assert expected_e == pytest.approx(1.0)


def test_smoke_study_profiles_splits_and_preserves_records(tmp_path):
    ledgers = {}
    for game, source_path in SOURCES.items():
        ledger = tmp_path / f"{game}.jsonl"
        with source_path.open(encoding="utf-8") as source:
            ledger.write_text(
                "".join(islice(source, 82)),
                encoding="utf-8",
            )
        ledgers[game] = ledger

    before = tree_sha256(BASE / "records")
    result = run_debate_confidence_study(
        ledgers,
        base=BASE,
        config=DebateConfidenceConfig(
            bootstrap_samples=100,
            bootstrap_block=3,
            minimum_holdout_group_share=0.01,
            maximum_holdout_mean_drift=10,
        ),
        verify_ledgers=False,
    )
    output = write_results(result, tmp_path / "results")

    assert output.exists()
    assert set(result["games"]) == {SUPER, LOTTO649}
    assert len(result["protocol"]["holm_family"]) == 8
    for game in (SUPER, LOTTO649):
        quality = result["games"][game]["data_quality"]
        assert quality["status"] == "pass"
        assert quality["profile"]["draws"] == 82
        assert quality["split_profile"][
            "development_draws"
        ] == 15
        assert quality["split_profile"]["holdout_draws"] == 7
        assert quality["feature_rows"] == 22
        assert quality["ranking_size_min"] == POOL[game]
        assert quality["ranking_size_max"] == POOL[game]
        assert quality["critiques_min"] == 60
        assert set(result["games"][game]["holdout"]) == {
            "top_10_hits",
            "top_30_hits",
        }
    assert result["records_integrity"] == {
        "before_sha256": before,
        "after_sha256": before,
        "unchanged": True,
    }
    assert json.loads(output.read_text(encoding="utf-8")) == result


def test_formal_result_passes_exact_acceptance_contract():
    from debate_confidence_verify import verify_formal_result

    result = json.loads(
        (
            BASE
            / "research"
            / "results"
            / "debate_confidence.json"
        ).read_text(encoding="utf-8")
    )

    verify_formal_result(result)
