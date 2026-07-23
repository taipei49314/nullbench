"""完整六主號機率前緣 v4 正式 artifact 驗收。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from engine.agent_loop import canonical_hash
from research.cross_game_overlap_signal import (
    MODEL_ID as CROSS_GAME_MODEL_ID,
)
from research.gates import tree_sha256
from research.probability_frontier_v4 import (
    EXPERIMENT_ID,
    PROTOCOL_FILE,
    SOURCE_FILES,
    run_probability_frontier_v4,
    validate_result,
)


BASE = Path(__file__).resolve().parent
FORMAL_RESULT = (
    BASE / "research" / "results" / "probability_frontier_v4.json"
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
            path = BASE / relative_path
            observed = (
                result.get("source_artifacts", {})
                .get(source_id, {})
            )
            try:
                source = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                failures.append(f"source_{source_id}")
                continue
            if (
                observed.get("file_sha256") != _file_sha256(path)
                or observed.get("canonical_payload_hash")
                != canonical_hash(source)
                or observed.get("audit_hash") != source.get("audit_hash")
            ):
                failures.append(f"source_{source_id}")
        try:
            recomputed = run_probability_frontier_v4(base=BASE)
        except (KeyError, OSError, TypeError, ValueError, RuntimeError):
            failures.append("live_recompute")
        else:
            if result != recomputed:
                failures.append("live_recompute")
    conclusion = result.get("conclusion", {})
    rows = result.get("frontier_rows", [])
    cross_row = next(
        (
            row
            for row in rows
            if row.get("method_id") == CROSS_GAME_MODEL_ID
        ),
        {},
    )
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
        or conclusion.get("v3_immutable") is not True
        or cross_row.get("rank") != 11
        or cross_row.get("strictly_dominated_by_uniform") is not True
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
            "完整六主號機率前緣 v4 驗收失敗："
            + ", ".join(sorted(set(failures)))
        )


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="驗收完整六主號 proper-score 模型前緣 v4"
    )
    parser.add_argument(
        "--tests-only",
        action="store_true",
        help="不重寫正式產物；執行測試並以目前來源重算驗證",
    )
    args = parser.parse_args(argv)
    print("[gate-test] probability frontier v4 contracts", flush=True)
    _run(
        [
            sys.executable,
            "-B",
            "-X",
            "utf8",
            "-m",
            "pytest",
            "tests/test_probability_frontier_v4.py",
            "tests/test_probability_frontier_v4_verify.py",
            "-q",
            "-p",
            "no:cacheprovider",
        ]
    )
    if not args.tests_only:
        print("[formal] rebuild probability frontier v4", flush=True)
        _run(
            [
                sys.executable,
                "-B",
                "-X",
                "utf8",
                "probability_frontier_v4.py",
            ]
        )
    result = json.loads(FORMAL_RESULT.read_text(encoding="utf-8"))
    verify_formal_result(result)
    print("[formal] artifact verified", flush=True)
    _run(["git", "diff", "--check"])
    print("Probability frontier v4 verification passed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
