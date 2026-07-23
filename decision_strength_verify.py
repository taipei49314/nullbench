"""號碼決策強度稽核的獨立計算、產物與測試驗收。"""
from __future__ import annotations

import argparse
from math import comb, fsum
import json
from pathlib import Path
import subprocess
import sys

from engine.agent_loop import canonical_hash
from engine.games import LOTTO649, SUPER
from research.decision_strength import (
    EXPERIMENT_ID,
    _hypergeometric_variance,
    run_decision_strength_audit,
)


BASE = Path(__file__).resolve().parent
FORMAL_RESULT = (
    BASE / "research" / "results" / "decision_strength.json"
)


def _run(command: list[str]) -> None:
    subprocess.run(command, cwd=BASE, check=True)


def _exact_hypergeometric_moments(
    population: int,
    selected: int,
    draws: int,
) -> tuple[float, float]:
    denominator = comb(population, draws)
    rows = []
    for hits in range(
        max(0, draws - (population - selected)),
        min(draws, selected) + 1,
    ):
        probability = (
            comb(selected, hits)
            * comb(population - selected, draws - hits)
            / denominator
        )
        rows.append((hits, probability))
    mean = fsum(hits * probability for hits, probability in rows)
    variance = fsum(
        probability * (hits - mean) ** 2
        for hits, probability in rows
    )
    return mean, variance


def verify_formal_result(result: dict) -> None:
    failures = []
    payload = {
        key: value
        for key, value in result.items()
        if key != "audit_hash"
    }
    if (
        result.get("schema_version") != "1"
        or result.get("experiment_id") != EXPERIMENT_ID
        or result.get("audit_hash") != canonical_hash(payload)
    ):
        failures.append("schema_or_hash")
    try:
        rebuilt = run_decision_strength_audit(BASE)
    except (KeyError, OSError, TypeError, ValueError) as exc:
        raise RuntimeError(
            "號碼決策強度來源無法重建"
        ) from exc
    if result != rebuilt:
        failures.append("deterministic_rebuild")

    for population, selected, draws in (
        (38, 30, 6),
        (49, 30, 6),
        (8, 5, 1),
    ):
        _, exact_variance = _exact_hypergeometric_moments(
            population,
            selected,
            draws,
        )
        formula_variance = _hypergeometric_variance(
            population=population,
            selected=selected,
            draws=draws,
        )
        if abs(exact_variance - formula_variance) > 1e-14:
            failures.append(
                f"hypergeometric_variance_{population}"
            )

    games = result.get("games", {})
    if set(games) != {SUPER, LOTTO649}:
        failures.append("games")
    else:
        for game, row in games.items():
            main = row.get("main", {})
            maximum = main.get("checkpoint_detection", {}).get(
                "832", {}
            )
            if (
                row.get("nonuniform_main_weight", 1) >= 0.00001
                or main.get(
                    "model_implied_expected_hit_lift", 1
                )
                >= maximum.get(
                    "approx_minimum_detectable_mean_lift", 0
                )
                or row.get("material_at_maximum_checkpoint")
                is not False
            ):
                failures.append(f"strength_{game}")
    diagnosis = result.get("diagnosis", {})
    decision = result.get("decision", {})
    integrity = result.get("records_integrity", {})
    if (
        diagnosis.get(
            "uniform_is_best_in_all_scored_dimensions"
        )
        is not True
        or diagnosis.get(
            "model_lift_below_max_checkpoint_detectability"
        )
        is not True
        or diagnosis.get("top_k_amplification_present") is not True
        or decision.get("status")
        != "retain_existing_future_shadow_only"
        or decision.get("launch_additional_label_variant") is not False
        or decision.get("change_existing_frozen_numbers") is not False
    ):
        failures.append("decision")
    if (
        integrity.get("unchanged") is not True
        or integrity.get("before_sha256")
        != integrity.get("after_sha256")
    ):
        failures.append("records_integrity")
    if failures:
        raise RuntimeError(
            "號碼決策強度驗收失敗：" + ", ".join(failures)
        )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="驗收號碼決策強度稽核"
    )
    parser.add_argument(
        "--tests-only",
        action="store_true",
        help="只跑測試並驗證目前產物",
    )
    args = parser.parse_args(argv)
    print("[gate-test] decision strength", flush=True)
    _run(
        [
            sys.executable,
            "-B",
            "-X",
            "utf8",
            "-m",
            "pytest",
            "tests/test_decision_strength.py",
            "tests/test_probability_stacking.py",
            "-q",
            "-p",
            "no:cacheprovider",
        ]
    )
    if not args.tests_only:
        print("[formal] rebuild decision strength", flush=True)
        _run(
            [
                sys.executable,
                "-B",
                "-X",
                "utf8",
                "decision_strength.py",
            ]
        )
    result = json.loads(
        FORMAL_RESULT.read_text(encoding="utf-8")
    )
    verify_formal_result(result)
    print("[formal] artifact and exact moments verified", flush=True)
    _run(["git", "diff", "--check"])
    print("號碼決策強度稽核驗收通過。", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
