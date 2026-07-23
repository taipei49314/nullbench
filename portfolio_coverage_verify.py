"""五注精確機率 coverage 研究的一鍵分階段測試、正式執行與驗收。"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


BASE = Path(__file__).resolve().parent
NPM = "npm.cmd" if os.name == "nt" else "npm"
FORMAL_WARMUP_DRAWS = 60
FORMAL_BOOTSTRAP_SAMPLES = 2_000
FORMAL_BOOTSTRAP_BLOCK = 13
STAGE_TESTS = (
    (
        "probability_math",
        (
            "tests/test_portfolio_coverage.py",
            "tests/test_games.py",
        ),
    ),
    (
        "lookahead_and_ledger",
        (
            "tests/test_portfolio_coverage.py",
            "tests/test_agent_loop.py",
            "tests/test_agent_ablation.py",
        ),
    ),
)


def _run(command: list[str], *, cwd: Path = BASE) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def verify_formal_result(result: dict) -> None:
    failures = []
    if result.get("schema_version") != "2":
        failures.append("schema_version")
    methodology = result.get("methodology", {})
    expected = {
        "warmup_draws": FORMAL_WARMUP_DRAWS,
        "bootstrap_samples": FORMAL_BOOTSTRAP_SAMPLES,
        "bootstrap_block_draws": FORMAL_BOOTSTRAP_BLOCK,
        "combinations_per_draw": 3_003,
    }
    failures.extend(
        field
        for field, value in expected.items()
        if methodology.get(field) != value
    )
    quality = result.get("data_quality", {})
    if quality.get("status") != "pass":
        failures.append("data_quality")
    profiles = quality.get("split_profiles", {})
    if set(profiles) != {"super", "lotto649"} or any(
        profile.get("holdout_draws", 0) < 1
        for profile in profiles.values()
    ):
        failures.append("holdout_split")
    integrity = result.get("records_integrity", {})
    if (
        integrity.get("unchanged") is not True
        or integrity.get("before_sha256")
        != integrity.get("after_sha256")
    ):
        failures.append("records_integrity")

    summary = result.get("summary", [])
    expected_rows = {
        (game, split)
        for game in ("super", "lotto649")
        for split in ("development", "holdout")
    }
    if {
        (row.get("game"), row.get("split")) for row in summary
    } != expected_rows:
        failures.append("summary_coverage")
    for row in summary:
        if (
            row.get("draws", 0) < 1
            or row.get("minimum_exact_probability_delta", -1) < -1e-15
            or row.get("exact_probability_non_decrease_rate") != 1.0
            or row.get(
                "minimum_any_prize_probability_delta", -1
            )
            < -1e-15
            or row.get(
                "any_prize_probability_non_decrease_rate"
            )
            != 1.0
            or not 0
            < row.get("uniform_random_five_probability", 0)
            < 1
            or not 0
            < row.get(
                "uniform_random_five_any_prize_probability", 0
            )
            < 1
        ):
            failures.append(
                f"{row.get('game')}:{row.get('split')}:probability"
            )
    traces = result.get("recent_holdout_trace", {})
    if set(traces) != {"super", "lotto649"} or any(
        not rows or len(rows) > 52 for rows in traces.values()
    ):
        failures.append("recent_holdout_trace")
    trace_text = json.dumps(traces, ensure_ascii=False)
    if '"numbers"' in trace_text or '"special"' in trace_text:
        failures.append("trace_contains_raw_draw_numbers")
    if result.get("conclusion", {}).get("status") not in {
        "eligible_for_forward_shadow",
        "retain_current_selector",
    }:
        failures.append("conclusion")
    if failures:
        raise RuntimeError(
            "五注精確機率研究正式驗收失敗：" + ", ".join(failures)
        )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="分階段測試後執行五注精確機率 coverage 研究"
    )
    parser.add_argument(
        "--tests-only",
        action="store_true",
        help="只跑階段、前端與全套測試，不重算正式結果",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("research") / "results",
    )
    args = parser.parse_args(argv)

    for stage, files in STAGE_TESTS:
        print(f"[gate-test] {stage}", flush=True)
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

    print("[gate-test] frontend", flush=True)
    for command in (
        [NPM, "test", "--", "--run"],
        [NPM, "run", "lint"],
        [NPM, "run", "build"],
    ):
        _run(command, cwd=BASE / "frontend")

    if not args.tests_only:
        print("[formal] portfolio coverage shadow study", flush=True)
        _run(
            [
                sys.executable,
                "-B",
                "-X",
                "utf8",
                "portfolio_coverage.py",
                "--warmup-draws",
                str(FORMAL_WARMUP_DRAWS),
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
            (output_dir / "portfolio_coverage.json").read_text(
                encoding="utf-8"
            )
        )
        verify_formal_result(result)
        print("[gate-test] full_suite_post", flush=True)
        _run(full_suite)

    print("[gate-test] git_diff_check", flush=True)
    _run(["git", "diff", "--check"])
    print("五注精確機率研究各階段、前端與完整測試均通過。", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
