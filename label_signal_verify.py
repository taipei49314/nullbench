"""30 號標籤排序研究的分階段測試、正式產物與回歸驗收。"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from engine.games import LOTTO649, SUPER
from research.label_signal import EXPERIMENT_ID, RANKER_NAMES
from research.structural_optimum import structural_proof_reference


BASE = Path(__file__).resolve().parent
NPM = "npm.cmd" if os.name == "nt" else "npm"
FORMAL_RESULT = BASE / "research" / "results" / "label_signal.json"


def _run(command: list[str], *, cwd: Path = BASE) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def verify_formal_result(result: dict) -> None:
    failures = []
    if (
        result.get("schema_version") != "1"
        or result.get("experiment_id") != EXPERIMENT_ID
    ):
        failures.append("schema")
    methodology = result.get("methodology", {})
    if (
        methodology.get("warmup_draws") != 60
        or methodology.get("development_fraction") != 0.7
        or methodology.get("bootstrap_samples") != 2_000
        or methodology.get("bootstrap_block_draws") != 13
        or methodology.get("rankers") != list(RANKER_NAMES)
        or methodology.get("structural_optimum_proof")
        != structural_proof_reference()
    ):
        failures.append("methodology")
    profiles = result.get("data_quality", {}).get(
        "split_profiles", {}
    )
    if (
        result.get("data_quality", {}).get("status") != "pass"
        or set(profiles) != {SUPER, LOTTO649}
        or profiles.get(SUPER, {}).get("holdout_draws") != 561
        or profiles.get(LOTTO649, {}).get("holdout_draws") != 628
    ):
        failures.append("data_quality")
    expected_rows = {
        (game, split, ranker)
        for game in (SUPER, LOTTO649)
        for split in ("development", "holdout")
        for ranker in RANKER_NAMES
    }
    if {
        (row.get("game"), row.get("split"), row.get("ranker"))
        for row in result.get("summary", [])
    } != expected_rows:
        failures.append("summary")
    decisions = result.get(
        "development_selection_and_holdout", {}
    )
    if (
        decisions.get(SUPER, {}).get(
            "development_selected_ranker"
        )
        != "cold_13"
        or decisions.get(SUPER, {}).get("promotion_eligible")
        is not False
        or decisions.get(LOTTO649, {}).get(
            "development_selected_ranker"
        )
        != "consensus"
        or decisions.get(LOTTO649, {}).get("promotion_eligible")
        is not False
    ):
        failures.append("selection")
    evidence = result.get(
        "consensus_holdout_vs_exact_uniform_null", {}
    )
    if any(
        game not in evidence
        or evidence[game].get("predictive_label_signal_supported")
        is not False
        or evidence[game].get(
            "holm_adjusted_one_sided_p_values", {}
        ).get("union_main_hits", 0)
        < 0.05
        for game in (SUPER, LOTTO649)
    ):
        failures.append("null_evidence")
    conclusion = result.get("conclusion", {})
    if (
        conclusion.get("status")
        != "retain_consensus_label_ranking"
        or conclusion.get("both_games_promotion_eligible")
        is not False
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
            "label signal 正式驗收失敗：" + ", ".join(failures)
        )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="驗收 30 號標籤排序的封存 holdout 研究"
    )
    parser.add_argument(
        "--tests-only",
        action="store_true",
        help="不重算正式歷史，只驗證測試與既有產物",
    )
    args = parser.parse_args(argv)
    stages = (
        (
            "lookahead_and_null_calibration",
            (
                "tests/test_label_signal.py",
                "tests/test_structural_optimum.py",
                "tests/test_agent_loop.py",
            ),
        ),
        (
            "selection_and_forward_safety",
            (
                "tests/test_label_signal.py",
                "tests/test_max_coverage.py",
                "tests/test_forward_lab.py",
                "tests/test_sync_service.py",
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
        print("[formal] label signal study", flush=True)
        _run(
            [
                sys.executable,
                "-B",
                "-X",
                "utf8",
                "label_signal.py",
            ]
        )
    verify_formal_result(
        json.loads(FORMAL_RESULT.read_text(encoding="utf-8"))
    )
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
    print("30 號標籤排序研究驗收通過。", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
