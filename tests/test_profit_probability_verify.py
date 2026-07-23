"""獲利機率正式驗收器的失敗關閉測試。"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from profit_probability_verify import verify_formal_result
from research.profit_probability import (
    build_profit_probability_certificate,
)


BASE = Path(__file__).parent.parent


@pytest.fixture(scope="module")
def certificate():
    return build_profit_probability_certificate(BASE)


def test_formal_verifier_accepts_recomputed_certificate(certificate):
    verify_formal_result(certificate)


@pytest.mark.parametrize(
    "mutation",
    [
        "certificate",
        "enumeration",
        "optimum",
        "forward",
        "records",
    ],
)
def test_formal_verifier_fails_closed(certificate, mutation):
    tampered = deepcopy(certificate)
    if mutation == "certificate":
        tampered["certificate_hash"] = "0" * 64
    elif mutation == "enumeration":
        tampered["enumeration_certificate"][
            "total_exact_candidates"
        ] -= 1
    elif mutation == "optimum":
        tampered["games"]["super"]["strict_profit_optimum"][
            "special_partition"
        ] = [0, 1, 2, 3, 4]
    elif mutation == "forward":
        tampered["decision"]["automatic_switch"] = True
    else:
        tampered["records_integrity"]["unchanged"] = False

    with pytest.raises(RuntimeError, match="正式驗收失敗"):
        verify_formal_result(tampered)
