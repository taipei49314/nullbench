from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from cross_game_overlap_signal_verify import (
    FORMAL_RESULT,
    verify_formal_result,
)
from engine.agent_loop import canonical_hash
from research.cross_game_overlap_signal import (
    GAMES,
    PROTOCOL_FILE,
    validate_result,
)


ROOT = Path(__file__).resolve().parents[1]


def _formal() -> dict:
    return json.loads(FORMAL_RESULT.read_text(encoding="utf-8"))


def _rehash(result: dict) -> None:
    payload = dict(result)
    payload.pop("audit_hash", None)
    result["audit_hash"] = canonical_hash(payload)


def test_formal_artifact_contract_and_decision():
    result = _formal()
    assert validate_result(result) == result
    verify_formal_result(result, verify_live_sources=False)


def test_formal_artifact_matches_live_recompute():
    verify_formal_result(_formal(), verify_live_sources=True)


def test_rehashed_regret_tamper_is_caught_by_live_recompute():
    result = deepcopy(_formal())
    row = result["diagnostics"]["super"]
    row["mean_regret_nats"] = 0.123
    row["mean_information_gain_nats"] = -0.123
    row["geometric_probability_ratio_vs_uniform"] = (
        0.884263662560821
    )
    row["final_log_e_value"] = -0.123 * row["draws"]
    _rehash(result)
    with pytest.raises(RuntimeError, match="live_recompute"):
        verify_formal_result(result, verify_live_sources=True)


def test_pair_mapping_tamper_fails_closed():
    result = deepcopy(_formal())
    result["data_quality"]["pairing_profiles"]["lotto649"][
        "mapping_hash"
    ] = "0" * 64
    result["diagnostics"]["lotto649"]["pairing_profile"][
        "mapping_hash"
    ] = "0" * 64
    _rehash(result)
    with pytest.raises(RuntimeError, match="live_recompute"):
        verify_formal_result(result, verify_live_sources=True)


def test_same_date_or_state_tamper_fails_closed():
    result = deepcopy(_formal())
    result["diagnostics"]["super"]["pairing_profile"][
        "same_date_source_ignored"
    ] = 0
    result["diagnostics"]["super"][
        "final_overlap_counts_by_m"
    ]["6"][0] += 1
    _rehash(result)
    with pytest.raises(RuntimeError):
        verify_formal_result(result, verify_live_sources=False)


def test_false_promotion_fails_closed():
    result = deepcopy(_formal())
    result["conclusion"]["future_challenger_design_allowed"] = True
    result["conclusion"]["selected_future_challenger"] = (
        "cross_game_overlap_dirichlet_null_1"
    )
    result["conclusion"]["probability_decision"] = (
        "cross_game_overlap_dirichlet_null_1"
    )
    _rehash(result)
    with pytest.raises(RuntimeError):
        verify_formal_result(result, verify_live_sources=False)


def test_protocol_file_hash_tamper_fails_closed():
    result = deepcopy(_formal())
    result["protocol"]["protocol_file_sha256"] = "0" * 64
    _rehash(result)
    with pytest.raises(RuntimeError, match="protocol_file"):
        verify_formal_result(result, verify_live_sources=False)


def test_all_games_have_fixed_family_and_no_historical_promotion():
    result = _formal()
    assert set(result["diagnostics"]) == set(GAMES)
    assert result["conclusion"]["historical_promotion_eligible"] is False
    assert result["conclusion"]["watcher_integration_allowed"] is False
    assert result["conclusion"]["frontier_v4_inclusion_required"] is True


@pytest.mark.parametrize(
    "script",
    [
        "cross_game_overlap_signal.py",
        "cross_game_overlap_signal_verify.py",
    ],
)
def test_cli_help_survives_cp1252_parent(script):
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "cp1252"
    completed = subprocess.run(
        [sys.executable, "-B", script, "--help"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0
    assert "UnicodeEncodeError" not in completed.stderr.decode(
        "utf-8",
        errors="replace",
    )
    assert (ROOT / PROTOCOL_FILE).exists()
