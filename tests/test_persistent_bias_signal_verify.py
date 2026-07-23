"""持續球號偏差 formal artifact 的接受與 fail-closed 測試。"""
from __future__ import annotations

from copy import deepcopy
import io
import json
from pathlib import Path

import pytest

import persistent_bias_signal_verify as verifier
from engine.agent_loop import canonical_hash
from engine.games import SUPER
from research.persistent_bias_signal import validate_result


BASE = Path(__file__).parent.parent
FORMAL = (
    BASE
    / "research"
    / "results"
    / "persistent_bias_signal.json"
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


def test_formal_result_validates():
    validate_result(_result())
    verifier.verify_formal_result(
        _result(),
        verify_live_sources=False,
    )


def test_live_sources_recompute_exact_formal_result():
    verifier.verify_formal_result(
        _result(),
        verify_live_sources=True,
    )


def test_rejects_regret_tamper_even_with_rehash():
    result = _result()
    result["diagnostics"][SUPER]["mean_regret_nats"] += 0.0001
    result["diagnostics"][SUPER][
        "mean_information_gain_nats"
    ] = -result["diagnostics"][SUPER]["mean_regret_nats"]
    result["diagnostics"][SUPER]["final_log_e_value"] = (
        -result["diagnostics"][SUPER]["mean_regret_nats"]
        * result["diagnostics"][SUPER]["draws"]
    )
    _rehash(result)
    with pytest.raises(RuntimeError):
        verifier.verify_formal_result(
            result,
            verify_live_sources=True,
        )


def test_rejects_raw_hash_tamper():
    result = _result()
    result["data_quality"]["games"][SUPER][
        "raw_tree_sha256"
    ] = "0" * 64
    _rehash(result)
    with pytest.raises((ValueError, RuntimeError)):
        verifier.verify_formal_result(
            result,
            verify_live_sources=False,
        )


def test_rejects_field_classification_tamper():
    result = deepcopy(_result())
    result["field_classification"][2]["availability"] = "pre_draw"
    _rehash(result)
    with pytest.raises((ValueError, RuntimeError)):
        verifier.verify_formal_result(
            result,
            verify_live_sources=False,
        )


def test_rejects_false_promotion_decision():
    result = deepcopy(_result())
    result["conclusion"]["status"] = (
        "future_only_challenger_design_allowed"
    )
    result["conclusion"]["future_challenger_design_allowed"] = True
    result["conclusion"]["selected_future_challenger"] = (
        "persistent_dirichlet_1"
    )
    _rehash(result)
    with pytest.raises((ValueError, RuntimeError)):
        verifier.verify_formal_result(
            result,
            verify_live_sources=False,
        )


def test_main_output_is_cp1252_safe(monkeypatch):
    output = io.BytesIO()
    stream = io.TextIOWrapper(output, encoding="cp1252")
    monkeypatch.setattr(verifier, "_run", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        verifier,
        "verify_formal_result",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(verifier.sys, "stdout", stream)

    assert verifier.main(["--tests-only"]) == 0
    stream.flush()
    assert (
        "verification passed"
        in output.getvalue().decode("cp1252").lower()
    )
