"""機率堆疊研究的正式產物與分階段驗收。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

from engine.agent_loop import verify_replay
from engine.games import LOTTO649, SUPER
from research.probability_stacking import (
    EXPERIMENT_ID,
    EXPERT_IDS,
    FORWARD_EXPERIMENT_ID,
    PROTOCOL_CONFIG,
    PROTOCOL_HASH,
    UNIFORM_EXPERT,
    validate_forward_candidate,
)


BASE = Path(__file__).resolve().parent
FORMAL_RESULT = (
    BASE / "research" / "results" / "probability_stacking.json"
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
        or quality.get("proposal_coverage")
        != "5 agents × 3 proposals per draw"
        or quality.get("critique_coverage")
        != "60 cross-agent critiques per draw"
        or quality.get("candidate_score_coverage") != "15 per draw"
    ):
        failures.append("data_quality_contract")
    for game, expected in expected_sources.items():
        row = verification.get(game, {})
        summary = summaries.get(game, {})
        if (
            row.get("lines") != expected["lines"]
            or row.get("ledger_sha256") != expected["ledger_sha256"]
            or row.get("last_event_hash")
            != expected["last_event_hash"]
            or summary.get("draws") != expected["lines"]
            or summary.get("first_date") != expected["first"]
            or summary.get("last_date") != expected["last"]
        ):
            failures.append(f"source_{game}")

    for game in (SUPER, LOTTO649):
        summary = summaries.get(game, {})
        expert_losses = summary.get(
            "mean_expert_main_log_loss", {}
        )
        model = models.get(game, {})
        weights = model.get("main_weights", {})
        if (
            set(expert_losses) != set(EXPERT_IDS)
            or set(weights) != set(EXPERT_IDS)
            or min(expert_losses, key=expert_losses.get)
            != UNIFORM_EXPERT
            or weights.get(UNIFORM_EXPERT, 0) <= 0.99999
            or sum(weights.values()) < 0.999999999999
            or sum(weights.values()) > 1.000000000001
        ):
            failures.append(f"proper_score_{game}")
    super_summary = summaries.get(SUPER, {})
    super_special_losses = super_summary.get(
        "mean_expert_special_log_loss", {}
    )
    super_special_weights = models.get(SUPER, {}).get(
        "special_weights", {}
    )
    if (
        set(super_special_losses) != set(EXPERT_IDS)
        or min(
            super_special_losses,
            key=super_special_losses.get,
        )
        != UNIFORM_EXPERT
        or super_special_weights.get(UNIFORM_EXPERT, 0)
        <= 0.99999
    ):
        failures.append("proper_score_super_special")

    if (
        conclusion.get("status") != "future_shadow_only"
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
            "機率堆疊正式驗收失敗：" + ", ".join(failures)
        )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="驗收機率堆疊與 future-only 時間邊界"
    )
    parser.add_argument(
        "--tests-only",
        action="store_true",
        help="不重算完整歷史，只驗證測試與既有正式產物",
    )
    args = parser.parse_args(argv)
    print("[gate-test] probability stacking contracts", flush=True)
    _run(
        [
            sys.executable,
            "-B",
            "-X",
            "utf8",
            "-m",
            "pytest",
            "tests/test_probability_stacking.py",
            "-q",
            "-p",
            "no:cacheprovider",
        ]
    )
    if not args.tests_only:
        print("[formal] rebuild probability stacking", flush=True)
        _run(
            [
                sys.executable,
                "-B",
                "-X",
                "utf8",
                "probability_stacking.py",
            ]
        )
    verify_formal_result(
        json.loads(FORMAL_RESULT.read_text(encoding="utf-8"))
    )
    print("[formal] artifact verified", flush=True)
    _run(["git", "diff", "--check"])
    print("機率堆疊研究驗收通過。", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
