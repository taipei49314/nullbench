"""第一個真實前向自動學習閉環的唯讀 Goal 驗收。

這個入口刻意不抓資料、不執行裁決，也不寫入任何帳本。它只在兩筆既有
預登記保持原樣、各自完成真實結算，而且下一期 qwen3:8b 登記封存了可重建
的 settled feedback 後回報完成。
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import date, datetime, time
import json
from pathlib import Path
import sys

from engine.agent_loop import canonical_hash
from engine.automation import read_status, verify_history
from engine.forward_feedback import (
    FEEDBACK_EXPERIMENT_ID,
    verify_feedback_context,
)
from engine.forward_lab import (
    ARM_COVERAGE,
    ARM_QWEN,
    COVERAGE_FORWARD_EXPERIMENT_ID,
    COVERAGE_FORWARD_EXPERIMENT_ID_V4,
    COVERAGE_FORWARD_EXPERIMENT_ID_V5,
    COVERAGE_FORWARD_EXPERIMENT_ID_V6,
    MONITORING_PROTOCOL_ID,
    build_summary,
    forward_ledger,
    verify_registry,
)
from engine.games import GAME_NAMES, LOTTO649, SUPER
from engine.ledger import TAIPEI
from research.structural_optimum import structural_proof_reference


ROOT = Path(__file__).resolve().parent
MAX_HEARTBEAT_AGE_SECONDS = 120
OFFICIAL_RESULT_DEADLINE_LOCAL_TIME = time(22, 0)
GOAL_TARGETS = {
    SUPER: {
        "target": {"date": "2026-07-20", "period": 115000058},
        "registration_hash": (
            "e3c4b0d067fa8208158025356d51496e"
            "4376ffcaf657a4a89905744234a493d1"
        ),
    },
    LOTTO649: {
        "target": {"date": "2026-07-21", "period": 115000072},
        "registration_hash": (
            "8991e28e95bb2e02c790049a4633c648"
            "c6f26bd0a3d620c792a3c8e3e3a1e4d9"
        ),
    },
}
EXPECTED_WAITING_FAILURES = {
    f"{game}:{condition}"
    for game in (SUPER, LOTTO649)
    for condition in (
        "settlement_missing",
        "next_registration_missing",
    )
}


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON 根節點不是 object：{path}")
    return value


def _event_content(event: dict) -> dict:
    content = event.get("content")
    if not isinstance(content, dict):
        raise ValueError("前向帳本事件缺少 content")
    if event.get("content_hash") != canonical_hash(content):
        raise ValueError("前向帳本事件 content_hash 不符")
    return content


def _target_order(target: dict) -> tuple[str, int]:
    return str(target["date"]), int(target["period"])


def _official_result_deadline(target: dict) -> datetime:
    """Return the fail-closed deadline after the scheduled draw."""
    return datetime.combine(
        date.fromisoformat(str(target["date"])),
        OFFICIAL_RESULT_DEADLINE_LOCAL_TIME,
        tzinfo=TAIPEI,
    )


def _provenance_from_context(context: dict) -> dict:
    return {
        "experiment_id": FEEDBACK_EXPERIMENT_ID,
        "status": (
            "verified"
            if context["settlement_count"] > 0
            else "verified_empty"
        ),
        "feedback_hash": context["feedback_hash"],
        "settlement_count": context["settlement_count"],
        "as_of_target": context["as_of_target"],
        "source_postmortem_hashes": context[
            "source_postmortem_hashes"
        ],
    }


def evaluate_goal_state(
    *,
    events: list[dict],
    registry_summary: dict,
    automation_status: dict,
    automation_history: dict,
    forward_snapshot: dict,
    manifest: dict,
    shadow_research: dict,
    expected: dict | None = None,
    observed_at: str | None = None,
) -> dict:
    """從已驗證的唯讀來源判斷 Goal 是否真的閉環。"""
    expected = deepcopy(expected or GOAL_TARGETS)
    failures: list[str] = []
    registrations: dict[str, dict] = {}
    settlements: dict[str, dict] = {}
    for event in events:
        content = _event_content(event)
        if event.get("type") == "forward_preregister":
            registrations[event["content_hash"]] = content
        elif event.get("type") == "forward_settlement":
            settlements[content["registration_hash"]] = content

    if registry_summary.get("chain_valid") is not True:
        failures.append("forward_chain_invalid")
    if automation_history.get("chain_valid") is not True:
        failures.append("automation_history_chain_invalid")
    if automation_status.get("watcher_state") != "online":
        failures.append("watcher_not_online")
    if int(automation_status.get("consecutive_failures", -1)) != 0:
        failures.append("watcher_has_consecutive_failures")
    if not automation_status.get("last_success_at"):
        failures.append("watcher_missing_last_success")
    heartbeat_at = automation_status.get("heartbeat_at")
    heartbeat_age_seconds = None
    try:
        observed = (
            datetime.fromisoformat(observed_at)
            if observed_at is not None
            else datetime.now(TAIPEI)
        )
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=TAIPEI)
        else:
            observed = observed.astimezone(TAIPEI)
        heartbeat = datetime.fromisoformat(heartbeat_at)
        if heartbeat.tzinfo is None:
            heartbeat = heartbeat.replace(tzinfo=TAIPEI)
        else:
            heartbeat = heartbeat.astimezone(TAIPEI)
        heartbeat_age_seconds = round(
            (observed - heartbeat).total_seconds(), 3
        )
    except (TypeError, ValueError):
        failures.append("watcher_heartbeat_invalid")
    else:
        if (
            heartbeat_age_seconds < -30
            or heartbeat_age_seconds > MAX_HEARTBEAT_AGE_SECONDS
        ):
            failures.append("watcher_heartbeat_stale")
    if forward_snapshot.get("verification") != registry_summary:
        failures.append("forward_snapshot_not_current")
    if (
        forward_snapshot.get("methodology", {}).get(
            "monitoring_protocol_id"
        )
        != MONITORING_PROTOCOL_ID
        or forward_snapshot.get(
            "qwen_joint_sequential_monitor", {}
        ).get("protocol_id")
        != MONITORING_PROTOCOL_ID
    ):
        failures.append("forward_monitoring_protocol_not_current")

    manifest_games = manifest.get("games", {})
    source_dates = shadow_research.get("data_quality", {}).get(
        "source_last_dates", {}
    )
    if shadow_research.get("records_integrity", {}).get(
        "unchanged"
    ) is not True:
        failures.append("shadow_research_changed_formal_records")

    game_evidence = {}
    for game, goal in expected.items():
        prefix = f"{game}:"
        target = goal["target"]
        registration_hash = goal["registration_hash"]
        initial = registrations.get(registration_hash)
        settlement = settlements.get(registration_hash)
        official_result_deadline = _official_result_deadline(target)
        official_result_overdue = (
            settlement is None and observed >= official_result_deadline
        )
        evidence = {
            "game_name": GAME_NAMES[game],
            "initial_target": target,
            "initial_registration_hash": registration_hash,
            "initial_registration_present": initial is not None,
            "settlement_present": settlement is not None,
            "official_result_deadline": (
                official_result_deadline.isoformat()
            ),
            "official_result_overdue": official_result_overdue,
            "next_pending_target": None,
            "feedback_status": None,
            "feedback_hash": None,
            "coverage_status": None,
            "coverage_exact_probability_delta": None,
            "coverage_any_prize_probability_delta": None,
        }

        if initial is None:
            failures.append(prefix + "initial_registration_missing")
        else:
            if initial.get("target") != target:
                failures.append(prefix + "initial_registration_changed")
            qwen = initial.get("arms", {}).get(ARM_QWEN, {})
            if (
                initial.get("late") is not False
                or qwen.get("eligible") is not True
                or qwen.get("source") != "ollama"
                or qwen.get("metadata", {}).get("model") != "qwen3:8b"
            ):
                failures.append(prefix + "initial_registration_not_qualified")

        if settlement is None:
            failures.append(prefix + "settlement_missing")
            if official_result_overdue:
                failures.append(prefix + "official_result_overdue")
        else:
            if (
                settlement.get("target") != target
                or settlement.get("qwen_vs_rule", {}).get("eligible")
                is not True
            ):
                failures.append(prefix + "settlement_not_qualified")

        settled_hashes = set(settlements)
        later_pending = [
            (registration_hash_, content)
            for registration_hash_, content in registrations.items()
            if content.get("game") == game
            and _target_order(content["target"]) > _target_order(target)
            and registration_hash_ not in settled_hashes
        ]
        later_pending.sort(
            key=lambda item: _target_order(item[1]["target"])
        )
        if not later_pending:
            failures.append(prefix + "next_registration_missing")
            game_evidence[game] = evidence
            continue

        next_hash, next_registration = later_pending[-1]
        next_target = next_registration["target"]
        evidence["next_pending_target"] = next_target
        evidence["next_registration_hash"] = next_hash
        qwen = next_registration.get("arms", {}).get(ARM_QWEN, {})
        coverage = next_registration.get("arms", {}).get(
            ARM_COVERAGE, {}
        )
        metadata = qwen.get("metadata") or {}
        coverage_metadata = coverage.get("metadata") or {}
        context = metadata.get("feedback_context")
        provenance = metadata.get("feedback_provenance")
        if (
            qwen.get("source") != "ollama"
            or qwen.get("eligible") is not True
            or metadata.get("model") != "qwen3:8b"
        ):
            failures.append(prefix + "next_qwen_not_qualified")
        coverage_delta = coverage_metadata.get(
            "exact_probability_delta"
        )
        coverage_any_prize_delta = coverage_metadata.get(
            "exact_any_prize_probability_delta"
        )
        coverage_support_hash = coverage_metadata.get(
            "support_evidence_hash"
        )
        coverage_structure = coverage_metadata.get(
            "selected_structure"
        )
        evidence["coverage_status"] = (
            "qualified"
            if coverage.get("eligible") is True
            else "ineligible"
        )
        evidence["coverage_exact_probability_delta"] = coverage_delta
        evidence["coverage_any_prize_probability_delta"] = (
            coverage_any_prize_delta
        )
        if (
            coverage.get("source")
            != "deterministic_consensus_disjoint_selector"
            or coverage.get("eligible") is not True
            or coverage_metadata.get("experiment_id")
            not in {
                COVERAGE_FORWARD_EXPERIMENT_ID,
                COVERAGE_FORWARD_EXPERIMENT_ID_V4,
                COVERAGE_FORWARD_EXPERIMENT_ID_V5,
                COVERAGE_FORWARD_EXPERIMENT_ID_V6,
            }
            or not isinstance(coverage_support_hash, str)
            or len(coverage_support_hash) != 64
            or coverage_metadata.get("structural_optimum_proof")
            != structural_proof_reference()
            or not isinstance(coverage_structure, dict)
            or coverage_structure.get("main_union_size") != 30
            or coverage_structure.get(
                "maximum_pairwise_main_overlap"
            )
            != 0
            or not isinstance(coverage_delta, (int, float))
            or coverage_delta < -1e-15
            or not isinstance(
                coverage_any_prize_delta, (int, float)
            )
            or coverage_any_prize_delta < -1e-15
        ):
            failures.append(prefix + "next_coverage_not_qualified")
        if not isinstance(context, dict):
            failures.append(prefix + "feedback_context_missing")
        else:
            try:
                verify_feedback_context(
                    context,
                    game=game,
                    target=next_target,
                )
            except (KeyError, TypeError, ValueError):
                failures.append(prefix + "feedback_context_invalid")
            else:
                evidence["feedback_hash"] = context["feedback_hash"]
                evidence["feedback_status"] = (
                    provenance.get("status")
                    if isinstance(provenance, dict)
                    else None
                )
                if (
                    context["settlement_count"] < 1
                    or provenance != _provenance_from_context(context)
                    or provenance.get("status") != "verified"
                ):
                    failures.append(prefix + "feedback_provenance_invalid")
                postmortem_hash = (
                    settlement.get("postmortem", {}).get(
                        "postmortem_hash"
                    )
                    if settlement is not None
                    else None
                )
                if (
                    not postmortem_hash
                    or postmortem_hash
                    not in context["source_postmortem_hashes"]
                ):
                    failures.append(
                        prefix + "initial_settlement_not_in_feedback"
                    )

        manifest_game = manifest_games.get(game, {})
        if (
            manifest_game.get("next_decision", {}).get("target")
            != next_target
            or manifest_game.get("next_decision", {}).get(
                "decision_hash"
            )
            != next_registration.get("source_decision_hash")
            or manifest_game.get("next_decision", {})
            .get("adjudication", {})
            .get("judge", {})
            .get("feedback_provenance")
            != provenance
        ):
            failures.append(prefix + "manifest_not_linked_to_registration")
        last_target = manifest_game.get("last_target")
        if (
            not isinstance(last_target, dict)
            or _target_order(last_target) < _target_order(target)
        ):
            failures.append(prefix + "manifest_has_not_replayed_target")
        elif source_dates.get(game) != last_target.get("date"):
            failures.append(prefix + "shadow_research_stale")
        game_evidence[game] = evidence

    if not failures:
        audit_state = "complete"
    elif set(failures) <= EXPECTED_WAITING_FAILURES:
        audit_state = "waiting"
    else:
        audit_state = "blocked"
    return {
        "status": "complete" if not failures else "incomplete",
        "audit_state": audit_state,
        "failures": failures,
        "verification": registry_summary,
        "watcher": {
            "state": automation_status.get("watcher_state"),
            "consecutive_failures": automation_status.get(
                "consecutive_failures"
            ),
            "last_success_at": automation_status.get("last_success_at"),
            "heartbeat_at": heartbeat_at,
            "heartbeat_age_seconds": heartbeat_age_seconds,
            "maximum_heartbeat_age_seconds": (
                MAX_HEARTBEAT_AGE_SECONDS
            ),
            "history_chain_valid": automation_history.get("chain_valid"),
        },
        "games": game_evidence,
        "shadow_research": {
            "generated_at": shadow_research.get("generated_at"),
            "source_last_dates": source_dates,
            "records_unchanged": shadow_research.get(
                "records_integrity", {}
            ).get("unchanged"),
        },
    }


def audit_goal(base: Path = ROOT) -> dict:
    """讀取目前正式證據；任何鏈或 schema 異常直接 fail closed。"""
    base = Path(base)
    ledger = forward_ledger(base)
    registry_summary = verify_registry(ledger)
    rebuilt_summary = build_summary(ledger)
    if rebuilt_summary.get("verification") != registry_summary:
        raise ValueError("重建後的前向摘要與帳本驗證不一致")
    return evaluate_goal_state(
        events=ledger.read_all(),
        registry_summary=registry_summary,
        automation_status=read_status(base),
        automation_history=verify_history(base),
        forward_snapshot=_read_json(
            base / "simulation" / "forward" / "status.json"
        ),
        manifest=_read_json(
            base / "simulation" / "results" / "manifest.json"
        ),
        shadow_research=_read_json(
            base / "research" / "results" / "council_quality.json"
        ),
    )


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="唯讀驗證第一個真實前向自動學習閉環"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="輸出完整 JSON 證據",
    )
    args = parser.parse_args(argv)
    try:
        result = audit_goal()
    except (KeyError, OSError, TypeError, ValueError) as exc:
        print(
            json.dumps(
                {"status": "invalid", "error": str(exc)},
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 1

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Goal 狀態：{result['status']}")
        for failure in result["failures"]:
            print(f"- {failure}")
    return 0 if result["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
