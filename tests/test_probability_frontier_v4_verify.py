from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from engine.agent_loop import canonical_hash
from probability_frontier_v4_verify import (
    FORMAL_RESULT,
    verify_formal_result,
)
from research.cross_game_overlap_signal import (
    MODEL_ID as CROSS_GAME_MODEL_ID,
)
from research.probability_frontier_v4 import (
    PROTOCOL_FILE,
    SOURCE_FILES,
    validate_result,
)


ROOT = Path(__file__).resolve().parents[1]


def _formal() -> dict:
    return json.loads(FORMAL_RESULT.read_text(encoding="utf-8"))


def _rehash(result: dict) -> None:
    payload = dict(result)
    payload.pop("audit_hash", None)
    result["audit_hash"] = canonical_hash(payload)


def test_formal_frontier_v4_contract_and_decision():
    result = _formal()
    assert validate_result(result) == result
    verify_formal_result(result, verify_live_sources=False)


def test_formal_frontier_v4_matches_live_sources():
    verify_formal_result(_formal(), verify_live_sources=True)


def test_rehashed_cross_game_regret_tamper_is_caught_live():
    result = deepcopy(_formal())
    row = next(
        row
        for row in result["frontier_rows"]
        if row["method_id"] == CROSS_GAME_MODEL_ID
    )
    row["game_results"]["super"]["mean_regret_nats"] = 0.025
    row["game_results"]["super"][
        "geometric_probability_ratio_vs_uniform"
    ] = 0.975309912028333
    regrets = [
        row["game_results"][game]["mean_regret_nats"]
        for game in ("super", "lotto649")
    ]
    row["mean_regret_across_games"] = sum(regrets) / 2
    row["minimax_regret"] = max(regrets)
    row["worst_game_probability_ratio_vs_uniform"] = (
        0.975309912028333
    )
    _rehash(result)
    with pytest.raises(RuntimeError, match="live_recompute"):
        verify_formal_result(result, verify_live_sources=True)


def test_source_hash_tamper_fails_closed():
    result = deepcopy(_formal())
    result["source_artifacts"]["cross_game_overlap_signal"][
        "file_sha256"
    ] = "0" * 64
    _rehash(result)
    with pytest.raises(
        RuntimeError,
        match="source_cross_game_overlap_signal",
    ):
        verify_formal_result(result, verify_live_sources=True)


def test_false_champion_or_rank_fails_closed():
    result = deepcopy(_formal())
    result["conclusion"]["champion_method_id"] = CROSS_GAME_MODEL_ID
    cross = next(
        row
        for row in result["frontier_rows"]
        if row["method_id"] == CROSS_GAME_MODEL_ID
    )
    cross["rank"] = 1
    _rehash(result)
    with pytest.raises(RuntimeError):
        verify_formal_result(result, verify_live_sources=False)


def test_protocol_hash_tamper_fails_closed():
    result = deepcopy(_formal())
    result["protocol"]["protocol_file_sha256"] = "0" * 64
    _rehash(result)
    with pytest.raises(RuntimeError, match="protocol_file"):
        verify_formal_result(result, verify_live_sources=False)


def test_source_manifest_is_fixed():
    result = _formal()
    assert set(result["source_artifacts"]) == set(SOURCE_FILES)
    assert result["conclusion"]["v3_immutable"] is True


@pytest.mark.parametrize(
    "script",
    ["probability_frontier_v4.py", "probability_frontier_v4_verify.py"],
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
