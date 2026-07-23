"""獎級精確分解的分階段測試與正式驗收。"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from research.prize_tier_profile import (
    build_prize_tier_certificate,
    verify_prize_tier_certificate,
    write_results,
)


BASE = Path(__file__).resolve().parent
NPM = "npm.cmd" if os.name == "nt" else "npm"
FORMAL_RESULT = (
    BASE / "research" / "results" / "prize_tier_profile.json"
)


def _run(command: list[str], *, cwd: Path = BASE) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="驗收五注獎級、同時中獎與逐注邊際機率"
    )
    parser.add_argument(
        "--tests-only",
        action="store_true",
        help="驗證既有正式結果，不重新寫出結果",
    )
    args = parser.parse_args(argv)

    stages = (
        (
            "exact_state_and_independent_small_pool",
            (
                "tests/test_prize_tier_profile.py",
                "tests/test_games.py",
            ),
        ),
        (
            "structural_probability_contract",
            (
                "tests/test_prize_tier_profile.py",
                "tests/test_structural_optimum.py",
                "tests/test_portfolio_coverage.py",
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
        print("[formal] recompute exact tier certificate", flush=True)
        write_results(
            build_prize_tier_certificate(BASE),
            FORMAL_RESULT,
        )
    result = json.loads(FORMAL_RESULT.read_text(encoding="utf-8"))
    verify_prize_tier_certificate(result)
    print("[formal] certificate verified", flush=True)

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
    print("五注獎級與逐注邊際機率驗收通過。", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
