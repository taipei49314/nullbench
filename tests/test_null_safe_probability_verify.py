"""公平零模型安全機率正式產物驗證器測試。"""
from __future__ import annotations

from copy import deepcopy
import json

import pytest

import null_safe_probability_verify


def _formal_result() -> dict:
    return json.loads(
        null_safe_probability_verify.FORMAL_RESULT.read_text(
            encoding="utf-8"
        )
    )


def test_formal_null_safe_probability_result_is_verified():
    null_safe_probability_verify.verify_formal_result(
        _formal_result()
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda result: result["methodology"].update(
            {"protocol_hash": "0" * 64}
        ),
        lambda result: result["prequential_summary"]["super"][
            "main"
        ].update({"null_safe_regret_vs_uniform": 0.1}),
        lambda result: result["prequential_summary"]["super"][
            "main"
        ].update({"uniform_log_loss": 1.0}),
        lambda result: result["final_models"]["lotto649"].update(
            {"main_gate_active": True}
        ),
        lambda result: result["records_integrity"].update(
            {"unchanged": False}
        ),
    ],
)
def test_formal_verifier_rejects_tampered_evidence(mutation):
    result = deepcopy(_formal_result())
    mutation(result)

    with pytest.raises(
        RuntimeError,
        match="null-safe 機率正式驗收失敗",
    ):
        null_safe_probability_verify.verify_formal_result(result)
