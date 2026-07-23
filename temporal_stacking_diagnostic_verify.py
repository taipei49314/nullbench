"""時間自適應機率 stacking 診斷的正式產物與分階段驗收。"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys

from engine.agent_loop import verify_replay
from engine.games import LOTTO649, SUPER
from research.temporal_stacking_diagnostic import (
    EXPERIMENT_ID,
    METHODS,
    PROTOCOL_FILE,
    STREAMS,
    validate_result,
)


BASE = Path(__file__).resolve().parent
FORMAL_RESULT = (
    BASE
    / "research"
    / "results"
    / "temporal_stacking_diagnostic.json"
)
SOURCE_LEDGERS = {
    SUPER: BASE / "simulation" / "results" / "super.jsonl",
    LOTTO649: (
        BASE / "simulation" / "results" / "lotto649.jsonl"
    ),
}


def _run(command: list[str]) -> None:
    subprocess.run(command, cwd=BASE, check=True)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_formal_result(result: dict) -> None:
    failures = []
    try:
        validate_result(result)
    except (KeyError, TypeError, ValueError):
        failures.append("artifact_contract")
    protocol = result.get("protocol", {})
    quality = result.get("data_quality", {})
    if (
        result.get("experiment_id") != EXPERIMENT_ID
        or protocol.get("protocol_file") != PROTOCOL_FILE
        or protocol.get("protocol_file_sha256")
        != _file_sha256(BASE / PROTOCOL_FILE)
    ):
        failures.append("protocol_file")
    verification = quality.get("ledger_verification", {})
    for game, path in SOURCE_LEDGERS.items():
        replay = verify_replay(path)
        with path.open(encoding="utf-8") as handle:
            events = [
                json.loads(line)
                for line in handle
                if line.strip()
            ]
        observed = verification.get(game, {})
        if (
            not events
            or observed.get("lines") != replay["lines"]
            or observed.get("ledger_sha256")
            != replay["ledger_sha256"]
            or observed.get("last_event_hash")
            != replay["last_event_hash"]
            or quality.get("source_first_dates", {}).get(game)
            != events[0]["reveal"]["date"]
            or quality.get("source_last_dates", {}).get(game)
            != events[-1]["reveal"]["date"]
        ):
            failures.append(f"source_{game}")
    rows = result.get("diagnostic_rows", [])
    by = {
        (row.get("stream"), row.get("method")): row
        for row in rows
    }
    if set(by) != {
        (stream, method)
        for stream in STREAMS
        for method in METHODS
    }:
        failures.append("fixed_family")
    else:
        for stream in STREAMS:
            uniform = by[(stream, "uniform")]
            current = by[
                (stream, "current_cumulative_marginal")
            ]
            subset = by[(stream, "subset_cumulative")]
            if (
                not math.isclose(
                    float(uniform["mean_regret_nats"]),
                    0.0,
                    rel_tol=0.0,
                    abs_tol=1e-12,
                )
                or float(current["mean_regret_nats"]) <= 0
                or float(subset["mean_regret_nats"]) <= 0
            ):
                failures.append(f"uniform_gap_{stream}")
        for stream in ("super_main", "lotto649_main"):
            if (
                float(
                    by[(stream, "subset_cumulative")][
                        "mean_regret_nats"
                    ]
                )
                >= float(
                    by[
                        (
                            stream,
                            "current_cumulative_marginal",
                        )
                    ]["mean_regret_nats"]
                )
            ):
                failures.append(f"subset_harm_reduction_{stream}")
        current_special = by[
            ("super_special", "current_cumulative_marginal")
        ]["mean_regret_nats"]
        subset_special = by[
            ("super_special", "subset_cumulative")
        ]["mean_regret_nats"]
        if not math.isclose(
            float(current_special),
            float(subset_special),
            rel_tol=0.0,
            abs_tol=1e-15,
        ):
            failures.append("special_score_equivalence")
    conclusion = result.get("conclusion", {})
    if (
        conclusion.get("status")
        != "retain_existing_null_safe_protocol"
        or conclusion.get("historical_promotion_eligible")
        is not False
        or conclusion.get("watcher_integration_allowed")
        is not False
        or conclusion.get("descriptive_minimax_method")
        != "subset_cumulative"
        or conclusion.get("qualified_future_challengers") != []
        or conclusion.get("selected_future_challenger") is not None
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
            "時間自適應 stacking 正式驗收失敗："
            + ", ".join(failures)
        )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="驗收時間自適應機率 stacking 診斷"
    )
    parser.add_argument(
        "--tests-only",
        action="store_true",
        help="不重算完整歷史，只驗證測試與既有正式產物",
    )
    args = parser.parse_args(argv)
    print("[gate-test] temporal stacking contracts", flush=True)
    _run(
        [
            sys.executable,
            "-B",
            "-X",
            "utf8",
            "-m",
            "pytest",
            "tests/test_temporal_stacking_diagnostic.py",
            "tests/test_temporal_stacking_diagnostic_verify.py",
            "-q",
            "-p",
            "no:cacheprovider",
        ]
    )
    if not args.tests_only:
        print("[formal] rebuild temporal stacking diagnostic", flush=True)
        _run(
            [
                sys.executable,
                "-B",
                "-X",
                "utf8",
                "temporal_stacking_diagnostic.py",
            ]
        )
    verify_formal_result(
        json.loads(FORMAL_RESULT.read_text(encoding="utf-8"))
    )
    print("[formal] artifact verified", flush=True)
    _run(["git", "diff", "--check"])
    print("時間自適應機率 stacking 診斷驗收通過。", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
