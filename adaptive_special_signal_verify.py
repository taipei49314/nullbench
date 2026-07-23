"""共同第二區自適應訊號研究的正式產物與分階段驗收。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from research.adaptive_special_signal import EXPERIMENT_ID, METHODS
from research.profit_portfolio_forward import PORTFOLIO_IDS


BASE = Path(__file__).resolve().parent
FORMAL_RESULT = (
    BASE / "research" / "results" / "adaptive_special_signal.json"
)
PROTOCOL = BASE / "ADAPTIVE_SPECIAL_PROTOCOL.md"


def _run(command: list[str]) -> None:
    subprocess.run(command, cwd=BASE, check=True)


def verify_formal_result(result: dict) -> None:
    failures = []
    protocol = result.get("protocol", {})
    methodology = result.get("methodology", {})
    quality = result.get("data_quality", {})
    profile = quality.get("profile", {})
    split = quality.get("split_profile", {})
    if (
        result.get("schema_version") != "1"
        or result.get("experiment_id") != EXPERIMENT_ID
    ):
        failures.append("schema")
    if (
        protocol.get("candidate_methods") != list(METHODS)
        or protocol.get("sha256")
        != hashlib.sha256(PROTOCOL.read_bytes()).hexdigest()
        or methodology.get("warmup_draws") != 60
        or methodology.get("development_fraction") != 0.7
        or methodology.get("inner_training_fraction") != 0.7
        or methodology.get("bootstrap_samples") != 2_000
        or methodology.get("bootstrap_block_draws") != 13
        or methodology.get("five_ticket_cost_ntd") != 500
    ):
        failures.append("protocol")
    if (
        quality.get("status") != "pass"
        or profile.get("draws") != 1929
        or profile.get("first_date") != "2008-01-24"
        or profile.get("last_date") != "2026-07-16"
        or profile.get("duplicate_dates") != 0
        or profile.get("duplicate_periods") != 0
        or profile.get("legal_draws") is not True
        or split.get("inner_validation_draws") != 393
        or split.get("holdout_draws") != 561
    ):
        failures.append("data_quality")
    inner = result.get("inner_validation", {})
    inner_selected = inner.get("results", {}).get(
        "rolling_104", {}
    )
    if (
        inner.get("status") != "candidate_selected"
        or inner.get("selected_method") != "rolling_104"
        or inner.get("eligible_methods")
        != [
            "rolling_104",
            "rolling_208",
            "ewma_half_life_52",
            "ewma_half_life_104",
        ]
        or inner_selected.get("special_hits") != 54
        or set(inner_selected.get("portfolios", {}))
        != set(PORTFOLIO_IDS)
        or any(
            row.get("strict_profit_delta", 0) <= 0
            for row in inner_selected.get(
                "portfolios", {}
            ).values()
        )
    ):
        failures.append("inner_selection")
    holdout = result.get("holdout", {})
    selected = holdout.get("result", {})
    portfolios = selected.get("portfolios", {})
    if (
        holdout.get("status")
        != "opened_for_inner_selected_candidate"
        or holdout.get("selected_method") != "rolling_104"
        or holdout.get("historical_gate_passed") is not False
        or selected.get("draws") != 561
        or selected.get("special_hits") != 69
        or selected.get("special_hit_rate")
        != 0.12299465240641712
        or selected.get("holm_adjusted_one_sided_p_values")
        != {
            "guarded_profit:strict_profit": 0.4860129001317546,
            "unconstrained_profit:strict_profit": 0.4860129001317546,
            "special_hit": 0.5761564865439045,
        }
        or set(portfolios) != set(PORTFOLIO_IDS)
        or any(
            row.get("strict_profit_delta", 0) <= 0
            or row.get("strict_profit_delta_ci_low", 0) >= 0
            for row in portfolios.values()
        )
    ):
        failures.append("holdout")
    if (
        result.get("future_forward_shadow_candidate") is not None
        or result.get("conclusion", {}).get("status")
        != "retain_existing_common_special_methods"
        or result.get("conclusion", {}).get(
            "historical_gate_passed"
        )
        is not False
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
            "共同第二區自適應正式驗收失敗："
            + ", ".join(failures)
        )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="驗收共同第二區自適應訊號研究"
    )
    parser.add_argument(
        "--tests-only",
        action="store_true",
        help="不重算正式歷史，只驗證測試與既有產物",
    )
    args = parser.parse_args(argv)
    print("[gate-test] temporal_and_selection_contract", flush=True)
    _run(
        [
            sys.executable,
            "-B",
            "-X",
            "utf8",
            "-m",
            "pytest",
            "tests/test_adaptive_special_signal.py",
            "tests/test_mechanism_signal.py",
            "tests/test_profit_portfolio_forward.py",
            "-q",
            "-p",
            "no:cacheprovider",
        ]
    )
    if not args.tests_only:
        print("[formal] adaptive special study", flush=True)
        _run(
            [
                sys.executable,
                "-B",
                "-X",
                "utf8",
                "adaptive_special_signal.py",
            ]
        )
    verify_formal_result(
        json.loads(FORMAL_RESULT.read_text(encoding="utf-8"))
    )
    print("[formal] artifact verified", flush=True)
    _run(["git", "diff", "--check"])
    print("共同第二區自適應訊號研究驗收通過。", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
