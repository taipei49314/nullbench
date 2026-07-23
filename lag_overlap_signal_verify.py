"""相鄰期重複數完整 subset proper-score 正式驗收。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from research.gates import tree_sha256
from research.lag_overlap_signal import (
    EXPERIMENT_ID,
    PROTOCOL_FILE,
    run_lag_overlap_signal,
    validate_result,
)


BASE = Path(__file__).resolve().parent
FORMAL_RESULT = (
    BASE / "research" / "results" / "lag_overlap_signal.json"
)


def _run(command: list[str]) -> None:
    subprocess.run(command, cwd=BASE, check=True)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_formal_result(
    result: dict,
    *,
    verify_live_sources: bool = True,
) -> None:
    failures = []
    try:
        validate_result(result)
    except (KeyError, TypeError, ValueError):
        failures.append("artifact_contract")
    protocol = result.get("protocol", {})
    if (
        result.get("experiment_id") != EXPERIMENT_ID
        or protocol.get("protocol_file") != PROTOCOL_FILE
        or protocol.get("protocol_file_sha256")
        != _file_sha256(BASE / PROTOCOL_FILE)
    ):
        failures.append("protocol_file")

    if verify_live_sources:
        try:
            recomputed = run_lag_overlap_signal(base=BASE)
        except (KeyError, OSError, TypeError, ValueError, RuntimeError):
            failures.append("live_recompute")
        else:
            if result != recomputed:
                failures.append("live_recompute")

    conclusion = result.get("conclusion", {})
    if (
        conclusion.get("status")
        != "retain_existing_null_safe_protocol"
        or conclusion.get("historical_promotion_eligible")
        is not False
        or conclusion.get("future_challenger_design_allowed")
        is not False
        or conclusion.get("watcher_integration_allowed") is not False
        or conclusion.get("selected_future_challenger") is not None
        or conclusion.get("frontier_v2_inclusion_required")
        is not True
    ):
        failures.append("decision")
    diagnostics = result.get("diagnostics", {})
    for game in ("super", "lotto649"):
        row = diagnostics.get(game, {})
        if (
            row.get("raw_mean_regret_nats", 0) <= 0
            or row.get("raw_bootstrap_95_low", 0) <= 0
            or row.get("safe_mean_regret_nats") != 0
            or row.get("gate_activation_count") != 0
            or row.get("final_gate_active") is not False
            or row.get("future_challenger_qualified") is not False
        ):
            failures.append(f"decision_{game}")
    integrity = result.get("records_integrity", {})
    if (
        integrity.get("unchanged") is not True
        or integrity.get("before_sha256")
        != integrity.get("after_sha256")
        or (
            verify_live_sources
            and integrity.get("after_sha256")
            != tree_sha256(BASE / "records")
        )
    ):
        failures.append("records_integrity")
    if failures:
        raise RuntimeError(
            "相鄰期重複數正式驗收失敗："
            + ", ".join(sorted(set(failures)))
        )


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="驗收相鄰期重複數完整 subset proper score"
    )
    parser.add_argument(
        "--tests-only",
        action="store_true",
        help="不重寫正式產物；執行測試並以目前來源重算驗證",
    )
    args = parser.parse_args(argv)
    print("[gate-test] lag-overlap probability contracts", flush=True)
    _run(
        [
            sys.executable,
            "-B",
            "-X",
            "utf8",
            "-m",
            "pytest",
            "tests/test_lag_overlap_signal.py",
            "tests/test_lag_overlap_signal_verify.py",
            "-q",
            "-p",
            "no:cacheprovider",
        ]
    )
    if not args.tests_only:
        print("[formal] rebuild lag-overlap artifact", flush=True)
        _run(
            [
                sys.executable,
                "-B",
                "-X",
                "utf8",
                "lag_overlap_signal.py",
            ]
        )
    result = json.loads(FORMAL_RESULT.read_text(encoding="utf-8"))
    verify_formal_result(result)
    print("[formal] artifact verified", flush=True)
    _run(["git", "diff", "--check"])
    print("Lag-overlap probability verification passed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
