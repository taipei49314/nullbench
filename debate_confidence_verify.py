"""AI 辯論逐期信心校準的正式產物與分階段驗收。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from engine.games import LOTTO649, POOL, SUPER
from research.debate_confidence import (
    CUTOFFS,
    EXPERIMENT_ID,
    PRIMARY_COMPONENTS,
    SAFE_LAMBDAS,
)


BASE = Path(__file__).resolve().parent
FORMAL_RESULT = (
    BASE / "research" / "results" / "debate_confidence.json"
)
PROTOCOL = BASE / "DEBATE_CONFIDENCE_PROTOCOL.md"


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
        or len(protocol.get("holm_family", ())) != 8
        or len(
            protocol.get("sequential_safe_holm_family", ())
        )
        != 8
        or methodology.get("warmup_draws") != 60
        or methodology.get("development_fraction") != 0.7
        or methodology.get("primary_components")
        != list(PRIMARY_COMPONENTS)
        or methodology.get("low_quantile") != 0.25
        or methodology.get("high_quantile") != 0.75
        or methodology.get("bootstrap_samples") != 2_000
        or methodology.get("bootstrap_block_draws") != 13
        or methodology.get("sequential_safe_lambdas")
        != list(SAFE_LAMBDAS)
        or not methodology.get("post_unblinding_qa_amendment")
    ):
        failures.append("protocol")

    expected_quality = {
        SUPER: {
            "draws": 1929,
            "first_date": "2008-01-24",
            "last_date": "2026-07-16",
            "development": 1308,
            "holdout": 561,
            "high_draws": 120,
            "low_draws": 151,
            "high_share": 0.21390374331550802,
            "low_share": 0.26916221033868093,
            "mean": -0.08248839740847977,
            "low_threshold": -0.6282412184188131,
            "high_threshold": 0.6305917474575089,
        },
        LOTTO649: {
            "draws": 2153,
            "first_date": "2007-01-02",
            "last_date": "2026-07-17",
            "development": 1465,
            "holdout": 628,
            "high_draws": 173,
            "low_draws": 146,
            "high_share": 0.2754777070063694,
            "low_share": 0.23248407643312102,
            "mean": 0.04412817805883222,
            "low_threshold": -0.6295636748258325,
            "high_threshold": 0.6042224830958247,
        },
    }
    expected_metrics = {
        SUPER: {
            "top_10_hits": {
                "high_total_hits": 183,
                "low_total_hits": 247,
                "high_delta_vs_null": -0.053947368421052744,
                "high_minus_low": -0.11076158940397351,
                "high_vs_null_one_sided_p_value": 0.7361610422174041,
                "high_minus_low_one_sided_p_value": 0.8169693924486962,
                "high_vs_null_ci_low": -0.21866060371517024,
                "high_minus_low_ci_low": -0.31023103978115,
                "safe_high_vs_null_log_e": -1.8653392929098571,
                "safe_high_minus_low_log_e": -2.7276743386686686,
            },
            "top_30_hits": {
                "high_total_hits": 561,
                "low_total_hits": 711,
                "high_delta_vs_null": -0.0618421052631577,
                "high_minus_low": -0.033609271523179274,
                "high_vs_null_one_sided_p_value": 0.7827061855754359,
                "high_minus_low_one_sided_p_value": 0.6177520570443619,
                "high_vs_null_ci_low": -0.24045799515993616,
                "high_minus_low_ci_low": -0.2842351040862492,
                "safe_high_vs_null_log_e": -1.8718719173056595,
                "safe_high_minus_low_log_e": -1.9326525855260668,
            },
        },
        LOTTO649: {
            "top_10_hits": {
                "high_total_hits": 223,
                "low_total_hits": 174,
                "high_delta_vs_null": 0.06452754512209502,
                "high_minus_low": 0.09723651912265407,
                "high_vs_null_one_sided_p_value": 0.1923514916239669,
                "high_minus_low_one_sided_p_value": 0.17763562777307537,
                "high_vs_null_ci_low": -0.05490814949461575,
                "high_minus_low_ci_low": -0.07544867280028643,
                "safe_high_vs_null_log_e": -0.6046520666341297,
                "safe_high_minus_low_log_e": -0.7346216911216454,
            },
            "top_30_hits": {
                "high_total_hits": 642,
                "low_total_hits": 538,
                "high_delta_vs_null": 0.03751327120443548,
                "high_minus_low": 0.026051152110222464,
                "high_vs_null_one_sided_p_value": 0.34403388409968755,
                "high_minus_low_one_sided_p_value": 0.4189905809044193,
                "high_vs_null_ci_low": -0.11503537990248955,
                "high_minus_low_ci_low": -0.22610914357616368,
                "safe_high_vs_null_log_e": -1.239951483444814,
                "safe_high_minus_low_log_e": -1.8144013804809076,
            },
        },
    }
    for game in (SUPER, LOTTO649):
        game_result = result.get("games", {}).get(game, {})
        quality = game_result.get("data_quality", {})
        profile = quality.get("profile", {})
        split = quality.get("split_profile", {})
        checks = quality.get("distribution_checks", {})
        holdout_groups = quality.get(
            "holdout_feature_profile", {}
        ).get("groups", {})
        model = game_result.get("confidence_model", {})
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
            != expected["development"]
            or split.get("holdout_draws") != expected["holdout"]
            or quality.get("feature_rows") != expected["draws"] - 60
            or quality.get("ranking_size_min") != POOL[game]
            or quality.get("ranking_size_max") != POOL[game]
            or quality.get("proposals_min") != 15
            or quality.get("candidate_scores_min") != 15
            or quality.get("critiques_min") != 60
            or quality.get("unique_critique_pairs_min") != 60
            or quality.get("proposal_appearances_total_min") != 90
            or checks.get("high_share") != expected["high_share"]
            or checks.get("low_share") != expected["low_share"]
            or holdout_groups.get("high", {}).get("draws")
            != expected["high_draws"]
            or holdout_groups.get("low", {}).get("draws")
            != expected["low_draws"]
            or checks.get("holdout_confidence_mean")
            != expected["mean"]
            or checks.get("distribution_gate_passed") is not True
            or model.get("low_threshold")
            != expected["low_threshold"]
            or model.get("high_threshold")
            != expected["high_threshold"]
        ):
            failures.append(f"{game}_data_quality")
        for metric, expected_row in expected_metrics[game].items():
            row = game_result.get("holdout", {}).get(metric, {})
            bootstrap = row.get("block_bootstrap", {})
            safe = row.get("sequential_safe", {})
            observed = {
                key: row.get(key)
                for key in (
                    "high_total_hits",
                    "low_total_hits",
                    "high_delta_vs_null",
                    "high_minus_low",
                    "high_vs_null_one_sided_p_value",
                    "high_minus_low_one_sided_p_value",
                )
            }
            observed.update(
                {
                    "high_vs_null_ci_low": bootstrap.get(
                        "high_vs_null_ci_low"
                    ),
                    "high_minus_low_ci_low": bootstrap.get(
                        "high_minus_low_ci_low"
                    ),
                    "safe_high_vs_null_log_e": safe.get(
                        "high_vs_null", {}
                    ).get("mixture_log_e_value"),
                    "safe_high_minus_low_log_e": safe.get(
                        "high_minus_low", {}
                    ).get("mixture_log_e_value"),
                }
            )
            if (
                observed != expected_row
                or row.get(
                    "holm_high_vs_null_one_sided_p_value"
                )
                != 1.0
                or row.get(
                    "holm_high_minus_low_one_sided_p_value"
                )
                != 1.0
                or any(
                    safe.get(contrast, {}).get(
                        "anytime_valid_p_value"
                    )
                    != 1.0
                    or safe.get(contrast, {}).get(
                        "holm_anytime_valid_p_value"
                    )
                    != 1.0
                    for contrast in (
                        "high_vs_null",
                        "high_minus_low",
                    )
                )
                or row.get("candidate_gate_passed") is not False
                or not row.get("candidate_gate_failures")
                or not {
                    "holdout_high_vs_null_safe_holm",
                    "holdout_high_minus_low_safe_holm",
                }
                <= set(row.get("candidate_gate_failures", ()))
            ):
                failures.append(f"{game}_{metric}")

    conclusion = result.get("conclusion", {})
    if (
        result.get("future_forward_shadow_candidates") != []
        or conclusion.get("status")
        != "stop_new_historical_confidence_hypotheses"
        or conclusion.get("historical_gate_passed") is not False
        or conclusion.get("candidate_count") != 0
        or conclusion.get("decision")
        != "wait_for_existing_forward_evidence"
    ):
        failures.append("decision")
    integrity = result.get("records_integrity", {})
    if (
        integrity.get("unchanged") is not True
        or integrity.get("before_sha256")
        != integrity.get("after_sha256")
    ):
        failures.append("records_integrity")
    if failures:
        raise RuntimeError(
            "AI 辯論逐期信心正式驗收失敗："
            + ", ".join(failures)
        )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="驗收 AI 辯論逐期信心校準研究"
    )
    parser.add_argument(
        "--tests-only",
        action="store_true",
        help="不重算正式歷史，只驗證測試與既有產物",
    )
    args = parser.parse_args(argv)
    print("[gate-test] temporal_confidence_and_exact_null", flush=True)
    _run(
        [
            sys.executable,
            "-B",
            "-X",
            "utf8",
            "-m",
            "pytest",
            "tests/test_debate_confidence.py",
            "tests/test_debate_rank_calibration.py",
            "tests/test_council_quality.py",
            "tests/test_max_coverage.py",
            "-q",
            "-p",
            "no:cacheprovider",
        ]
    )
    if not args.tests_only:
        print("[formal] debate confidence study", flush=True)
        _run(
            [
                sys.executable,
                "-B",
                "-X",
                "utf8",
                "debate_confidence.py",
            ]
        )
    verify_formal_result(
        json.loads(FORMAL_RESULT.read_text(encoding="utf-8"))
    )
    print("[formal] artifact verified", flush=True)
    _run(["git", "diff", "--check"])
    print("AI 辯論逐期信心校準驗收通過。", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
