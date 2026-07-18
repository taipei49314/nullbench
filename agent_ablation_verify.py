"""Agent 數量消融的一鍵分階段完整測試、正式執行與驗收。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys


BASE = Path(__file__).resolve().parent
FORMAL_WARMUP_DRAWS = 60
FORMAL_NULL_REPLICATES = 200
FORMAL_BOOTSTRAP_SAMPLES = 2_000
FORMAL_BOOTSTRAP_BLOCK = 13
STAGE_TESTS = (
    ("ablation_core", ("tests/test_agent_ablation.py",)),
    (
        "report_contract",
        (
            "tests/test_agent_ablation_report.py",
            "tests/test_agent_ablation.py",
        ),
    ),
)


def _run(command: list[str]) -> None:
    subprocess.run(command, cwd=BASE, check=True)


def stage_test_commands(
    python: str = sys.executable,
) -> list[tuple[str, list[str]]]:
    return [
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
        for stage, files in STAGE_TESTS
    ]


def verify_formal_result(result: dict) -> None:
    failures = []
    methodology = result.get("methodology", {})
    expected = {
        "agent_subsets": 26,
        "warmup_draws": FORMAL_WARMUP_DRAWS,
        "null_replicates_per_draw": FORMAL_NULL_REPLICATES,
        "bootstrap_samples": FORMAL_BOOTSTRAP_SAMPLES,
        "bootstrap_block_draws": FORMAL_BOOTSTRAP_BLOCK,
    }
    failures.extend(
        field
        for field, value in expected.items()
        if methodology.get(field) != value
    )
    if result.get("data_quality", {}).get("status") != "pass":
        failures.append("data_quality")
    profiles = result.get("data_quality", {}).get("split_profiles", {})
    if set(profiles) != {"super", "lotto649"} or any(
        profile.get("holdout_draws", 0) < 1 for profile in profiles.values()
    ):
        failures.append("holdout_split")
    integrity = result.get("records_integrity", {})
    if (
        integrity.get("unchanged") is not True
        or integrity.get("before_sha256") != integrity.get("after_sha256")
    ):
        failures.append("records_integrity")
    expected_rows = {
        (game, split, size)
        for game in ("super", "lotto649")
        for split in ("development", "holdout")
        for size in range(2, 6)
    }
    actual_rows = {
        (row.get("game"), row.get("split"), row.get("agent_count"))
        for row in result.get("count_summary", [])
    }
    if actual_rows != expected_rows:
        failures.append("count_summary")
    if result.get("conclusion", {}).get("status") not in {
        "supported",
        "not_supported",
    }:
        failures.append("conclusion")
    if failures:
        raise RuntimeError(
            "Agent 消融正式驗收失敗：" + ", ".join(failures)
        )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="分階段測試後執行完整 Agent 數量消融"
    )
    parser.add_argument(
        "--tests-only",
        action="store_true",
        help="只跑階段與全套測試，不重算正式結果",
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
        print("[formal] agent-count ablation", flush=True)
        _run(
            [
                sys.executable,
                "-B",
                "-X",
                "utf8",
                "agent_ablation.py",
                "--warmup-draws",
                str(FORMAL_WARMUP_DRAWS),
                "--null-replicates",
                str(FORMAL_NULL_REPLICATES),
                "--bootstrap-samples",
                str(FORMAL_BOOTSTRAP_SAMPLES),
                "--bootstrap-block",
                str(FORMAL_BOOTSTRAP_BLOCK),
                "--output",
                str(args.output),
            ]
        )
        output_dir = (
            args.output if args.output.is_absolute() else BASE / args.output
        )
        result = json.loads(
            (output_dir / "agent_ablation.json").read_text(encoding="utf-8")
        )
        verify_formal_result(result)
        print("[gate-test] full_suite_post", flush=True)
        _run(full_suite)

    print("[gate-test] git_diff_check", flush=True)
    _run(["git", "diff", "--check"])
    print("Agent 消融各階段、正式研究與完整測試均通過。", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
