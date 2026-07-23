"""高獎級正式證書驗證器的 fail-closed 測試。"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from high_tier_optimum_verify import verify_formal_result


BASE = Path(__file__).parent.parent
FORMAL = (
    BASE / "research" / "results" / "high_tier_optimum.json"
)


def _result() -> dict:
    return json.loads(FORMAL.read_text(encoding="utf-8"))


def test_committed_high_tier_certificate_passes_verifier():
    verify_formal_result(_result())


@pytest.mark.parametrize(
    "mutate",
    [
        lambda result: result.update(
            {"certificate_hash": "0" * 64}
        ),
        lambda result: result["source_structural_proof"].update(
            {"certificate_hash": "0" * 64}
        ),
        lambda result: result["records_integrity"].update(
            {"unchanged": False}
        ),
    ],
)
def test_high_tier_verifier_rejects_tampering(mutate):
    result = deepcopy(_result())
    mutate(result)

    with pytest.raises(RuntimeError, match="正式驗收失敗"):
        verify_formal_result(result)
