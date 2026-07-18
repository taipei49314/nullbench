"""一鍵執行研究階段測試、正式回測與最終驗收。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys


BASE = Path(__file__).resolve().parent
FORMAL_REPLICATES = 8
FORMAL_BOOTSTRAP_SAMPLES = 1_000
REQUIRED_GATES = (
    "data_quality",
    "strategy_search",
    "validation_holdout",
    "decision_report",
)
STAGE_TESTS = (
    (
        "data_quality",
        ("tests/test_research_data_quality.py", "tests/test_research_backtest.py"),
    ),
    (
        "strategy_search",
        (
            "tests/test_research_strategy_search.py",
            "tests/test_research_backtest.py",
        ),
    ),
    (
        "validation_holdout",
        (
            "tests/test_research_validation_holdout.py",
            "tests/test_research_strategy_search.py",
        ),
    ),
    (
        "decision_report",
        (
            "tests/test_research_decision_report.py",
            "tests/test_research_validation_holdout.py",
        ),
    ),
)


def _run(command: list[str]) -> None:
    subprocess.run(command, cwd=BASE, check=True)


def stage_test_commands(python: str = sys.executable) -> list[tuple[str, list[str]]]:
    commands = []
    for stage, files in STAGE_TESTS:
        commands.append(
            (
                stage,
                [
                    python,
                    "-B",
                    "-X",
                    "utf8",
                    "-m",
                    "pytest",
                    *files,
                    "-q",
                    "-p",
                    "no:cacheprovider",
                ],
            )
        )
    return commands


def verify_formal_study(study: dict) -> None:
    """拒絕把低樣本 smoke run 或失敗閘門當成正式結果。"""
    failures = []
    if study.get("replicates") != FORMAL_REPLICATES:
        failures.append("replicates")
    if study.get("bootstrap_samples") != FORMAL_BOOTSTRAP_SAMPLES:
        failures.append("bootstrap_samples")
    gates = study.get("stage_gates", {})
    failures.extend(
        f"gate:{name}"
        for name in REQUIRED_GATES
        if gates.get(name, {}).get("status") != "pass"
    )
    integrity = study.get("records_integrity", {})
    if (
        integrity.get("unchanged") is not True
        or integrity.get("before_sha256") != integrity.get("after_sha256")
    ):
        failures.append("records_integrity")
    if study.get("decision", {}).get("economic") != "no_play":
        failures.append("economic_decision")
    if failures:
        raise RuntimeError("正式研究驗收失敗：" + ", ".join(failures))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="逐階段完整測試後，重現正式全歷史策略研究"
    )
    parser.add_argument(
        "--tests-only",
        action="store_true",
        help="只跑四階段與全套測試，不執行正式回測",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("research") / "results",
    )
    args = parser.parse_args(argv)

    for stage, command in stage_test_commands():
        print(f"[gate-test] {stage}", flush=True)
        _run(command)

    full_suite = [
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
    print("[gate-test] full_suite_pre", flush=True)
    _run(full_suite)

    if not args.tests_only:
        print("[formal] walk-forward backtest", flush=True)
        _run(
            [
                sys.executable,
                "-B",
                "-X",
                "utf8",
                "research_backtest.py",
                "--replicates",
                str(FORMAL_REPLICATES),
                "--bootstrap-samples",
                str(FORMAL_BOOTSTRAP_SAMPLES),
                "--output",
                str(args.output),
            ]
        )
        result_path = (
            args.output
            if args.output.is_absolute()
            else BASE / args.output
        ) / "strategy_research.json"
        study = json.loads(result_path.read_text(encoding="utf-8"))
        verify_formal_study(study)
        print("[gate-test] full_suite_post", flush=True)
        _run(full_suite)

    print("[gate-test] git_diff_check", flush=True)
    _run(["git", "diff", "--check"])
    print("所有研究階段、正式回測與完整測試均通過。", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
