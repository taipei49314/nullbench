"""AI 辯論主號排名校準的正式產物與分階段驗收。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from engine.games import LOTTO649, POOL, SUPER
from research.debate_rank_calibration import CUTOFFS, EXPERIMENT_ID


BASE = Path(__file__).resolve().parent
FORMAL_RESULT = (
    BASE
    / "research"
    / "results"
    / "debate_rank_calibration.json"
)
PROTOCOL = BASE / "DEBATE_RANK_CALIBRATION_PROTOCOL.md"


def _run(command: list[str]) -> None:
    subprocess.run(command, cwd=BASE, check=True)


def verify_formal_result(result: dict) -> None:
    failures = []
    protocol = result.get("protocol", {})
    methodology = result.get("methodology", {})
    if (
        result.get("schema_version") != "1"
        or result.get("experiment_id") != EXPERIMENT_ID
    ):
        failures.append("schema")
    if (
        protocol.get("sha256")
        != hashlib.sha256(PROTOCOL.read_bytes()).hexdigest()
        or protocol.get("cutoffs") != list(CUTOFFS)
        or len(protocol.get("holm_family", ())) != 6
        or methodology.get("warmup_draws") != 60
        or methodology.get("development_fraction") != 0.7
        or methodology.get("bootstrap_samples") != 2_000
        or methodology.get("bootstrap_block_draws") != 13
    ):
        failures.append("protocol")

    expected_quality = {
        SUPER: {
            "draws": 1929,
            "first_date": "2008-01-24",
            "last_date": "2026-07-16",
            "development_draws": 1308,
            "holdout_draws": 561,
        },
        LOTTO649: {
            "draws": 2153,
            "first_date": "2007-01-02",
            "last_date": "2026-07-17",
            "development_draws": 1465,
            "holdout_draws": 628,
        },
    }
    expected_metrics = {
        SUPER: {
            "top_10_hits": {
                "observed_total_hits": 871,
                "mean_delta_vs_exact_null": -0.0263626981893236,
                "two_sided_p_value": 0.5485681562110853,
                "holm_adjusted_two_sided_p_value": 1.0,
            },
            "top_20_hits": {
                "observed_total_hits": 1763,
                "mean_delta_vs_exact_null": -0.015292241298433297,
                "two_sided_p_value": 0.7641001219851962,
                "holm_adjusted_two_sided_p_value": 1.0,
            },
            "top_30_hits": {
                "observed_total_hits": 2652,
                "mean_delta_vs_exact_null": -0.009569377990430249,
                "two_sided_p_value": 0.8224945796980032,
                "holm_adjusted_two_sided_p_value": 1.0,
            },
        },
        LOTTO649: {
            "top_10_hits": {
                "observed_total_hits": 803,
                "mean_delta_vs_exact_null": 0.05417262446379823,
                "two_sided_p_value": 0.1532404278913497,
                "holm_adjusted_two_sided_p_value": 0.7941357046343199,
            },
            "top_20_hits": {
                "observed_total_hits": 1570,
                "mean_delta_vs_exact_null": 0.051020408163265245,
                "two_sided_p_value": 0.26942517991064713,
                "holm_adjusted_two_sided_p_value": 1.0,
            },
            "top_30_hits": {
                "observed_total_hits": 2350,
                "mean_delta_vs_exact_null": 0.06856882880540743,
                "two_sided_p_value": 0.13235595077238665,
                "holm_adjusted_two_sided_p_value": 0.7941357046343199,
            },
        },
    }
    for game in (SUPER, LOTTO649):
        game_result = result.get("games", {}).get(game, {})
        quality = game_result.get("data_quality", {})
        profile = quality.get("profile", {})
        split = quality.get("split_profile", {})
        expected = expected_quality[game]
        if (
            quality.get("status") != "pass"
            or profile.get("draws") != expected["draws"]
            or profile.get("first_date") != expected["first_date"]
            or profile.get("last_date") != expected["last_date"]
            or profile.get("duplicate_dates") != 0
            or profile.get("duplicate_periods") != 0
            or profile.get("legal_draws") is not True
            or split.get("development_draws")
            != expected["development_draws"]
            or split.get("holdout_draws")
            != expected["holdout_draws"]
            or quality.get("ranking_rows")
            != expected["draws"] - 60
            or quality.get("ranking_size_min") != POOL[game]
            or quality.get("ranking_size_max") != POOL[game]
            or quality.get("unique_numbers_min") != POOL[game]
            or quality.get("proposal_appearances_total_min") != 90
            or quality.get("proposal_appearances_total_max") != 90
        ):
            failures.append(f"{game}_data_quality")
        holdout = game_result.get("holdout", {})
        for metric, expected_row in expected_metrics[game].items():
            row = holdout.get(metric, {})
            if (
                any(
                    row.get(key) != value
                    for key, value in expected_row.items()
                )
                or row.get("calibration") != "not_calibrated"
                or row.get("delta_ci_low", 0) >= 0
                or row.get("delta_ci_high", 0) <= 0
            ):
                failures.append(f"{game}_{metric}")

    super_contrast = (
        result.get("games", {})
        .get(SUPER, {})
        .get("holdout", {})
        .get("top_10_minus_next_10_hits", {})
    )
    if (
        super_contrast.get("mean_delta")
        != -0.0374331550802139
        or super_contrast.get("delta_ci_low")
        != -0.18542780748663104
        or super_contrast.get("delta_ci_high")
        != 0.10338680926916222
        or super_contrast.get("first_half_mean_delta") >= 0
        or super_contrast.get("second_half_mean_delta") <= 0
    ):
        failures.append("super_multiplicity_contrast")

    mapping = result.get("mapping_decision", {})
    if (
        mapping.get(
            "guarded_profit_high_support_mapping_supported"
        )
        is not False
        or mapping.get(
            "unconstrained_profit_high_support_mapping_supported"
        )
        is not False
        or mapping.get("negative_calibration_shadow_candidate")
        is not False
        or mapping.get("decision")
        != "retain_mapping_as_deterministic_tie_break_only"
    ):
        failures.append("mapping_decision")
    integrity = result.get("records_integrity", {})
    if (
        integrity.get("unchanged") is not True
        or integrity.get("before_sha256")
        != integrity.get("after_sha256")
    ):
        failures.append("records_integrity")
    if failures:
        raise RuntimeError(
            "AI 辯論主號排名校準正式驗收失敗："
            + ", ".join(failures)
        )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="驗收 AI 辯論主號排名校準研究"
    )
    parser.add_argument(
        "--tests-only",
        action="store_true",
        help="不重算正式歷史，只驗證測試與既有產物",
    )
    args = parser.parse_args(argv)
    print("[gate-test] temporal_exact_null_and_mapping", flush=True)
    _run(
        [
            sys.executable,
            "-B",
            "-X",
            "utf8",
            "-m",
            "pytest",
            "tests/test_debate_rank_calibration.py",
            "tests/test_max_coverage.py",
            "tests/test_label_signal.py",
            "tests/test_profit_portfolio_forward.py",
            "-q",
            "-p",
            "no:cacheprovider",
        ]
    )
    if not args.tests_only:
        print("[formal] debate rank calibration", flush=True)
        _run(
            [
                sys.executable,
                "-B",
                "-X",
                "utf8",
                "debate_rank_calibration.py",
            ]
        )
    verify_formal_result(
        json.loads(FORMAL_RESULT.read_text(encoding="utf-8"))
    )
    print("[formal] artifact verified", flush=True)
    _run(["git", "diff", "--check"])
    print("AI 辯論主號排名校準驗收通過。", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
