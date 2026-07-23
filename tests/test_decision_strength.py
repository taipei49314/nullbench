"""號碼軟機率與 top-k 硬決策強度的計算及唯讀測試。"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from engine.agent_loop import canonical_hash
from engine.games import LOTTO649, SUPER
from research.decision_strength import (
    EXPERIMENT_ID,
    distribution_strength,
    run_decision_strength_audit,
    write_results,
)
from research.gates import tree_sha256


BASE = Path(__file__).parent.parent


def test_uniform_distribution_has_zero_label_lift():
    distribution = {number: 1 / 38 for number in range(1, 39)}
    strength = distribution_strength(
        distribution,
        selected_count=30,
        draws_per_event=6,
    )

    assert strength["selected_mass_lift"] == pytest.approx(0.0)
    assert strength["model_implied_expected_hit_lift"] == pytest.approx(
        0.0
    )
    assert strength["approx_pairs_for_80pct_power"] is None
    assert strength["boundary_tie_count"] == 38


def test_nonuniform_distribution_reports_positive_top_k_lift():
    raw = {
        number: 1.0 + (0.01 if number <= 30 else -0.0375)
        for number in range(1, 39)
    }
    total = sum(raw.values())
    distribution = {
        number: value / total for number, value in raw.items()
    }
    strength = distribution_strength(
        distribution,
        selected_count=30,
        draws_per_event=6,
    )

    assert strength["selected_numbers"] == list(range(1, 31))
    assert strength["selected_mass_lift"] > 0
    assert strength["model_implied_expected_hit_lift"] > 0
    assert strength["approx_pairs_for_80pct_power"] > 0


def test_distribution_contract_rejects_invalid_mass():
    with pytest.raises(ValueError):
        distribution_strength(
            {1: 0.4, 2: 0.4},
            selected_count=1,
            draws_per_event=1,
        )


@pytest.fixture(scope="module")
def formal_audit():
    return run_decision_strength_audit(BASE)


def test_formal_audit_quantifies_current_signal_without_promotion(
    formal_audit,
):
    assert formal_audit["experiment_id"] == EXPERIMENT_ID
    assert set(formal_audit["games"]) == {SUPER, LOTTO649}
    assert formal_audit["diagnosis"] == {
        "uniform_is_best_in_all_scored_dimensions": True,
        "model_lift_below_max_checkpoint_detectability": True,
        "top_k_amplification_present": True,
        "interpretation": formal_audit["diagnosis"]["interpretation"],
    }
    assert (
        formal_audit["decision"]["launch_additional_label_variant"]
        is False
    )
    assert (
        formal_audit["decision"]["change_existing_frozen_numbers"]
        is False
    )
    for row in formal_audit["games"].values():
        assert row["nonuniform_main_weight"] < 0.00001
        assert (
            row["main"]["model_implied_expected_hit_lift"]
            < row["main"]["checkpoint_detection"]["832"][
                "approx_minimum_detectable_mean_lift"
            ]
        )
        assert row["material_at_maximum_checkpoint"] is False


def test_audit_is_read_only_and_writes_exact_json(
    formal_audit,
    tmp_path,
):
    before = tree_sha256(BASE / "records")
    path = write_results(formal_audit, tmp_path)

    assert json.loads(path.read_text(encoding="utf-8")) == formal_audit
    assert tree_sha256(BASE / "records") == before


def test_write_rejects_tampered_audit_hash(formal_audit, tmp_path):
    tampered = deepcopy(formal_audit)
    tampered["decision"]["status"] = "promoted"

    with pytest.raises(ValueError, match="audit_hash"):
        write_results(tampered, tmp_path)


def test_audit_hash_covers_complete_payload(formal_audit):
    payload = {
        key: value
        for key, value in formal_audit.items()
        if key != "audit_hash"
    }
    assert formal_audit["audit_hash"] == canonical_hash(payload)


@pytest.mark.parametrize(
    "population,selected,draws",
    [(38, 30, 6), (49, 30, 6), (8, 5, 1)],
)
def test_closed_form_variance_matches_exact_enumeration(
    population,
    selected,
    draws,
):
    from decision_strength_verify import (
        _exact_hypergeometric_moments,
    )
    from research.decision_strength import (
        _hypergeometric_variance,
    )

    _, exact = _exact_hypergeometric_moments(
        population,
        selected,
        draws,
    )
    formula = _hypergeometric_variance(
        population=population,
        selected=selected,
        draws=draws,
    )
    assert formula == pytest.approx(exact, abs=1e-14)
