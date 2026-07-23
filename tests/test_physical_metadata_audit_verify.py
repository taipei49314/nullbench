from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from engine.agent_loop import canonical_hash
from physical_metadata_audit_verify import (
    FORMAL_RESULT,
    verify_formal_result,
)
from research.physical_metadata_audit import (
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


def test_rehashed_source_evidence_tamper_fails_closed():
    result = deepcopy(_formal())
    result["source_evidence"]["official_faq"]["facts"][0] = (
        "betting cutoff is 19:00"
    )
    evidence = dict(result["source_evidence"])
    evidence.pop("evidence_hash", None)
    result["source_evidence"]["evidence_hash"] = canonical_hash(evidence)
    _rehash(result)
    with pytest.raises(RuntimeError, match="artifact_contract"):
        verify_formal_result(result, verify_live_sources=False)


def test_rehashed_raw_count_tamper_is_caught_live():
    result = deepcopy(_formal())
    result["raw_schema_audit"]["games"]["super"]["rows"] += 1
    result["raw_schema_audit"]["rows_total"] += 1
    _rehash(result)
    with pytest.raises(RuntimeError):
        verify_formal_result(result, verify_live_sources=True)


def test_rehashed_observation_eligibility_tamper_fails_closed():
    result = deepcopy(_formal())
    observation = result["observation_audit"]["observations"][0]
    observation["eligible_for_forecast"] = True
    observation["eligibility_reason"] = "eligible"
    result["observation_audit"]["pre_cutoff_eligible_observations"] = 1
    result["observation_audit"]["observation_hash"] = canonical_hash(
        result["observation_audit"]["observations"]
    )
    _rehash(result)
    with pytest.raises(RuntimeError, match="artifact_contract"):
        verify_formal_result(result, verify_live_sources=False)


def test_protocol_file_hash_tamper_fails_closed():
    result = deepcopy(_formal())
    result["protocol"]["protocol_file_sha256"] = "0" * 64
    _rehash(result)
    with pytest.raises(RuntimeError, match="protocol_file"):
        verify_formal_result(result, verify_live_sources=False)


@pytest.mark.parametrize(
    "script",
    ["physical_metadata_audit.py", "physical_metadata_audit_verify.py"],
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
