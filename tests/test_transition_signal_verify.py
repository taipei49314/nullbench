"""條件轉移正式產物驗證器的 fail-closed 測試。"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from transition_signal_verify import verify_formal_result


BASE = Path(__file__).parent.parent
FORMAL = (
    BASE / "research" / "results" / "transition_signal.json"
)


def _result() -> dict:
    return json.loads(FORMAL.read_text(encoding="utf-8"))


def test_committed_transition_result_passes_formal_verifier():
    verify_formal_result(_result())


@pytest.mark.parametrize(
    "mutate",
    [
        lambda result: result["protocol"].update(
            {"protocol_hash": "0" * 64}
        ),
        lambda result: result[
            "future_forward_shadow_protocol"
        ].update({"registration_eligible": True}),
        lambda result: result["records_integrity"].update(
            {"unchanged": False}
        ),
    ],
)
def test_formal_verifier_rejects_tampering(mutate):
    result = deepcopy(_result())
    mutate(result)

    with pytest.raises(RuntimeError, match="正式驗收失敗"):
        verify_formal_result(result)
