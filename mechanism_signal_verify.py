"""開獎機制訊號研究的分階段測試、產物與完整驗收。"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import sys

from engine.agent_loop import canonical_hash
from engine.games import LOTTO649, SUPER
from research.mechanism_signal import (
    EXPERIMENT_ID,
    MAIN_CANDIDATES,
)
from research.structural_optimum import structural_proof_reference
from research.profit_portfolio_forward import (
    GUARDED_PROOF,
    PORTFOLIO_IDS,
    UNCONSTRAINED_PROOF,
)


BASE = Path(__file__).resolve().parent
NPM = "npm.cmd" if os.name == "nt" else "npm"
FORMAL_RESULT = (
    BASE / "research" / "results" / "mechanism_signal.json"
)


def _run(command: list[str], *, cwd: Path = BASE) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def verify_formal_result(result: dict) -> None:
    failures = []
    methodology = result.get("methodology", {})
    if (
        result.get("schema_version") != "1"
        or result.get("experiment_id") != EXPERIMENT_ID
    ):
        failures.append("schema")
    if (
        methodology.get("warmup_draws") != 60
        or methodology.get("development_fraction") != 0.7
        or methodology.get("inner_training_fraction") != 0.7
        or methodology.get("bootstrap_samples") != 2_000
        or methodology.get("bootstrap_block_draws") != 13
        or methodology.get("main_candidates")
        != {
            game: list(candidates)
            for game, candidates in MAIN_CANDIDATES.items()
        }
        or methodology.get("structural_optimum_proof")
        != structural_proof_reference()
    ):
        failures.append("methodology")
    quality = result.get("data_quality", {})
    profiles = quality.get("profiles", {})
    splits = quality.get("split_profiles", {})
    if (
        quality.get("status") != "pass"
        or profiles.get(SUPER, {}).get("draws") != 1929
        or profiles.get(LOTTO649, {}).get("draws") != 2153
        or profiles.get(LOTTO649, {}).get("off_schedule_draws")
        != 113
        or splits.get(SUPER, {}).get("holdout_draws") != 561
        or splits.get(LOTTO649, {}).get("holdout_draws") != 628
    ):
        failures.append("data_quality")
    rows = result.get("main_candidate_holdout", [])
    if {
        (row.get("game"), row.get("candidate"))
        for row in rows
    } != {
        (game, candidate)
        for game, candidates in MAIN_CANDIDATES.items()
        for candidate in candidates
    }:
        failures.append("candidate_rows")
    decisions = result.get("main_decisions", {})
    if (
        decisions.get(SUPER, {}).get(
            "development_selected_candidate"
        )
        != "uniform_null"
        or decisions.get(LOTTO649, {}).get(
            "development_selected_candidate"
        )
        != "total_ball_frequency"
        or any(
            decisions.get(game, {}).get("promotion_eligible")
            is not False
            for game in (SUPER, LOTTO649)
        )
    ):
        failures.append("main_decisions")
    special = result.get("super_special_candidate", {})
    common = special.get("profit_common_special_candidate", {})
    if (
        special.get("selected_specials") != [2, 5, 3, 4, 1]
        or special.get("holdout_special_hits") != 377
        or special.get("inner_validation_delta_vs_exact_null", 0)
        >= 0
        or special.get("holm_adjusted_special_coverage_p_value", 0)
        < 0.05
        or special.get("paired_any_prize_ci_low", 0) >= 0
        or special.get("promotion_eligible") is not False
    ):
        failures.append("special_candidate")
    portfolios = common.get("holdout_portfolios", {})
    if (
        common.get("inner_selected_special") != 5
        or common.get("inner_validation_draws") != 393
        or common.get("inner_validation_special_hits") != 46
        or common.get("inner_validation_delta_vs_exact_null", 0)
        >= 0
        or common.get("selected_special") != 2
        or common.get("holdout_draws") != 561
        or common.get("holdout_special_hits") != 83
        or not math.isclose(
            common.get("holdout_raw_one_sided_p_value", -1),
            0.05959373461580309,
            abs_tol=1e-15,
        )
        or common.get("holm_adjusted_one_sided_p_value", 0)
        < 0.05
        or set(portfolios) != set(PORTFOLIO_IDS)
        or any(
            not math.isclose(
                portfolios.get(portfolio_id, {}).get(
                    "strict_profit_delta", -1
                ),
                0.0071301247771836,
                abs_tol=1e-15,
            )
            or portfolios.get(portfolio_id, {}).get(
                "strict_profit_delta_ci_low", 0
            )
            >= 0
            for portfolio_id in PORTFOLIO_IDS
        )
        or common.get("promotion_eligible") is not False
        or common.get("decision")
        != "retain_consensus_profit_common_special"
    ):
        failures.append("profit_common_special_candidate")
    candidate = result.get("future_forward_shadow_candidate", {})
    if (
        len(candidate.get("candidate_hash", "")) != 64
        or candidate.get("use") != "future_forward_shadow_only"
        or candidate.get("promotion_eligible") is not False
    ):
        failures.append("forward_candidate")
    profit_candidate = result.get(
        "future_profit_common_special_shadow_candidate", {}
    )
    profit_candidate_payload = {
        key: value
        for key, value in profit_candidate.items()
        if key != "candidate_hash"
    }
    if (
        profit_candidate.get("experiment_id")
        != "profit-common-special-forward-shadow-v1"
        or profit_candidate.get("source_experiment_id")
        != EXPERIMENT_ID
        or profit_candidate.get("game") != SUPER
        or profit_candidate.get("fitted_through") != "2021-03-01"
        or profit_candidate.get("selected_special") != 2
        or profit_candidate.get("promotion_eligible") is not False
        or profit_candidate.get("use")
        != "future_forward_shadow_only"
        or profit_candidate.get("guarded_profit_proof")
        != GUARDED_PROOF
        or profit_candidate.get("unconstrained_profit_proof")
        != UNCONSTRAINED_PROOF
        or profit_candidate.get("candidate_hash")
        != canonical_hash(profit_candidate_payload)
    ):
        failures.append("profit_common_special_forward_candidate")
    conclusion = result.get("conclusion", {})
    if (
        conclusion.get("status")
        != "retain_current_label_and_special_ranking"
        or conclusion.get("any_historical_promotion_eligible")
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
            "mechanism signal 正式驗收失敗："
            + ", ".join(failures)
        )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="驗收開獎機制的可重現訊號研究"
    )
    parser.add_argument(
        "--tests-only",
        action="store_true",
        help="不重算正式歷史，只驗證測試與既有產物",
    )
    args = parser.parse_args(argv)
    stages = (
        (
            "data_quality_and_statistical_calibration",
            (
                "tests/test_mechanism_signal.py",
                "tests/test_label_signal.py",
                "tests/test_research_data_quality.py",
            ),
        ),
        (
            "nested_selection_and_structural_safety",
            (
                "tests/test_mechanism_signal.py",
                "tests/test_max_coverage.py",
                "tests/test_structural_optimum.py",
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
        print("[formal] mechanism signal study", flush=True)
        _run(
            [
                sys.executable,
                "-B",
                "-X",
                "utf8",
                "mechanism_signal.py",
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
    print("開獎機制訊號研究驗收通過。", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
