"""無守門獲利正式驗收器的失敗關閉測試。"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from research.unconstrained_profit_optimum import (
    build_unconstrained_profit_certificate,
)
from unconstrained_profit_optimum_verify import (
    verify_formal_result,
)


BASE = Path(__file__).parent.parent


@pytest.fixture(scope="module")
def certificate():
    return build_unconstrained_profit_certificate(BASE)


def test_formal_verifier_accepts_recomputed_certificate(certificate):
    verify_formal_result(certificate)


@pytest.mark.parametrize(
    "mutation",
    [
        "certificate",
        "global_proof",
        "bound",
        "optimum",
        "scope",
        "forward",
        "records",
    ],
)
def test_formal_verifier_fails_closed(certificate, mutation):
    tampered = deepcopy(certificate)
    if mutation == "certificate":
        tampered["certificate_hash"] = "0" * 64
    elif mutation == "global_proof":
        tampered["proof"][
            "global_empirical_optimum_proved"
        ] = False
    elif mutation == "bound":
        tampered["proof"][
            "proper_special_partition_relaxations"
        ][0]["total_empirical_strict_profit_upper_count"] += 1
    elif mutation == "optimum":
        tampered["games"]["super"]["optimum_structure"][
            "special_partition"
        ] = [0, 1, 2, 3, 4]
    elif mutation == "scope":
        tampered["proof"]["nominal_common_special"][
            "certificate_scope"
        ] = "forged_global_scope"
    elif mutation == "forward":
        tampered["decision"]["automatic_switch"] = True
    else:
        tampered["records_integrity"]["unchanged"] = False

    with pytest.raises(RuntimeError, match="正式驗收失敗"):
        verify_formal_result(tampered)
