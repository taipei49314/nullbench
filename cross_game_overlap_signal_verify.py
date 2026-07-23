"""跨遊戲 overlap 正式研究產物驗收。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from research.cross_game_overlap_signal import (
    BOOTSTRAP_SAMPLES,
    EXPERIMENT_ID,
    GAMES,
    MODEL_ID,
    PROTOCOL_FILE,
    run_cross_game_overlap_signal,
    validate_result,
)
from research.gates import tree_sha256


BASE = Path(__file__).resolve().parent
FORMAL_RESULT = (
    BASE
    / "research"
    / "results"
    / "cross_game_overlap_signal.json"
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
            recomputed = run_cross_game_overlap_signal(
                base=BASE,
                bootstrap_samples=BOOTSTRAP_SAMPLES,
            )
        except (
            KeyError,
            OSError,
            TypeError,
            ValueError,
            RuntimeError,
        ):
            failures.append("live_recompute")
        else:
            if result != recomputed:
                failures.append("live_recompute")
    diagnostics = result.get("diagnostics", {})
    if set(diagnostics) != set(GAMES):
        failures.append("fixed_family")
    conclusion = result.get("conclusion", {})
    qualified = (
        set(diagnostics) == set(GAMES)
        and all(
            diagnostics[game].get("future_challenger_qualified")
            is True
            for game in GAMES
        )
    )
    if (
        conclusion.get("historical_promotion_eligible") is not False
        or conclusion.get("watcher_integration_allowed") is not False
        or conclusion.get("future_challenger_design_allowed")
        is not qualified
        or conclusion.get("selected_future_challenger")
        != (MODEL_ID if qualified else None)
        or conclusion.get("probability_decision")
        != (MODEL_ID if qualified else "uniform_null_safe")
        or conclusion.get("frontier_v4_inclusion_required") is not True
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
            "跨遊戲 overlap 正式驗收失敗："
            + ", ".join(sorted(set(failures)))
        )


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="驗收跨遊戲前一期 overlap 完整 subset 研究"
    )
    parser.add_argument(
        "--tests-only",
        action="store_true",
        help="不重寫正式產物；執行測試並以目前來源重算驗證",
    )
    args = parser.parse_args(argv)
    print("[gate-test] cross-game overlap contracts", flush=True)
    _run(
        [
            sys.executable,
            "-B",
            "-X",
            "utf8",
            "-m",
            "pytest",
            "tests/test_cross_game_overlap_signal.py",
            "tests/test_cross_game_overlap_signal_verify.py",
            "-q",
            "-p",
            "no:cacheprovider",
        ]
    )
    if not args.tests_only:
        print("[formal] rebuild cross-game overlap signal", flush=True)
        _run(
            [
                sys.executable,
                "-B",
                "-X",
                "utf8",
                "cross_game_overlap_signal.py",
            ]
        )
    result = json.loads(FORMAL_RESULT.read_text(encoding="utf-8"))
    verify_formal_result(result)
    print("[formal] artifact verified", flush=True)
    _run(["git", "diff", "--check"])
    print("Cross-game overlap subset signal verification passed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
