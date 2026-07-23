"""完整六主號機率前緣正式 artifact 驗收。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from research.gates import tree_sha256
from research.probability_frontier import (
    EXPERIMENT_ID,
    PROTOCOL_FILE,
    SOURCE_FILES,
    run_probability_frontier,
    validate_result,
)


BASE = Path(__file__).resolve().parent
FORMAL_RESULT = (
    BASE / "research" / "results" / "probability_frontier.json"
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
        for source_id, relative_path in SOURCE_FILES.items():
            observed = (
                result.get("source_artifacts", {})
                .get(source_id, {})
                .get("file_sha256")
            )
            if observed != _file_sha256(BASE / relative_path):
                failures.append(f"source_{source_id}")
        try:
            recomputed = run_probability_frontier(base=BASE)
        except (KeyError, TypeError, ValueError, RuntimeError):
            failures.append("live_recompute")
        else:
            if result != recomputed:
                failures.append("live_recompute")

    conclusion = result.get("conclusion", {})
    if (
        conclusion.get("status")
        != "retain_uniform_null_safe_champion"
        or conclusion.get("champion_method_id")
        != "uniform_null_safe"
        or conclusion.get(
            "historically_supported_non_uniform_methods"
        )
        != []
        or conclusion.get("historical_promotion_eligible")
        is not False
        or conclusion.get("watcher_integration_allowed")
        is not False
        or conclusion.get("stop_historical_parameter_search")
        is not True
    ):
        failures.append("decision")
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
            "完整六主號機率前緣正式驗收失敗："
            + ", ".join(sorted(set(failures)))
        )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="驗收完整六主號 proper-score 模型前緣"
    )
    parser.add_argument(
        "--tests-only",
        action="store_true",
        help="不重寫正式產物；執行測試並以目前來源重算驗證",
    )
    args = parser.parse_args(argv)
    print("[gate-test] probability frontier contracts", flush=True)
    _run(
        [
            sys.executable,
            "-B",
            "-X",
            "utf8",
            "-m",
            "pytest",
            "tests/test_probability_frontier.py",
            "tests/test_probability_frontier_verify.py",
            "-q",
            "-p",
            "no:cacheprovider",
        ]
    )
    if not args.tests_only:
        print("[formal] rebuild probability frontier", flush=True)
        _run(
            [
                sys.executable,
                "-B",
                "-X",
                "utf8",
                "probability_frontier.py",
            ]
        )
    verify_formal_result(
        json.loads(FORMAL_RESULT.read_text(encoding="utf-8"))
    )
    print("[formal] artifact verified", flush=True)
    _run(["git", "diff", "--check"])
    print("Probability frontier verification passed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
