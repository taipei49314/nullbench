"""抽出順序子集合訊號的正式產物與分階段驗收。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from engine.agent_loop import verify_replay
from engine.games import LOTTO649, SUPER
from research.draw_order_signal import (
    EXPERIMENT_ID,
    GAMES,
    PROTOCOL_FILE,
    load_and_profile_raw_game,
    validate_result,
)
from research.gates import tree_sha256


BASE = Path(__file__).resolve().parent
FORMAL_RESULT = (
    BASE / "research" / "results" / "draw_order_signal.json"
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

    quality = result.get("data_quality", {})
    if verify_live_sources:
        for game in GAMES:
            try:
                _, live_profile = load_and_profile_raw_game(
                    game,
                    base=BASE,
                )
            except (KeyError, TypeError, ValueError, RuntimeError):
                failures.append(f"source_{game}")
                continue
            observed = quality.get("games", {}).get(game, {})
            fields = (
                "files",
                "empty_files",
                "draws",
                "unique_periods",
                "date_range",
                "row_schema_variants",
                "draw_order_coverage_rate",
                "raw_tree_sha256",
                "ledger_verification",
            )
            if any(
                observed.get(field) != live_profile.get(field)
                for field in fields
            ):
                failures.append(f"source_{game}")
        raw_hashes = {
            game: tree_sha256(BASE / "data" / "raw" / game)
            for game in GAMES
        }
        if quality.get("raw_snapshot_hashes") != raw_hashes:
            failures.append("raw_snapshot")
        for game, path in SOURCE_LEDGERS.items():
            replay = verify_replay(path)
            if (
                quality.get("games", {})
                .get(game, {})
                .get("ledger_verification")
                != replay
            ):
                failures.append(f"ledger_{game}")

    diagnostics = result.get("diagnostics", {})
    if set(diagnostics) != set(GAMES):
        failures.append("fixed_family")
    else:
        for game in GAMES:
            row = diagnostics[game]
            if (
                float(row.get("mean_regret_nats", 0)) <= 0
                or float(row.get("bootstrap_95_low", 0)) <= 0
                or float(row.get("bootstrap_95_high", 0)) <= 0
                or row.get("future_challenger_qualified") is not False
                or any(
                    row.get("future_challenger_criteria", {}).values()
                )
            ):
                failures.append(f"negative_result_{game}")
    conclusion = result.get("conclusion", {})
    if (
        conclusion.get("status")
        != "retain_existing_null_safe_protocol"
        or conclusion.get("historical_promotion_eligible")
        is not False
        or conclusion.get("future_challenger_design_allowed")
        is not False
        or conclusion.get("watcher_integration_allowed")
        is not False
        or conclusion.get("selected_future_challenger") is not None
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
            "抽出順序子集合訊號正式驗收失敗："
            + ", ".join(sorted(set(failures)))
        )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="驗收抽出順序子集合訊號研究"
    )
    parser.add_argument(
        "--tests-only",
        action="store_true",
        help="不重算完整歷史，只驗證測試與既有正式產物",
    )
    args = parser.parse_args(argv)
    print("[gate-test] draw-order signal contracts", flush=True)
    _run(
        [
            sys.executable,
            "-B",
            "-X",
            "utf8",
            "-m",
            "pytest",
            "tests/test_draw_order_signal.py",
            "tests/test_draw_order_signal_verify.py",
            "-q",
            "-p",
            "no:cacheprovider",
        ]
    )
    if not args.tests_only:
        print("[formal] rebuild draw-order signal", flush=True)
        _run(
            [
                sys.executable,
                "-B",
                "-X",
                "utf8",
                "draw_order_signal.py",
            ]
        )
    verify_formal_result(
        json.loads(FORMAL_RESULT.read_text(encoding="utf-8"))
    )
    print("[formal] artifact verified", flush=True)
    _run(["git", "diff", "--check"])
    print("Draw-order subset signal verification passed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
