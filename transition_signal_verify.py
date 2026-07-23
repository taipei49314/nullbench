"""條件轉移訊號研究的分階段測試、產物與完整驗收。"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from engine.games import LOTTO649, SUPER
from research.structural_optimum import structural_proof_reference
from research.transition_signal import (
    EXPERIMENT_ID,
    TRANSITION_CANDIDATES,
    transition_protocol_reference,
)


BASE = Path(__file__).resolve().parent
NPM = "npm.cmd" if os.name == "nt" else "npm"
FORMAL_RESULT = (
    BASE / "research" / "results" / "transition_signal.json"
)


def _run(command: list[str], *, cwd: Path = BASE) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def verify_formal_result(result: dict) -> None:
    failures = []
    methodology = result.get("methodology", {})
    if (
        result.get("schema_version") != "1"
        or result.get("experiment_id") != EXPERIMENT_ID
        or result.get("protocol")
        != transition_protocol_reference()
    ):
        failures.append("schema_or_protocol")
    if (
        methodology.get("warmup_draws") != 60
        or methodology.get("development_fraction") != 0.7
        or methodology.get("inner_training_fraction") != 0.7
        or methodology.get("bootstrap_samples") != 2_000
        or methodology.get("bootstrap_block_draws") != 13
        or methodology.get("candidates")
        != list(TRANSITION_CANDIDATES)
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
        or profiles.get(LOTTO649, {}).get(
            "off_schedule_draws"
        )
        != 113
        or splits.get(SUPER, {}).get(
            "inner_validation_draws"
        )
        != 393
        or splits.get(SUPER, {}).get("holdout_draws") != 561
        or splits.get(LOTTO649, {}).get(
            "inner_validation_draws"
        )
        != 440
        or splits.get(LOTTO649, {}).get("holdout_draws") != 628
    ):
        failures.append("data_quality")
    rows = result.get("candidate_holdout", [])
    if {
        (row.get("game"), row.get("candidate"))
        for row in rows
    } != {
        (game, candidate)
        for game in (SUPER, LOTTO649)
        for candidate in TRANSITION_CANDIDATES
    }:
        failures.append("candidate_rows")
    if any(
        not 0
        <= row.get(
            "holm_adjusted_exact_null_one_sided_p_value",
            -1,
        )
        <= 1
        for row in rows
    ):
        failures.append("holm_family")
    decisions = result.get("decisions", {})
    if any(
        decisions.get(game, {}).get(
            "inner_selected_candidate"
        )
        != "consensus"
        or decisions.get(game, {}).get(
            "historical_promotion_eligible"
        )
        is not False
        or decisions.get(game, {}).get(
            "inner_selection_used_holdout"
        )
        is not False
        for game in (SUPER, LOTTO649)
    ):
        failures.append("selection")
    super_leader = next(
        (
            row
            for row in rows
            if row.get("game") == SUPER
            and row.get("candidate") == "lag1_520_lift"
        ),
        {},
    )
    lotto_leader = next(
        (
            row
            for row in rows
            if row.get("game") == LOTTO649
            and row.get("candidate") == "lag1_260_lift"
        ),
        {},
    )
    if (
        super_leader.get(
            "inner_validation_union_main_hits_delta_vs_consensus",
            0,
        )
        <= 0
        or super_leader.get(
            "inner_validation_best_main_hits_delta_vs_consensus",
            0,
        )
        >= 0
        or lotto_leader.get(
            "inner_validation_union_main_hits_delta_vs_consensus",
            0,
        )
        <= 0
        or lotto_leader.get(
            "inner_validation_best_main_hits_delta_vs_consensus",
            0,
        )
        >= 0
    ):
        failures.append("guardrail_rejection")
    forward = result.get(
        "future_forward_shadow_protocol", {}
    )
    if (
        len(forward.get("candidate_hash", "")) != 64
        or forward.get("registration_eligible") is not False
        or forward.get("promotion_eligible") is not False
        or set(forward.get("algorithms", {}).values())
        != {"consensus"}
    ):
        failures.append("forward_non_registration")
    conclusion = result.get("conclusion", {})
    if (
        conclusion.get("status")
        != "no_confirmed_transition_signal"
        or conclusion.get(
            "any_historical_promotion_eligible"
        )
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
            "transition signal 正式驗收失敗："
            + ", ".join(failures)
        )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="驗收條件轉移訊號的巢狀 holdout 研究"
    )
    parser.add_argument(
        "--tests-only",
        action="store_true",
        help="不重算正式歷史，只驗證測試與既有產物",
    )
    args = parser.parse_args(argv)
    stages = (
        (
            "lookahead_and_transition_state",
            (
                "tests/test_transition_signal.py",
                "tests/test_transition_signal_verify.py",
                "tests/test_agent_loop.py",
                "tests/test_mechanism_signal.py",
            ),
        ),
        (
            "nested_selection_and_multiple_testing",
            (
                "tests/test_transition_signal.py",
                "tests/test_transition_signal_verify.py",
                "tests/test_label_signal.py",
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
        print("[formal] transition signal study", flush=True)
        _run(
            [
                sys.executable,
                "-B",
                "-X",
                "utf8",
                "transition_signal.py",
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
    print("條件轉移訊號研究驗收通過。", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
