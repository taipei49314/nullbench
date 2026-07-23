from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from engine.games import LOTTO649, SUPER
from research.physical_metadata_audit import (
    FIXED_OBSERVATION_INPUTS,
    classify_observation,
    match_physical_paths,
    nested_key_paths,
    run_physical_metadata_audit,
    scan_raw_metadata,
)


ROOT = Path(__file__).resolve().parents[1]


def _sample() -> dict:
    return deepcopy(FIXED_OBSERVATION_INPUTS[0])


def test_nested_schema_scan_finds_machine_and_ball_set_aliases():
    paths = nested_key_paths(
        {
            "period": 1,
            "mechanism": {
                "drawMachineId": "2",
                "ball_set": {"id": "A"},
            },
            "events": [{"anomalyFlag": False}],
        }
    )
    matches = match_physical_paths(paths)
    assert matches["machine"] == ["mechanism.drawMachineId"]
    assert matches["ball_set"] == ["mechanism.ball_set"]
    assert matches["anomaly"] == ["events[].anomalyFlag"]


def test_fixed_sample_is_after_cutoff_and_fails_closed():
    observed = classify_observation(_sample())
    assert observed["machine_id"] == "2"
    assert observed["ball_set_id"] is None
    assert observed["eligible_for_forecast"] is False
    assert (
        observed["eligibility_reason"]
        == "published_after_registration_cutoff"
    )


def test_exact_cutoff_is_eligible_with_complete_verified_assignment():
    sample = _sample()
    sample["public_observed_at"] = sample["registration_cutoff_at"]
    sample["ball_set_id"] = "A"
    observed = classify_observation(sample)
    assert observed["eligible_for_forecast"] is True
    assert observed["eligibility_reason"] == "eligible"


def test_missing_ball_set_before_cutoff_remains_ineligible():
    sample = _sample()
    sample["public_observed_at"] = "2026-07-17T19:59:59+08:00"
    observed = classify_observation(sample)
    assert observed["eligible_for_forecast"] is False
    assert observed["eligibility_reason"] == "machine_or_ball_set_missing"


@pytest.mark.parametrize(
    "field,value",
    [
        ("public_observed_at", "2026-07-17T19:59:59"),
        ("registration_cutoff_at", None),
    ],
)
def test_missing_or_naive_timestamp_is_rejected(field, value):
    sample = _sample()
    sample[field] = value
    with pytest.raises(ValueError):
        classify_observation(sample)


def test_special_bonus_scope_cannot_become_forecast_feature():
    sample = _sample()
    sample["public_observed_at"] = "2026-07-17T19:59:00+08:00"
    sample["ball_set_id"] = "A"
    sample["source_scope"] = "special_bonus"
    observed = classify_observation(sample)
    assert observed["eligible_for_forecast"] is False
    assert (
        observed["eligibility_reason"]
        == "source_scope_not_target_main_draw"
    )


def test_live_raw_scan_has_complete_identity_and_no_physical_fields():
    audit = scan_raw_metadata(base=ROOT)
    assert audit["status"] == "pass"
    assert audit["files_total"] == 494
    assert audit["rows_total"] == 4082
    assert audit["physical_metadata_rows_total"] == 0
    assert audit["physical_metadata_coverage_rate"] == 0
    for game in (SUPER, LOTTO649):
        row = audit["games"][game]
        assert row["rows"] == row["unique_periods"]
        assert row["rows"] == row["unique_dates"]
        assert row["physical_field_match_count"] == 0


def test_full_audit_retains_uniform_null_safe():
    result = run_physical_metadata_audit(base=ROOT)
    assert result["conclusion"]["status"] == (
        "physical_metadata_unavailable_pre_cutoff"
    )
    assert (
        result["conclusion"]["number_probability_model_allowed"]
        is False
    )
    assert (
        result["conclusion"]["selected_probability_protocol"]
        == "uniform_null_safe"
    )
    assert result["records_integrity"]["unchanged"] is True
