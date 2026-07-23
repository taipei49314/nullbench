"""實體開獎中介資料可用性正式驗收。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from research.gates import tree_sha256
from research.physical_metadata_audit import (
    EXPERIMENT_ID,
    GAMES,
    PROTOCOL_FILE,
    run_physical_metadata_audit,
    validate_result,
)


BASE = Path(__file__).resolve().parent
FORMAL_RESULT = (
    BASE / "research" / "results" / "physical_metadata_audit.json"
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
            recomputed = run_physical_metadata_audit(base=BASE)
        except (KeyError, OSError, TypeError, ValueError, RuntimeError):
            failures.append("live_recompute")
        else:
            if result != recomputed:
                failures.append("live_recompute")

    conclusion = result.get("conclusion", {})
    if (
        conclusion.get("status")
        != "physical_metadata_unavailable_pre_cutoff"
        or conclusion.get("official_raw_physical_fields_absent")
        is not True
        or conclusion.get("pre_cutoff_assignment_absent") is not True
        or conclusion.get("future_model_ready") is not False
        or conclusion.get("number_probability_model_allowed")
        is not False
        or conclusion.get("historical_promotion_eligible")
        is not False
        or conclusion.get("watcher_integration_allowed") is not False
        or conclusion.get("number_changes_allowed") is not False
        or conclusion.get("future_diagnostic_collection_allowed")
        is not True
        or conclusion.get("selected_probability_protocol")
        != "uniform_null_safe"
    ):
        failures.append("decision")
    raw = result.get("raw_schema_audit", {})
    if (
        raw.get("physical_metadata_rows_total") != 0
        or raw.get("physical_metadata_coverage_rate") != 0
        or set(raw.get("games", {})) != set(GAMES)
    ):
        failures.append("raw_decision")
    observations = result.get("observation_audit", {})
    if (
        observations.get("total_observations") != 1
        or observations.get("pre_cutoff_eligible_observations") != 0
        or observations.get("machine_id_observations") != 1
        or observations.get("ball_set_id_observations") != 0
    ):
        failures.append("observation_decision")
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
            "實體 metadata 正式驗收失敗："
            + ", ".join(sorted(set(failures)))
        )


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="驗收實體開獎資料可用性 artifact"
    )
    parser.add_argument(
        "--tests-only",
        action="store_true",
        help="不重寫正式產物；執行專項測試並以目前來源重算",
    )
    args = parser.parse_args(argv)
    print("[gate-test] physical metadata contracts", flush=True)
    _run(
        [
            sys.executable,
            "-B",
            "-X",
            "utf8",
            "-m",
            "pytest",
            "tests/test_physical_metadata_audit.py",
            "tests/test_physical_metadata_audit_verify.py",
            "-q",
            "-p",
            "no:cacheprovider",
        ]
    )
    if not args.tests_only:
        print("[formal] rebuild physical metadata artifact", flush=True)
        _run(
            [
                sys.executable,
                "-B",
                "-X",
                "utf8",
                "physical_metadata_audit.py",
            ]
        )
    result = json.loads(FORMAL_RESULT.read_text(encoding="utf-8"))
    verify_formal_result(result)
    print("[formal] artifact verified", flush=True)
    _run(["git", "diff", "--check"])
    print("Physical metadata verification passed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
