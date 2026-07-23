"""五注全域結構最優證明的分階段測試與正式驗收。"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from research.structural_optimum import (
    build_structural_optimum_certificate,
    verify_structural_optimum_certificate,
    write_results,
)


BASE = Path(__file__).resolve().parent
NPM = "npm.cmd" if os.name == "nt" else "npm"
FORMAL_RESULT = (
    BASE / "research" / "results" / "structural_optimum.json"
)


def _run(command: list[str], *, cwd: Path = BASE) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="驗收五注完整中獎機率的全域結構證明"
    )
    parser.add_argument(
        "--tests-only",
        action="store_true",
        help="驗證既有正式證明，不重新寫出結果",
    )
    args = parser.parse_args(argv)

    stages = (
        (
            "independent_counting_and_finite_proof",
            (
                "tests/test_structural_optimum.py",
                "tests/test_portfolio_coverage.py",
                "tests/test_games.py",
            ),
        ),
        (
            "selector_and_forward_contract",
            (
                "tests/test_structural_optimum.py",
                "tests/test_max_coverage.py",
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
        print("[formal] recompute exact certificate", flush=True)
        write_results(
            build_structural_optimum_certificate(BASE),
            FORMAL_RESULT,
        )
    result = json.loads(FORMAL_RESULT.read_text(encoding="utf-8"))
    verify_structural_optimum_certificate(result)
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
    print("五注全域結構最優證明驗收通過。", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
