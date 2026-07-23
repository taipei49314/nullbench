"""威力彩無 overlap 守門獲利全域最優證書的完整驗收。"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from research.unconstrained_profit_optimum import (
    EXPECTED_EMPIRICAL_PROPER_UPPERS,
    EXPERIMENT_ID,
    NOMINAL_OPTIMUM_COUNT,
    PROPER_SPECIAL_COMPOSITIONS,
    verify_unconstrained_profit_certificate,
)


BASE = Path(__file__).resolve().parent
NPM = "npm.cmd" if os.name == "nt" else "npm"
FORMAL_RESULT = (
    BASE
    / "research"
    / "results"
    / "unconstrained_profit_optimum.json"
)


def _run(command: list[str], *, cwd: Path = BASE) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def verify_formal_result(result: dict) -> None:
    failures = []
    try:
        verify_unconstrained_profit_certificate(result, BASE)
    except RuntimeError:
        failures.append("certificate")
    if result.get("experiment_id") != EXPERIMENT_ID:
        failures.append("experiment")
    proof = result.get("proof", {})
    if (
        proof.get("global_empirical_optimum_proved") is not True
        or proof.get(
            "global_empirical_optimum_unique_up_to_relabeling"
        )
        is not True
        or proof.get("global_nominal_optimum_proved") is not True
        or proof.get(
            "global_nominal_optimum_unique_up_to_relabeling"
        )
        is not True
    ):
        failures.append("global_proof")
    bounds = {
        tuple(row.get("special_block_sizes", [])): row.get(
            "total_empirical_strict_profit_upper_count"
        )
        for row in proof.get(
            "proper_special_partition_relaxations", []
        )
    }
    if bounds != EXPECTED_EMPIRICAL_PROPER_UPPERS:
        failures.append("proper_special_bounds")
    game = result.get("games", {}).get("super", {})
    optimum = game.get("optimum_structure", {})
    metrics = game.get("metrics", {})
    if (
        optimum.get("membership_masks")
        != [7, 11, 13, 14, 19, 21, 22, 25, 26, 28]
        or optimum.get("membership_counts") != [1] * 10
        or optimum.get("special_partition") != [0] * 5
        or metrics.get(
            "empirical_floor_strict_profit", {}
        ).get("numerator")
        != 1_648_101
    ):
        failures.append("optimum")
    nominal = proof.get("nominal_common_special", {})
    nominal_proper = proof.get(
        "nominal_proper_special_global_bounds", []
    )
    if (
        nominal.get(
            "common_special_nominal_global_optimum_proved"
        )
        is not True
        or nominal.get("certificate_scope")
        != "common_special_structures"
        or {
            tuple(row.get("special_block_sizes", []))
            for row in nominal_proper
        }
        != set(PROPER_SPECIAL_COMPOSITIONS)
        or any(
            row.get(
                "global_nominal_strict_profit_upper_count",
                NOMINAL_OPTIMUM_COUNT,
            )
            >= NOMINAL_OPTIMUM_COUNT
            or row.get("strictly_below_optimum") is not True
            for row in nominal_proper
        )
        or game.get(
            "nominal_strict_profit_global_maximum", {}
        ).get("numerator")
        != NOMINAL_OPTIMUM_COUNT
    ):
        failures.append("nominal_global_proof")
    decision = result.get("decision", {})
    if (
        decision.get("automatic_switch") is not False
        or decision.get(
            "current_forward_registrations_unchanged"
        )
        is not True
    ):
        failures.append("forward_safety")
    source = result.get("source_pareto_certificate", {})
    if source != {
        "experiment_id": "five-ticket-profit-pareto-proof-v1",
        "certificate_hash": (
            "b91fb1e1f4a4f7ba6478389b05182761472fcdc9784460967"
            "b9011a739356ee4"
        ),
    }:
        failures.append("source_reference")
    integrity = result.get("records_integrity", {})
    if (
        integrity.get("unchanged") is not True
        or integrity.get("before_sha256")
        != integrity.get("after_sha256")
    ):
        failures.append("records_integrity")
    if failures:
        raise RuntimeError(
            "無守門獲利正式驗收失敗：" + ", ".join(failures)
        )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="驗收威力彩無 overlap 守門獲利全域最優證書"
    )
    parser.add_argument(
        "--tests-only",
        action="store_true",
        help="不重算證書，只驗證測試與既有正式產物",
    )
    args = parser.parse_args(argv)
    stages = (
        (
            "finite_enumerations_and_bounds",
            (
                "tests/test_unconstrained_profit_optimum.py",
                "tests/test_unconstrained_profit_optimum_verify.py",
                "tests/test_profit_probability.py",
            ),
        ),
        (
            "certificate_and_forward_compatibility",
            (
                "tests/test_forward_lab.py",
                "tests/test_profit_portfolio_forward.py",
            ),
        ),
    )
    for name, files in stages:
        print(f"[gate-test] {name}", flush=True)
        _run(
            [
                sys.executable,
                "-B",
                "-X",
                "utf8",
                "-m",
                "pytest",
                *files,
                "-q",
                "-p",
                "no:cacheprovider",
            ]
        )
    if not args.tests_only:
        print(
            "[formal] recompute unconstrained profit certificate",
            flush=True,
        )
        _run(
            [
                sys.executable,
                "-B",
                "-X",
                "utf8",
                "unconstrained_profit_optimum.py",
            ]
        )
    result = json.loads(
        FORMAL_RESULT.read_text(encoding="utf-8")
    )
    verify_formal_result(result)
    print("[formal] artifact verified", flush=True)
    print("[gate-test] full_suite", flush=True)
    _run(
        [
            sys.executable,
            "-B",
            "-X",
            "utf8",
            "-m",
            "pytest",
            "tests",
            "-q",
            "-p",
            "no:cacheprovider",
        ]
    )
    print("[gate-test] frontend", flush=True)
    _run([NPM, "test", "--", "--run"], cwd=BASE / "frontend")
    _run([NPM, "run", "lint"], cwd=BASE / "frontend")
    _run([NPM, "run", "build"], cwd=BASE / "frontend")
    print("[gate-test] git_diff_check", flush=True)
    _run(["git", "diff", "--check"])
    print("威力彩無守門獲利全域最優證書驗收通過。", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
