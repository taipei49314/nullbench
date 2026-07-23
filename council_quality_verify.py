"""Agent 品質影子研究的一鍵分階段測試、正式執行與驗收。"""
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
        "quality_core",
        (
            "tests/test_council_quality.py",
            "tests/test_council_quality_report.py",
            "tests/test_agent_ablation.py",
        ),
    ),
    (
        "loop_integration",
        (
            "tests/test_sync_service.py",
            "tests/test_automation.py",
            "tests/test_council_quality.py",
        ),
    ),
)


def _run(command: list[str], *, cwd: Path = BASE) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def verify_formal_result(result: dict) -> None:
    failures = []
    methodology = result.get("methodology", {})
    expected = {
        "warmup_draws": FORMAL_WARMUP_DRAWS,
        "bootstrap_samples": FORMAL_BOOTSTRAP_SAMPLES,
        "bootstrap_block_draws": FORMAL_BOOTSTRAP_BLOCK,
        "candidate_agent": "coverage_auditor",
        "candidate_proposals_per_draw": 3,
        "candidate_search_samples_per_proposal": 160,
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
    expected_agent_rows = {
        (game, split, agent)
        for game in ("super", "lotto649")
        for split in ("development", "holdout")
        for agent in (
            "independent_null",
            "overfit_guard",
            "regime_shift",
            "structural_bias",
            "temporal_dependency",
        )
    }
    actual_agent_rows = {
        (row.get("game"), row.get("split"), row.get("agent"))
        for row in result.get("agent_quality", [])
    }
    if actual_agent_rows != expected_agent_rows:
        failures.append("agent_quality")
    if len(result.get("critic_quality", [])) != 20:
        failures.append("critic_quality")
    if len(result.get("critic_pair_redundancy", [])) != 40:
        failures.append("critic_pair_redundancy")
    if len(result.get("judge_sensitivity", [])) != 20:
        failures.append("judge_sensitivity")
    selected = result.get("selected_replacements", {})
    if set(selected) != {"super", "lotto649"} or any(
        item.get("development", {}).get("agent")
        != item.get("holdout", {}).get("agent")
        for item in selected.values()
    ):
        failures.append("development_selection")
    traces = result.get("recent_holdout_trace", {})
    if set(traces) != {"super", "lotto649"} or any(
        not rows or len(rows) > 52 for rows in traces.values()
    ):
        failures.append("recent_holdout_trace")
    if result.get("conclusion", {}).get("status") not in {
        "promote_candidate",
        "retain_current_council",
    }:
        failures.append("conclusion")
    if failures:
        raise RuntimeError(
            "Agent 品質影子研究正式驗收失敗：" + ", ".join(failures)
        )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="分階段測試後執行完整 Agent 品質影子研究"
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
        print("[formal] council quality shadow study", flush=True)
        _run(
            [
                sys.executable,
                "-B",
                "-X",
                "utf8",
                "council_quality.py",
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
            (output_dir / "council_quality.json").read_text(
                encoding="utf-8"
            )
        )
        verify_formal_result(result)
        print("[gate-test] full_suite_post", flush=True)
        _run(full_suite)

    print("[gate-test] git_diff_check", flush=True)
    _run(["git", "diff", "--check"])
    print("Agent 品質影子研究各階段、前端與完整測試均通過。", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
