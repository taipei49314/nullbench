"""五注高獎級 Pareto 最優補充證書的完整驗收。"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from engine.games import LOTTO649, SUPER
from research.high_tier_optimum import (
    EXPERIMENT_ID,
    HIGH_TIER_CUTOFF_RANK,
    MAIN_THRESHOLDS,
    verify_high_tier_optimum_certificate,
)


BASE = Path(__file__).resolve().parent
NPM = "npm.cmd" if os.name == "nt" else "npm"
FORMAL_RESULT = (
    BASE / "research" / "results" / "high_tier_optimum.json"
)


def _run(command: list[str], *, cwd: Path = BASE) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def verify_formal_result(result: dict) -> None:
    failures = []
    try:
        verify_high_tier_optimum_certificate(result)
    except RuntimeError:
        failures.append("certificate")
    source = result.get("source_structural_proof", {})
    if source != {
        "experiment_id": "five-ticket-structural-optimum-proof-v1",
        "certificate_hash": (
            "9d74135192e33d5c8f20753841885cd604cd9523248e15f52"
            "dad4d4580742a23"
        ),
    }:
        failures.append("v1_reference")
    if result.get("experiment_id") != EXPERIMENT_ID:
        failures.append("experiment")
    games = result.get("games", {})
    for game in (SUPER, LOTTO649):
        row = games.get(game, {})
        thresholds = row.get("main_hit_thresholds", [])
        tiers = row.get(
            "cumulative_high_tier_union_bounds", []
        )
        boundary = row.get(
            "first_non_exclusive_cumulative_tier", {}
        )
        if (
            [item.get("minimum_main_hits") for item in thresholds]
            != list(MAIN_THRESHOLDS)
            or any(
                item.get("global_optimum_proved") is not True
                for item in thresholds
            )
            or len(tiers) != HIGH_TIER_CUTOFF_RANK[game]
            or any(
                item.get("global_optimum_proved") is not True
                or item.get("union_upper_attained") is not True
                for item in tiers
            )
            or boundary.get("maximum_best_tier_rank")
            != HIGH_TIER_CUTOFF_RANK[game] + 1
            or boundary.get("union_upper_attained") is not False
            or boundary.get("union_upper_deficit_count", 0) <= 0
        ):
            failures.append(f"{game}_proof")
    conclusion = result.get("conclusion", {})
    if (
        conclusion.get("all_high_tier_union_bounds_attained")
        is not True
        or "共同全域最優" not in conclusion.get("strategy", "")
    ):
        failures.append("conclusion")
    integrity = result.get("records_integrity", {})
    if (
        integrity.get("unchanged") is not True
        or integrity.get("before_sha256")
        != integrity.get("after_sha256")
    ):
        failures.append("records_integrity")
    if failures:
        raise RuntimeError(
            "高獎級最優正式驗收失敗：" + ", ".join(failures)
        )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="驗收五注高獎級 Pareto 全域最優補充證書"
    )
    parser.add_argument(
        "--tests-only",
        action="store_true",
        help="不重算證書，只驗證測試與既有正式產物",
    )
    args = parser.parse_args(argv)
    stages = (
        (
            "independent_threshold_counting",
            (
                "tests/test_high_tier_optimum.py",
                "tests/test_prize_tier_profile.py",
                "tests/test_structural_optimum.py",
            ),
        ),
        (
            "certificate_and_forward_compatibility",
            (
                "tests/test_high_tier_optimum.py",
                "tests/test_high_tier_optimum_verify.py",
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
        print("[formal] recompute high-tier certificate", flush=True)
        _run(
            [
                sys.executable,
                "-B",
                "-X",
                "utf8",
                "high_tier_optimum.py",
            ]
        )
    result = json.loads(FORMAL_RESULT.read_text(encoding="utf-8"))
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
    print("五注高獎級 Pareto 最優證書驗收通過。", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
