"""機率前緣 formal artifact 的接受與 fail-closed 測試。"""
from __future__ import annotations

from copy import deepcopy
import io
import json
from pathlib import Path

import pytest

import probability_frontier_verify as verifier
from engine.agent_loop import canonical_hash
from engine.games import SUPER
from research.probability_frontier import validate_result


BASE = Path(__file__).parent.parent
FORMAL = (
    BASE / "research" / "results" / "probability_frontier.json"
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


def test_rejects_regret_tamper_even_with_derived_fields_and_rehash():
    result = _result()
    row = next(
        row
        for row in result["frontier_rows"]
        if row["method_id"] == "subset_cumulative"
    )
    game_row = row["game_results"][SUPER]
    game_row["mean_regret_nats"] += 0.0001
    game_row["geometric_probability_ratio_vs_uniform"] = (
        __import__("math").exp(-game_row["mean_regret_nats"])
    )
    regrets = [
        value["mean_regret_nats"]
        for value in row["game_results"].values()
    ]
    row["mean_regret_across_games"] = sum(regrets) / len(regrets)
    row["minimax_regret"] = max(regrets)
    row["worst_game_probability_ratio_vs_uniform"] = (
        __import__("math").exp(-row["minimax_regret"])
    )
    _rehash(result)
    with pytest.raises(RuntimeError):
        verifier.verify_formal_result(
            result,
            verify_live_sources=True,
        )


def test_rejects_source_hash_tamper():
    result = _result()
    result["source_artifacts"]["draw_order_signal"][
        "file_sha256"
    ] = "0" * 64
    _rehash(result)
    with pytest.raises(RuntimeError):
        verifier.verify_formal_result(
            result,
            verify_live_sources=True,
        )


def test_rejects_score_scale_tamper():
    result = deepcopy(_result())
    result["protocol"]["score"] = "marginal_mass_log_loss"
    _rehash(result)
    with pytest.raises((ValueError, RuntimeError)):
        verifier.verify_formal_result(
            result,
            verify_live_sources=False,
        )


def test_rejects_exclusion_contract_tamper():
    result = deepcopy(_result())
    result["protocol"]["excluded_metric_families"].remove(
        "top_k_or_ticket_hits"
    )
    _rehash(result)
    with pytest.raises((ValueError, RuntimeError)):
        verifier.verify_formal_result(
            result,
            verify_live_sources=False,
        )


def test_rejects_false_champion():
    result = deepcopy(_result())
    result["conclusion"]["champion_method_id"] = (
        "subset_cumulative"
    )
    result["conclusion"]["status"] = (
        "future_only_research_required"
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
