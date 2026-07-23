"""公平零模型安全機率研究的正式產物與分階段驗收。"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import subprocess
import sys

from engine.agent_loop import verify_replay
from engine.games import (
    LOTTO649,
    PICK_N,
    POOL,
    SPECIAL_POOL,
    SUPER,
)
from research.null_safe_probability import (
    ACTIVATION_E_THRESHOLD,
    EXPERIMENT_ID,
    FORWARD_EXPERIMENT_ID,
    PROTOCOL_CONFIG,
    PROTOCOL_HASH,
    SENSITIVITY_THRESHOLDS,
    validate_e_process_state,
    validate_forward_candidate,
)


BASE = Path(__file__).resolve().parent
FORMAL_RESULT = (
    BASE
    / "research"
    / "results"
    / "null_safe_probability.json"
)
SOURCE_LEDGERS = {
    SUPER: BASE / "simulation" / "results" / "super.jsonl",
    LOTTO649: (
        BASE / "simulation" / "results" / "lotto649.jsonl"
    ),
}


def _run(command: list[str]) -> None:
    subprocess.run(command, cwd=BASE, check=True)


def verify_formal_result(result: dict) -> None:
    failures = []
    quality = result.get("data_quality", {})
    verification = quality.get("ledger_verification", {})
    summaries = result.get("prequential_summary", {})
    models = result.get("final_models", {})
    conclusion = result.get("conclusion", {})
    integrity = result.get("records_integrity", {})
    candidate = result.get("future_forward_shadow_candidate")

    if (
        result.get("schema_version") != "1"
        or result.get("experiment_id") != EXPERIMENT_ID
        or result.get("methodology", {}).get("protocol_hash")
        != PROTOCOL_HASH
        or any(
            result.get("methodology", {}).get(key) != value
            for key, value in PROTOCOL_CONFIG.items()
        )
    ):
        failures.append("schema_or_protocol")

    expected_sources = {}
    for game, path in SOURCE_LEDGERS.items():
        first = None
        last = None
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                event = json.loads(line)
                first = first or event
                last = event
        if first is None or last is None:
            raise RuntimeError(f"{game} 正式 ledger 為空")
        replay = verify_replay(path)
        expected_sources[game] = {
            **replay,
            "first": first["reveal"]["date"],
            "last": last["reveal"]["date"],
        }
    if (
        quality.get("status") != "pass"
        or quality.get("chronology") != "strictly_increasing"
        or quality.get("duplicate_periods") != 0
        or quality.get("likelihood")
        != "normalized_unordered_subset_and_categorical"
        or quality.get("e_process_complexity") != "O(draws)"
    ):
        failures.append("data_quality_contract")
    for game, expected in expected_sources.items():
        row = verification.get(game, {})
        summary = summaries.get(game, {})
        if (
            row.get("lines") != expected["lines"]
            or row.get("ledger_sha256")
            != expected["ledger_sha256"]
            or row.get("last_event_hash")
            != expected["last_event_hash"]
            or summary.get("draws") != expected["lines"]
            or summary.get("first_date") != expected["first"]
            or summary.get("last_date") != expected["last"]
        ):
            failures.append(f"source_{game}")

    stream_rows = [
        (SUPER, "main"),
        (SUPER, "special"),
        (LOTTO649, "main"),
    ]
    for game, dimension in stream_rows:
        row = summaries.get(game, {}).get(dimension, {})
        model = models.get(game, {})
        prefix = "main" if dimension == "main" else "special"
        try:
            existing_regret = float(
                row["existing_mixture_regret_vs_uniform"]
            )
            safe_regret = float(
                row["null_safe_regret_vs_uniform"]
            )
            improvement = float(
                row["null_safe_improvement_vs_existing"]
            )
            uniform_loss = float(row["uniform_log_loss"])
            cumulative_log_lr = float(
                row[
                    "cumulative_log_likelihood_ratio_vs_uniform"
                ]
            )
            draws = int(row["draws"])
            maximum_e = float(row["maximum_restart_e_value"])
            final_e = float(row["final_restart_e_value"])
            state = validate_e_process_state(
                model[f"{prefix}_e_process"]
            )
        except (KeyError, TypeError, ValueError):
            failures.append(f"score_contract_{game}_{dimension}")
            continue
        if (
            not all(
                math.isfinite(value)
                for value in (
                    existing_regret,
                    safe_regret,
                    improvement,
                    uniform_loss,
                    cumulative_log_lr,
                    maximum_e,
                    final_e,
                )
            )
            or draws != expected_sources[game]["lines"]
            or not math.isclose(
                uniform_loss,
                (
                    math.log(math.comb(POOL[game], PICK_N))
                    if dimension == "main"
                    else math.log(SPECIAL_POOL[SUPER])
                ),
                rel_tol=0.0,
                abs_tol=1e-12,
            )
            or not math.isclose(
                existing_regret,
                -cumulative_log_lr / draws,
                rel_tol=0.0,
                abs_tol=1e-12,
            )
            or existing_regret <= 0
            or abs(safe_regret) > 1e-12
            or not math.isclose(
                improvement,
                existing_regret - safe_regret,
                rel_tol=0.0,
                abs_tol=1e-15,
            )
            or improvement <= 0
            or maximum_e >= ACTIVATION_E_THRESHOLD
            or row.get("activation_periods") != 0
            or row.get("sensitivity_activation_periods")
            != {
                str(threshold): 0
                for threshold in SENSITIVITY_THRESHOLDS
            }
            or state["sequence"] != row.get("draws")
            or model.get(f"{prefix}_gate_active") is not False
        ):
            failures.append(f"null_safe_result_{game}_{dimension}")

    if (
        conclusion.get("status")
        != "candidate_ready_future_shadow"
        or conclusion.get("historical_promotion_eligible") is not False
        or not isinstance(candidate, dict)
        or candidate.get("experiment_id") != FORWARD_EXPERIMENT_ID
        or not isinstance(candidate.get("candidate_hash"), str)
        or len(candidate["candidate_hash"]) != 64
        or candidate.get("fitted_through")
        != {
            game: expected_sources[game]["last"]
            for game in (SUPER, LOTTO649)
        }
    ):
        failures.append("future_only_decision")
    else:
        try:
            validate_forward_candidate(candidate)
        except (TypeError, ValueError):
            failures.append("forward_candidate")

    if (
        integrity.get("unchanged") is not True
        or integrity.get("after_sha256")
        != integrity.get("before_sha256")
        or not isinstance(integrity.get("before_sha256"), str)
        or len(integrity["before_sha256"]) != 64
    ):
        failures.append("records_integrity")

    if failures:
        raise RuntimeError(
            "null-safe 機率正式驗收失敗：" + ", ".join(failures)
        )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="驗收公平零模型安全機率閘門與 future-only 邊界"
    )
    parser.add_argument(
        "--tests-only",
        action="store_true",
        help="不重算完整歷史，只驗證測試與既有正式產物",
    )
    args = parser.parse_args(argv)
    print("[gate-test] null-safe probability contracts", flush=True)
    _run(
        [
            sys.executable,
            "-B",
            "-X",
            "utf8",
            "-m",
            "pytest",
            "tests/test_null_safe_probability.py",
            "-q",
            "-p",
            "no:cacheprovider",
        ]
    )
    if not args.tests_only:
        print("[formal] rebuild null-safe probability", flush=True)
        _run(
            [
                sys.executable,
                "-B",
                "-X",
                "utf8",
                "null_safe_probability.py",
            ]
        )
    verify_formal_result(
        json.loads(FORMAL_RESULT.read_text(encoding="utf-8"))
    )
    print("[formal] artifact verified", flush=True)
    _run(["git", "diff", "--check"])
    print("公平零模型安全機率研究驗收通過。", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
