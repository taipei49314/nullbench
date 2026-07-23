from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from engine.agent_loop import canonical_hash
from lag_overlap_signal_verify import (
    FORMAL_RESULT,
    verify_formal_result,
)
from research.lag_overlap_signal import (
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
    row["raw_mean_regret_nats"] = 0.123
    row["raw_mean_information_gain_nats"] = -0.123
    row["raw_geometric_probability_ratio_vs_uniform"] = (
        0.884263662560821
    )
    _rehash(result)
    with pytest.raises(RuntimeError, match="live_recompute"):
        verify_formal_result(result, verify_live_sources=True)


def test_rehashed_raw_source_hash_tamper_is_caught_live():
    result = deepcopy(_formal())
    fake_hash = "0" * 64
    result["data_quality"]["games"]["super"][
        "raw_tree_sha256"
    ] = fake_hash
    result["data_quality"]["raw_snapshot_hashes"][
        "super"
    ] = fake_hash
    hashes = result["data_quality"]["raw_snapshot_hashes"]
    result["data_quality"]["combined_raw_snapshot_hash"] = (
        canonical_hash(hashes)
    )
    _rehash(result)
    with pytest.raises(RuntimeError, match="live_recompute"):
        verify_formal_result(result, verify_live_sources=True)


def test_gate_timing_tamper_fails_closed():
    result = deepcopy(_formal())
    row = result["diagnostics"]["super"]
    row["gate_activation_count"] = 1
    _rehash(result)
    with pytest.raises(RuntimeError):
        verify_formal_result(result, verify_live_sources=False)


def test_overlap_count_tamper_fails_closed():
    result = deepcopy(_formal())
    row = result["diagnostics"]["lotto649"]
    row["final_overlap_counts"][0] += 1
    _rehash(result)
    with pytest.raises(RuntimeError):
        verify_formal_result(result, verify_live_sources=False)


def test_protocol_file_hash_tamper_fails_closed():
    result = deepcopy(_formal())
    result["protocol"]["protocol_file_sha256"] = "0" * 64
    _rehash(result)
    with pytest.raises(RuntimeError, match="protocol_file"):
        verify_formal_result(result, verify_live_sources=False)


def test_all_games_retain_null_safe():
    result = _formal()
    assert set(result["diagnostics"]) == set(GAMES)
    for row in result["diagnostics"].values():
        assert row["raw_mean_regret_nats"] > 0
        assert row["raw_bootstrap_95_low"] > 0
        assert row["safe_mean_regret_nats"] == 0
        assert row["gate_activation_count"] == 0
        assert row["final_gate_active"] is False


@pytest.mark.parametrize(
    "script",
    ["lag_overlap_signal.py", "lag_overlap_signal_verify.py"],
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
