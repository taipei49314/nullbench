"""時間 stacking formal verifier 的接受與 fail-closed 測試。"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from engine.agent_loop import canonical_hash
from engine.games import SUPER
from temporal_stacking_diagnostic_verify import (
    verify_formal_result,
)


BASE = Path(__file__).parent.parent
FORMAL = (
    BASE
    / "research"
    / "results"
    / "temporal_stacking_diagnostic.json"
)


def _result() -> dict:
    return json.loads(FORMAL.read_text(encoding="utf-8"))


def _rehash(result: dict) -> None:
    result["audit_hash"] = canonical_hash(
        {
            key: value
            for key, value in result.items()
            if key != "audit_hash"
        }
    )


def test_formal_verifier_accepts_current_artifact():
    verify_formal_result(_result())


def test_formal_verifier_rejects_protocol_file_mismatch():
    result = _result()
    result["protocol"]["protocol_file_sha256"] = "0" * 64
    _rehash(result)
    with pytest.raises(RuntimeError, match="protocol_file"):
        verify_formal_result(result)


def test_formal_verifier_rejects_source_mismatch():
    result = _result()
    result["data_quality"]["ledger_verification"][SUPER][
        "ledger_sha256"
    ] = "0" * 64
    _rehash(result)
    with pytest.raises(RuntimeError, match="source_super"):
        verify_formal_result(result)


def test_formal_verifier_rejects_decision_tamper():
    result = deepcopy(_result())
    result["conclusion"]["status"] = (
        "future_challenger_supported_for_preregistration"
    )
    _rehash(result)
    with pytest.raises(RuntimeError):
        verify_formal_result(result)
