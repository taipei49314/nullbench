"""Append-only future registry for the switching-Bayes v2 shadow."""
from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from engine.agent_loop import canonical_hash
from engine.games import (
    GAME_NAMES,
    LOTTO649,
    SUPER,
    validate_pick,
)
from engine.ledger import Ledger, TAIPEI, now_iso
from research.agent_ablation import portfolio_metrics
from research.max_coverage import select_consensus_disjoint_portfolio
from research.switching_bayes import (
    FORWARD_EXPERIMENT_ID,
    PROTOCOL_HASH,
    build_score_capsule,
    forecast,
    select_shadow_portfolio,
    settle_score_capsule,
    validate_forward_candidate,
    validate_score_capsule,
)


REGISTRY_EXPERIMENT_ID = (
    "switching-bayes-append-only-forward-registry-v2"
)
DRAW_CUTOFF_TIME = "20:30:00"
SELECTED_TICKETS = 5


def _content(event: dict) -> dict:
    content = event.get("content")
    if (
        not isinstance(content, dict)
        or event.get("content_hash") != canonical_hash(content)
    ):
        raise ValueError("switching Bayes forward content hash 不符")
    return content


def _append(ledger: Ledger, event_type: str, content: dict) -> dict:
    return ledger.append(
        event_type,
        {
            "content": content,
            "content_hash": canonical_hash(content),
        },
    )


def _target_key(game: str, target: dict) -> tuple[str, str, int]:
    return (
        game,
        str(target["date"]),
        int(target["period"]),
    )


def _deadline(target: dict) -> str:
    return f"{target['date']}T{DRAW_CUTOFF_TIME}+08:00"


def _validate_tickets(game: str, tickets: list[dict]) -> None:
    if not isinstance(tickets, list) or len(tickets) != SELECTED_TICKETS:
        raise ValueError("switching Bayes forward 必須恰有五注")
    main_numbers = set()
    for slot, ticket in enumerate(tickets, 1):
        if (
            not isinstance(ticket, dict)
            or int(ticket.get("slot", 0)) != slot
        ):
            raise ValueError("switching Bayes forward slot 不連續")
        validate_pick(
            game,
            ticket["numbers"],
            ticket.get("special"),
        )
        main_numbers.update(int(number) for number in ticket["numbers"])
    if len(main_numbers) != 30:
        raise ValueError("switching Bayes forward 未保留 30 主號互斥結構")
    if game == SUPER and len(
        {int(ticket["special"]) for ticket in tickets}
    ) != SELECTED_TICKETS:
        raise ValueError("switching Bayes forward 第二區未完全分散")


def _selection_hash(game: str, tickets: list[dict]) -> str:
    return canonical_hash(
        {
            "game": game,
            "tickets": tickets,
        }
    )


def _normalized_reveal(game: str, draw) -> dict:
    return {
        "date": str(draw.date),
        "period": int(draw.period),
        "numbers": [int(number) for number in draw.numbers],
        "special": (
            int(draw.special)
            if draw.special is not None
            else None
        ),
        "game": game,
    }


def _find_draw(store, game: str, target: dict):
    for draw in store.draws(game):
        if (
            draw.date == str(target["date"])
            and draw.period == int(target["period"])
        ):
            return draw
    return None


def _registration(
    decision: dict,
    candidate: dict,
    *,
    registered_at: str,
) -> dict:
    game = decision["game"]
    target = {
        "date": str(decision["target"]["date"]),
        "period": int(decision["target"]["period"]),
    }
    prediction = forecast(game, decision, candidate)
    tickets, selection = select_shadow_portfolio(
        game,
        decision,
        candidate,
    )
    coverage_tickets, coverage = (
        select_consensus_disjoint_portfolio(
            game,
            decision,
        )
    )
    _validate_tickets(game, tickets)
    _validate_tickets(game, coverage_tickets)
    capsule = build_score_capsule(prediction)
    deadline = _deadline(target)
    late = datetime.fromisoformat(registered_at) >= datetime.fromisoformat(
        deadline
    )
    return {
        "schema_version": "1",
        "experiment_id": REGISTRY_EXPERIMENT_ID,
        "shadow_experiment_id": FORWARD_EXPERIMENT_ID,
        "protocol_hash": PROTOCOL_HASH,
        "phase": "preregister",
        "game": game,
        "game_name": GAME_NAMES[game],
        "target": target,
        "registered_at": registered_at,
        "deadline": deadline,
        "late": late,
        "eligible": not late,
        "history_count": int(decision["history_count"]),
        "history_last": deepcopy(decision.get("history_last")),
        "source_decision_hash": decision["decision_hash"],
        "candidate_hash": candidate["candidate_hash"],
        "selection_hash": _selection_hash(game, tickets),
        "coverage_selection_hash": _selection_hash(
            game,
            coverage_tickets,
        ),
        "tickets": tickets,
        "coverage_tickets": coverage_tickets,
        "score_capsule": capsule,
        "belief_weights": selection["belief_weights"],
        "coverage_support_evidence_hash": coverage[
            "support_evidence_hash"
        ],
        "use": "future_forward_shadow_only",
        "historical_backfill_allowed": False,
    }


def _validate_registration(content: dict) -> None:
    expected = {
        "schema_version",
        "experiment_id",
        "shadow_experiment_id",
        "protocol_hash",
        "phase",
        "game",
        "game_name",
        "target",
        "registered_at",
        "deadline",
        "late",
        "eligible",
        "history_count",
        "history_last",
        "source_decision_hash",
        "candidate_hash",
        "selection_hash",
        "coverage_selection_hash",
        "tickets",
        "coverage_tickets",
        "score_capsule",
        "belief_weights",
        "coverage_support_evidence_hash",
        "use",
        "historical_backfill_allowed",
    }
    game = content.get("game")
    if (
        not isinstance(content, dict)
        or set(content) != expected
        or content.get("schema_version") != "1"
        or content.get("experiment_id") != REGISTRY_EXPERIMENT_ID
        or content.get("shadow_experiment_id")
        != FORWARD_EXPERIMENT_ID
        or content.get("protocol_hash") != PROTOCOL_HASH
        or content.get("phase") != "preregister"
        or game not in (SUPER, LOTTO649)
        or content.get("game_name") != GAME_NAMES[game]
        or content.get("deadline") != _deadline(content["target"])
        or content.get("late")
        != (
            datetime.fromisoformat(content["registered_at"])
            >= datetime.fromisoformat(content["deadline"])
        )
        or content.get("eligible")
        != (not bool(content.get("late")))
        or content.get("selection_hash")
        != _selection_hash(game, content.get("tickets", []))
        or content.get("coverage_selection_hash")
        != _selection_hash(
            game,
            content.get("coverage_tickets", []),
        )
        or content.get("use") != "future_forward_shadow_only"
        or content.get("historical_backfill_allowed") is not False
    ):
        raise ValueError("switching Bayes preregistration 契約不符")
    _validate_tickets(game, content["tickets"])
    _validate_tickets(game, content["coverage_tickets"])
    capsule = validate_score_capsule(content["score_capsule"])
    if (
        capsule["game"] != game
        or capsule["target"] != content["target"]
        or capsule["candidate_hash"] != content["candidate_hash"]
        or capsule["source_decision_hash"]
        != content["source_decision_hash"]
        or capsule["main_prior_weights"]
        != content["belief_weights"]
    ):
        raise ValueError("switching Bayes preregistration score 來源不符")


def _settlement(registration_hash: str, registered: dict, draw) -> dict:
    game = registered["game"]
    reveal = _normalized_reveal(game, draw)
    shadow = portfolio_metrics(
        game,
        registered["tickets"],
        reveal,
    )
    coverage = portfolio_metrics(
        game,
        registered["coverage_tickets"],
        reveal,
    )
    score = settle_score_capsule(
        registered["score_capsule"],
        actual_main=reveal["numbers"],
        actual_special=(
            reveal["special"] if game == SUPER else None
        ),
    )
    union_delta = (
        shadow["union_main_hits"]
        - coverage["union_main_hits"]
    )
    return {
        "schema_version": "1",
        "experiment_id": REGISTRY_EXPERIMENT_ID,
        "shadow_experiment_id": FORWARD_EXPERIMENT_ID,
        "protocol_hash": PROTOCOL_HASH,
        "phase": "settlement",
        "registration_hash": registration_hash,
        "game": game,
        "game_name": GAME_NAMES[game],
        "target": registered["target"],
        "eligible": registered["eligible"],
        "actual": reveal,
        "shadow_result": shadow,
        "coverage_result": coverage,
        "shadow_minus_coverage_union_main_hits": union_delta,
        "shadow_minus_coverage_best_main_hits": (
            shadow["best_main_hits"]
            - coverage["best_main_hits"]
        ),
        "shadow_minus_coverage_any_three_plus": (
            int(shadow["any_three_plus"])
            - int(coverage["any_three_plus"])
        ),
        "shadow_minus_coverage_any_prize": (
            int(shadow["any_prize"])
            - int(coverage["any_prize"])
        ),
        "verdict": (
            "switching_bayes_win"
            if union_delta > 0
            else "coverage_win"
            if union_delta < 0
            else "tie"
        ),
        "proper_score": score,
        "interpretation": (
            "只結算開獎前已存在的 capsule；本期結果只能更新下一期，"
            "不得回改本期號碼。"
        ),
    }


def verify_registry(ledger: Ledger) -> dict:
    if not ledger.verify_chain():
        raise ValueError("switching Bayes forward ledger hash chain 不符")
    registrations = {}
    settlements = set()
    for event in ledger.read_all():
        content = _content(event)
        if event.get("schema_version") != "1":
            raise ValueError("switching Bayes forward schema 不符")
        if event["type"] == "switching_bayes_preregister":
            _validate_registration(content)
            key = _target_key(content["game"], content["target"])
            if key in {
                _target_key(row["game"], row["target"])
                for row in registrations.values()
            }:
                raise ValueError("switching Bayes forward 目標重複登記")
            registrations[event["content_hash"]] = content
        elif event["type"] == "switching_bayes_settlement":
            registration_hash = content.get("registration_hash")
            if (
                registration_hash not in registrations
                or registration_hash in settlements
            ):
                raise ValueError("switching Bayes settlement 來源不符或重複")
            registered = registrations[registration_hash]
            actual = content.get("actual", {})

            class FrozenDraw:
                date = actual.get("date")
                period = int(actual.get("period"))
                numbers = tuple(actual.get("numbers", ()))
                special = actual.get("special")

            expected = _settlement(
                registration_hash,
                registered,
                FrozenDraw(),
            )
            if content != expected:
                raise ValueError("switching Bayes settlement 重建不符")
            settlements.add(registration_hash)
        else:
            raise ValueError("未知 switching Bayes forward event")
    return {
        "chain_valid": True,
        "events": len(ledger.read_all()),
        "registrations": len(registrations),
        "settlements": len(settlements),
        "pending": len(registrations) - len(settlements),
    }


def _write_status(
    path: Path,
    ledger: Ledger,
) -> dict:
    verification = verify_registry(ledger)
    registration_events = ledger.events_of(
        "switching_bayes_preregister"
    )
    settlement_events = ledger.events_of(
        "switching_bayes_settlement"
    )
    settled = {
        _content(event)["registration_hash"]
        for event in settlement_events
    }
    pending = [
        {
            "registration_hash": event["content_hash"],
            "game": _content(event)["game"],
            "target": _content(event)["target"],
            "registered_at": _content(event)["registered_at"],
            "deadline": _content(event)["deadline"],
            "eligible": _content(event)["eligible"],
            "candidate_hash": _content(event)["candidate_hash"],
        }
        for event in registration_events
        if event["content_hash"] not in settled
    ]
    recent_scores = [
        {
            "game": _content(event)["game"],
            "target": _content(event)["target"],
            "eligible": _content(event)["eligible"],
            "main_regret_vs_uniform": _content(event)[
                "proper_score"
            ]["main_regret_vs_uniform"],
            "verdict": _content(event)["verdict"],
        }
        for event in settlement_events[-20:]
    ]
    status = {
        "schema_version": "1",
        "experiment_id": REGISTRY_EXPERIMENT_ID,
        "generated_at": now_iso(),
        "verification": verification,
        "pending": pending,
        "recent_scores": recent_scores,
        "historical_backfill_allowed": False,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(
            status,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return status


def reconcile_registry(
    base: Path,
    store,
    manifest: dict,
    *,
    registered_at: str | None = None,
) -> dict:
    """Settle existing preregistrations, then freeze each next target once."""
    base = Path(base)
    forward_dir = base / "simulation" / "forward"
    ledger = Ledger(forward_dir / "switching_bayes.jsonl")
    verify_registry(ledger)
    registrations = {
        _target_key(
            _content(event)["game"],
            _content(event)["target"],
        ): event
        for event in ledger.events_of(
            "switching_bayes_preregister"
        )
    }
    settled = {
        _content(event)["registration_hash"]
        for event in ledger.events_of(
            "switching_bayes_settlement"
        )
    }
    settlements_created = 0
    for event in ledger.events_of("switching_bayes_preregister"):
        if event["content_hash"] in settled:
            continue
        content = _content(event)
        draw = _find_draw(
            store,
            content["game"],
            content["target"],
        )
        if draw is None:
            continue
        _append(
            ledger,
            "switching_bayes_settlement",
            _settlement(
                event["content_hash"],
                content,
                draw,
            ),
        )
        settlements_created += 1

    study = json.loads(
        (
            base
            / "research"
            / "results"
            / "switching_bayes.json"
        ).read_text(encoding="utf-8")
    )
    candidate = validate_forward_candidate(
        study["future_forward_shadow_candidate"]
    )
    registration_status = {}
    timestamp = registered_at or now_iso()
    for game in (SUPER, LOTTO649):
        decision = manifest["games"][game]["next_decision"]
        key = _target_key(game, decision["target"])
        if key in registrations:
            registration_status[game] = {
                "status": "existing",
                "registration_hash": registrations[key][
                    "content_hash"
                ],
            }
            continue
        event = _append(
            ledger,
            "switching_bayes_preregister",
            _registration(
                decision,
                candidate,
                registered_at=timestamp,
            ),
        )
        registration_status[game] = {
            "status": "created",
            "registration_hash": event["content_hash"],
        }
    status = _write_status(
        forward_dir / "switching_bayes_status.json",
        ledger,
    )
    return {
        "settlements_created": settlements_created,
        "registrations": registration_status,
        "status": status,
        "ledger_path": str(ledger.path),
        "status_path": str(
            forward_dir / "switching_bayes_status.json"
        ),
    }
