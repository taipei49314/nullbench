"""五注獲利機率 Pareto 證書的完整驗收。"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from engine.games import LOTTO649, SUPER
from research.profit_probability import (
    EXPECTED_SEARCH_CANDIDATES,
    EXPERIMENT_ID,
    verify_profit_probability_certificate,
)


BASE = Path(__file__).resolve().parent
NPM = "npm.cmd" if os.name == "nt" else "npm"
FORMAL_RESULT = (
    BASE
    / "research"
    / "results"
    / "profit_probability.json"
)


def _run(command: list[str], *, cwd: Path = BASE) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def verify_formal_result(result: dict) -> None:
    failures = []
    try:
        verify_profit_probability_certificate(result, BASE)
    except RuntimeError:
        failures.append("certificate")
    if result.get("experiment_id") != EXPERIMENT_ID:
        failures.append("experiment")
    enumeration = result.get("enumeration_certificate", {})
    if (
        enumeration.get("total_exact_candidates")
        != EXPECTED_SEARCH_CANDIDATES
        or enumeration.get(
            "complete_within_high_tier_guardrail"
        )
        is not True
    ):
        failures.append("enumeration")
    games = result.get("games", {})
    super_row = games.get(SUPER, {})
    optimum = super_row.get("strict_profit_optimum", {})
    metrics = optimum.get("metrics", {})
    if (
        optimum.get("canonical_shared_masks")
        != [3, 5, 6, 9, 10, 12, 17, 18, 20, 24]
        or optimum.get("special_partition") != [0, 0, 0, 0, 0]
        or metrics.get(
            "empirical_floor_strict_profit", {}
        ).get("numerator")
        != 1_203_926
        or super_row.get("robust_optimum_is_unique") is not True
        or super_row.get(
            "same_optimum_under_both_payout_models"
        )
        is not True
        or super_row.get("tradeoff", {}).get(
            "at_least_four_main_probability_change"
        )
        != 0
    ):
        failures.append("super_optimum")
    lotto_row = games.get(LOTTO649, {})
    if (
        lotto_row.get(
            "any_prize_equals_nominal_strict_profit"
        )
        is not True
        or lotto_row.get(
            "any_prize_equals_empirical_floor_strict_profit"
        )
        is not True
    ):
        failures.append("lotto_equivalence")
    decision = result.get("decision", {})
    if (
        decision.get("automatic_switch") is not False
        or decision.get(
            "current_forward_registrations_unchanged"
        )
        is not True
    ):
        failures.append("forward_safety")
    source = result.get("source_structural_proof", {})
    if source != {
        "experiment_id": (
            "five-ticket-structural-optimum-proof-v1"
        ),
        "certificate_hash": (
            "9d74135192e33d5c8f20753841885cd604cd9523248e15f52"
            "dad4d4580742a23"
        ),
    }:
        failures.append("v1_reference")
    integrity = result.get("records_integrity", {})
    if (
        integrity.get("unchanged") is not True
        or integrity.get("before_sha256")
        != integrity.get("after_sha256")
    ):
        failures.append("records_integrity")
    if failures:
        raise RuntimeError(
            "獲利機率正式驗收失敗：" + ", ".join(failures)
        )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="驗收五注獲利機率 Pareto 正式證書"
    )
    parser.add_argument(
        "--tests-only",
        action="store_true",
        help="不重算證書，只驗證測試與既有正式產物",
    )
    args = parser.parse_args(argv)
    stages = (
        (
            "enumeration_and_independent_brute_force",
            (
                "tests/test_profit_probability.py",
                "tests/test_prize_tier_profile.py",
            ),
        ),
        (
            "certificate_and_forward_compatibility",
            (
                "tests/test_profit_probability.py",
                "tests/test_profit_probability_verify.py",
                "tests/test_high_tier_optimum.py",
                "tests/test_forward_lab.py",
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
        print("[formal] recompute profit certificate", flush=True)
        _run(
            [
                sys.executable,
                "-B",
                "-X",
                "utf8",
                "profit_probability.py",
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
    print("五注獲利機率 Pareto 證書驗收通過。", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
