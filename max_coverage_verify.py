"""共識完全分散五注研究的分階段測試、正式執行與驗收。"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import sys

from engine.games import LOTTO649, SUPER
from research.max_coverage import EXPERIMENT_ID, OFFICIAL_RULE_URLS
from research.structural_optimum import (
    structural_proof_reference,
    verify_structural_optimum_certificate,
)


BASE = Path(__file__).resolve().parent
NPM = "npm.cmd" if os.name == "nt" else "npm"
FORMAL_WARMUP_DRAWS = 60
FORMAL_BOOTSTRAP_SAMPLES = 2_000
FORMAL_BOOTSTRAP_BLOCK = 13
KNOWN_EXACT = {
    SUPER: {
        "any_prize": 0.5429629500836931,
        "three_main": 0.1920413839918484,
    },
    LOTTO649: {
        "any_prize": 0.15296613117321764,
        "three_main": 0.09290168005643094,
    },
}


def _run(command: list[str], *, cwd: Path = BASE) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def verify_exact_selector_audits(base: Path = BASE) -> None:
    manifest = json.loads(
        (
            Path(base) / "simulation" / "results" / "manifest.json"
        ).read_text(encoding="utf-8")
    )
    failures = []
    for game in (SUPER, LOTTO649):
        path = (
            Path(base)
            / "research"
            / "results"
            / f"exact_selector_audit_{game}.json"
        )
        try:
            result = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            failures.append(f"{game}:missing")
            continue
        expected = KNOWN_EXACT[game]
        reference = result.get("disjoint_reference", {})
        if (
            result.get("game") != game
            or result.get("complete_enumeration") is not True
            or result.get("combinations_expected") != 3_003
            or result.get("combinations_evaluated") != 3_003
            or result.get("source_decision_hash")
            != manifest["games"][game]["next_decision"][
                "decision_hash"
            ]
            or result.get("safe_candidates_better_than_heuristic")
            != 0
            or abs(result.get("heuristic_any_prize_regret", 1))
            > 1e-15
            or result.get("candidate_pool_gap_to_disjoint_reference", 0)
            <= 0
            or reference.get("main_union_size") != 30
            or reference.get("maximum_pairwise_main_overlap") != 0
            or not math.isclose(
                reference.get("exact_any_prize", -1),
                expected["any_prize"],
                rel_tol=0,
                abs_tol=1e-15,
            )
            or not math.isclose(
                reference.get("exact_at_least_three_main", -1),
                expected["three_main"],
                rel_tol=0,
                abs_tol=1e-15,
            )
        ):
            failures.append(f"{game}:invalid")
    if failures:
        raise RuntimeError(
            "精確 selector 枚舉驗收失敗：" + ", ".join(failures)
        )


def verify_formal_result(result: dict) -> None:
    failures = []
    if (
        result.get("schema_version") != "1"
        or result.get("experiment_id") != EXPERIMENT_ID
    ):
        failures.append("schema")
    methodology = result.get("methodology", {})
    expected_methodology = {
        "warmup_draws": FORMAL_WARMUP_DRAWS,
        "bootstrap_samples": FORMAL_BOOTSTRAP_SAMPLES,
        "bootstrap_block_draws": FORMAL_BOOTSTRAP_BLOCK,
        "selection_budget": "每期固定五注",
    }
    if any(
        methodology.get(field) != expected
        for field, expected in expected_methodology.items()
    ) or methodology.get(
        "official_prize_rules"
    ) != OFFICIAL_RULE_URLS or methodology.get(
        "structural_optimum_proof"
    ) != structural_proof_reference():
        failures.append("methodology")
    quality = result.get("data_quality", {})
    if quality.get("status") != "pass":
        failures.append("data_quality")
    profiles = quality.get("split_profiles", {})
    if set(profiles) != {SUPER, LOTTO649} or any(
        profile.get("holdout_draws", 0) < 1
        for profile in profiles.values()
    ):
        failures.append("split_profiles")
    summary = result.get("summary", [])
    expected_rows = {
        (game, split)
        for game in (SUPER, LOTTO649)
        for split in ("development", "holdout")
    }
    if {
        (row.get("game"), row.get("split")) for row in summary
    } != expected_rows:
        failures.append("summary")
    for row in summary:
        game = row.get("game")
        expected = KNOWN_EXACT.get(game, {})
        if (
            row.get("draws", 0) < 1
            or row.get("max_union_size") != 30
            or row.get("structural_non_decrease_rate") != 1.0
            or row.get(
                "minimum_max_minus_proposal_coverage_exact_any_prize",
                -1,
            )
            < -1e-15
            or row.get(
                "minimum_max_minus_proposal_coverage_exact_three_main",
                -1,
            )
            < -1e-15
            or row.get(
                "max_minus_proposal_coverage_exact_any_prize", 0
            )
            <= 0
            or row.get(
                "max_minus_proposal_coverage_exact_three_main", 0
            )
            <= 0
            or not math.isclose(
                row.get("max_coverage_exact_any_prize", -1),
                expected.get("any_prize", -2),
                rel_tol=0,
                abs_tol=1e-15,
            )
            or not math.isclose(
                row.get("max_coverage_exact_three_main", -1),
                expected.get("three_main", -2),
                rel_tol=0,
                abs_tol=1e-15,
            )
        ):
            failures.append(
                f"{game}:{row.get('split')}:probability"
            )
    integrity = result.get("records_integrity", {})
    if (
        integrity.get("unchanged") is not True
        or integrity.get("before_sha256")
        != integrity.get("after_sha256")
    ):
        failures.append("records_integrity")
    conclusion = result.get("conclusion", {})
    if (
        conclusion.get("status") != "eligible_for_forward_shadow"
        or not all(
            conclusion.get(
                "structural_probability_pass", {}
            ).get(game)
            is True
            for game in (SUPER, LOTTO649)
        )
    ):
        failures.append("conclusion")
    if failures:
        raise RuntimeError(
            "共識完全分散研究正式驗收失敗："
            + ", ".join(failures)
        )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="驗收共識完全分散五注影子研究"
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
    stages = (
        (
            "probability_and_construction",
            (
                "tests/test_structural_optimum.py",
                "tests/test_max_coverage.py",
                "tests/test_exact_selector_audit.py",
                "tests/test_portfolio_coverage.py",
                "tests/test_games.py",
            ),
        ),
        (
            "lookahead_and_forward_contract",
            (
                "tests/test_max_coverage.py",
                "tests/test_agent_loop.py",
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
    print("[gate-test] full_suite", flush=True)
    _run(full_suite)
    print("[gate-test] frontend", flush=True)
    for command in (
        [NPM, "test", "--", "--run"],
        [NPM, "run", "lint"],
        [NPM, "run", "build"],
    ):
        _run(command, cwd=BASE / "frontend")
    if not args.tests_only:
        print("[formal] max coverage consensus study", flush=True)
        _run(
            [
                sys.executable,
                "-B",
                "-X",
                "utf8",
                "max_coverage.py",
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
    if not args.tests_only or (output_dir / "max_coverage.json").exists():
        result = json.loads(
            (output_dir / "max_coverage.json").read_text(
                encoding="utf-8"
            )
        )
        verify_formal_result(result)
        verify_structural_optimum_certificate(
            json.loads(
                (
                    BASE
                    / "research"
                    / "results"
                    / "structural_optimum.json"
                ).read_text(encoding="utf-8")
            )
        )
        verify_exact_selector_audits(BASE)
        print("[formal] artifacts verified", flush=True)
    print("[gate-test] git_diff_check", flush=True)
    _run(["git", "diff", "--check"])
    print("共識完全分散五注研究驗收通過。", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
