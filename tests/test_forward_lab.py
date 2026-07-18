"""下一期終局裁判前向 A/B：凍結、結算、雜湊與門檻。"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from engine.agent_loop import (
    apply_final_judge,
    canonical_hash,
    conduct_debate,
    initial_state,
)
from engine.forward_feedback import (
    build_feedback_context_from_settlements,
)
from engine.forward_lab import (
    ARM_QWEN,
    ARM_RANDOM,
    ARM_RULE,
    ARMS,
    FORWARD_EXPERIMENT_ID,
    _block_bootstrap_ci,
    build_summary,
    feedback_for_target,
    preregister_decision,
    reconcile_forward_registry,
    settle_forward_registry,
    settle_ready,
    verify_registry,
)
from engine.games import LOTTO649, SUPER, Draw
from engine.ledger import Ledger
from engine.qwen_judge import selection_diagnostics
from engine.store import DrawStore


BASE = Path(__file__).parent.parent
DATA = BASE / "data"


def _qwen_payload(decision):
    feedback_context = build_feedback_context_from_settlements(
        [],
        decision["game"],
        before_target=decision["target"],
    )
    selected = [
        proposal["proposal_id"] for proposal in decision["proposals"][-5:]
    ]
    return {
        "source": "ollama",
        "requested_model": "qwen3:8b",
        "model": "qwen3:8b",
        "selected_proposal_ids": selected,
        "summary": "測試用終局裁決。",
        "reasons": [
            {"proposal_id": proposal_id, "reason": "測試理由"}
            for proposal_id in selected
        ],
        "prompt_hash": "prompt-sha",
        "response_hash": "response-sha",
        "feedback_provenance": {
            "experiment_id": "settled-forward-feedback-v1",
            "status": "verified_empty",
            "feedback_hash": feedback_context["feedback_hash"],
            "settlement_count": 0,
            "as_of_target": None,
            "source_postmortem_hashes": [],
        },
        "feedback_context": feedback_context,
        "telemetry": {
            "schema_version": "1",
            "outcome": "success",
            "wall_duration_ms": 1200,
            "ollama_total_duration_ms": 1100,
            "eval_count": 80,
            "eval_tokens_per_second": 20,
            "complete": True,
        },
        "selection_diagnostics": selection_diagnostics(
            decision,
            selected,
        ),
    }


def _decision(
    game: str,
    *,
    date: str | None = None,
    period: int = 188000001,
) -> dict:
    history = DrawStore(DATA).draws(game)[:80]
    target = {
        "date": date or (
            "2099-01-05" if game == SUPER else "2099-01-06"
        ),
        "period": period,
    }
    decision = conduct_debate(game, target, history, initial_state())
    return apply_final_judge(
        deepcopy(decision), lambda current: _qwen_payload(current)
    )


def _draw(game: str) -> Draw:
    return Draw(
        game=game,
        period=188000001,
        date="2099-01-05" if game == SUPER else "2099-01-06",
        numbers=(1, 2, 3, 4, 5, 6),
        special=8 if game == SUPER else 7,
    )


class FakeStore:
    def __init__(self, draws=None):
        self._draws = draws or {}

    def draws(self, game):
        return list(self._draws.get(game, []))


@pytest.mark.parametrize("game", [SUPER, LOTTO649])
def test_preregister_freezes_three_valid_arms_without_reveal(tmp_path, game):
    ledger = Ledger(tmp_path / "forward.jsonl")
    result = preregister_decision(
        ledger,
        _decision(game),
        registered_at="2099-01-01T12:00:00+08:00",
    )
    content = result["event"]["content"]

    assert result["status"] == "created"
    assert content["experiment_id"] == FORWARD_EXPERIMENT_ID
    assert content["late"] is False
    assert set(content["arms"]) == set(ARMS)
    assert all(len(content["arms"][arm]["tickets"]) == 5 for arm in ARMS)
    assert all(content["arms"][arm]["eligible"] for arm in ARMS)
    assert content["arms"][ARM_QWEN]["metadata"]["model"] == "qwen3:8b"
    assert content["arms"][ARM_QWEN]["metadata"][
        "feedback_provenance"
    ]["status"] == "verified_empty"
    assert content["arms"][ARM_QWEN]["metadata"][
        "feedback_context"
    ]["feedback_hash"] == content["arms"][ARM_QWEN][
        "metadata"
    ]["feedback_provenance"]["feedback_hash"]
    assert (
        content["arms"][ARM_QWEN]["metadata"]["telemetry"]["outcome"]
        == "success"
    )
    assert (
        content["arms"][ARM_QWEN]["metadata"]["selection_diagnostics"][
            "selected_count"
        ]
        == 5
    )
    assert content["arms"][ARM_RANDOM]["source"] == "uniform_null"
    assert "actual" not in json.dumps(content)
    assert verify_registry(ledger)["registrations"] == 1


def test_preregister_is_idempotent_and_never_overwrites_first_qwen_choice(
    tmp_path,
):
    ledger = Ledger(tmp_path / "forward.jsonl")
    decision = _decision(SUPER)
    first = preregister_decision(
        ledger,
        decision,
        registered_at="2099-01-01T12:00:00+08:00",
    )
    changed = deepcopy(decision)
    changed["selected_tickets"] = list(reversed(changed["selected_tickets"]))
    second = preregister_decision(
        ledger,
        changed,
        registered_at="2099-01-02T12:00:00+08:00",
    )

    assert first["registration_hash"] == second["registration_hash"]
    assert second["status"] == "existing"
    assert len(ledger.read_all()) == 1


def test_late_registration_and_qwen_fallback_are_ineligible(tmp_path):
    late_ledger = Ledger(tmp_path / "late.jsonl")
    late = preregister_decision(
        late_ledger,
        _decision(SUPER),
        registered_at="2099-01-05T20:30:00+08:00",
    )["event"]["content"]
    assert late["late"] is True
    assert all(not late["arms"][arm]["eligible"] for arm in ARMS)

    fallback_ledger = Ledger(tmp_path / "fallback.jsonl")
    baseline = _decision(SUPER)
    fallback = apply_final_judge(
        conduct_debate(
            SUPER,
            baseline["target"],
            DrawStore(DATA).draws(SUPER)[:80],
            initial_state(),
        ),
        lambda _: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    content = preregister_decision(
        fallback_ledger,
        fallback,
        registered_at="2099-01-01T12:00:00+08:00",
    )["event"]["content"]
    assert content["arms"][ARM_RULE]["eligible"] is True
    assert content["arms"][ARM_RANDOM]["eligible"] is True
    assert content["arms"][ARM_QWEN]["eligible"] is False
    assert (
        content["arms"][ARM_QWEN]["ineligible_reason"]
        == "qwen_not_verified"
    )


def test_qwen_without_verified_settled_feedback_is_ineligible(tmp_path):
    decision = _decision(SUPER)
    decision["adjudication"]["judge"].pop(
        "feedback_provenance",
        None,
    )
    decision["adjudication"]["judge"].pop(
        "feedback_context",
        None,
    )

    content = preregister_decision(
        Ledger(tmp_path / "missing-feedback.jsonl"),
        decision,
        registered_at="2099-01-01T12:00:00+08:00",
    )["event"]["content"]

    assert content["arms"][ARM_RULE]["eligible"] is True
    assert content["arms"][ARM_RANDOM]["eligible"] is True
    assert content["arms"][ARM_QWEN]["eligible"] is False
    assert (
        content["arms"][ARM_QWEN]["ineligible_reason"]
        == "qwen_not_verified"
    )


def test_settlement_requires_existing_preregistration_and_is_idempotent(
    tmp_path,
):
    ledger = Ledger(tmp_path / "forward.jsonl")
    preregistration = preregister_decision(
        ledger,
        _decision(SUPER),
        registered_at="2099-01-01T12:00:00+08:00",
    )

    assert settle_ready(ledger, FakeStore()) == []
    created = settle_ready(
        ledger, FakeStore({SUPER: [_draw(SUPER)]})
    )
    assert len(created) == 1
    settlement = created[0]["content"]
    assert (
        settlement["registration_hash"]
        == preregistration["registration_hash"]
    )
    assert settlement["actual"]["numbers"] == [1, 2, 3, 4, 5, 6]
    assert settlement["postmortem"]["registration_hash"] == (
        preregistration["registration_hash"]
    )
    assert settlement["postmortem"]["postmortem_hash"]
    assert set(settlement["arm_results"]) == set(ARMS)
    assert settlement["qwen_vs_rule"]["verdict"] in {
        "qwen_win",
        "rule_win",
        "tie",
    }
    assert settle_ready(
        ledger, FakeStore({SUPER: [_draw(SUPER)]})
    ) == []
    assert verify_registry(ledger)["settlements"] == 1


def test_registry_detects_last_line_content_tampering(tmp_path):
    path = tmp_path / "forward.jsonl"
    ledger = Ledger(path)
    preregister_decision(
        ledger,
        _decision(SUPER),
        registered_at="2099-01-01T12:00:00+08:00",
    )
    event = json.loads(path.read_text(encoding="utf-8"))
    event["content"]["arms"][ARM_RULE]["tickets"][0]["numbers"][0] = 38
    path.write_text(json.dumps(event, ensure_ascii=False) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="content_hash"):
        verify_registry(ledger)


def test_registry_rejects_rehashed_but_inconsistent_postmortem(
    tmp_path,
):
    path = tmp_path / "forward.jsonl"
    ledger = Ledger(path)
    preregister_decision(
        ledger,
        _decision(SUPER),
        registered_at="2099-01-01T12:00:00+08:00",
    )
    settle_ready(ledger, FakeStore({SUPER: [_draw(SUPER)]}))
    lines = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    settlement = lines[-1]
    postmortem = settlement["content"]["postmortem"]
    postmortem["diagnostic_flags"] = ["forged_causal_story"]
    postmortem["postmortem_hash"] = canonical_hash(
        {
            key: value
            for key, value in postmortem.items()
            if key != "postmortem_hash"
        }
    )
    settlement["content_hash"] = canonical_hash(
        settlement["content"]
    )
    path.write_text(
        "\n".join(
            json.dumps(line, ensure_ascii=False)
            for line in lines
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="flags 不完整"):
        verify_registry(ledger)


def test_registry_rejects_semantically_inconsistent_qwen_telemetry(tmp_path):
    path = tmp_path / "forward.jsonl"
    ledger = Ledger(path)
    preregister_decision(
        ledger,
        _decision(SUPER),
        registered_at="2099-01-01T12:00:00+08:00",
    )
    event = json.loads(path.read_text(encoding="utf-8"))
    event["content"]["arms"][ARM_QWEN]["metadata"]["telemetry"][
        "outcome"
    ] = "error"
    event["content_hash"] = canonical_hash(event["content"])
    path.write_text(
        json.dumps(event, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="來源與遙測結果矛盾"):
        verify_registry(ledger)


def test_registry_rejects_forged_feedback_context_even_with_new_hash(
    tmp_path,
):
    path = tmp_path / "forward.jsonl"
    ledger = Ledger(path)
    preregister_decision(
        ledger,
        _decision(SUPER),
        registered_at="2099-01-01T12:00:00+08:00",
    )
    event = json.loads(path.read_text(encoding="utf-8"))
    metadata = event["content"]["arms"][ARM_QWEN]["metadata"]
    context = metadata["feedback_context"]
    context["honesty_note"] = "forged but rehashed"
    context["feedback_hash"] = canonical_hash(
        {
            key: value
            for key, value in context.items()
            if key != "feedback_hash"
        }
    )
    metadata["feedback_provenance"]["feedback_hash"] = context[
        "feedback_hash"
    ]
    event["content_hash"] = canonical_hash(event["content"])
    path.write_text(
        json.dumps(event, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="誠實聲明不符"):
        verify_registry(ledger)


def test_registry_rejects_fallback_source_with_success_telemetry(tmp_path):
    path = tmp_path / "forward.jsonl"
    ledger = Ledger(path)
    preregister_decision(
        ledger,
        _decision(SUPER),
        registered_at="2099-01-01T12:00:00+08:00",
    )
    event = json.loads(path.read_text(encoding="utf-8"))
    event["content"]["arms"][ARM_QWEN][
        "source"
    ] = "deterministic_fallback"
    event["content_hash"] = canonical_hash(event["content"])
    path.write_text(
        json.dumps(event, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="降級來源與遙測結果矛盾"):
        verify_registry(ledger)


def test_summary_stays_collecting_until_preregistered_forward_sample_exists(
    tmp_path,
):
    ledger = Ledger(tmp_path / "forward.jsonl")
    preregister_decision(
        ledger,
        _decision(SUPER),
        registered_at="2099-01-01T12:00:00+08:00",
    )
    settle_ready(ledger, FakeStore({SUPER: [_draw(SUPER)]}))
    summary = build_summary(ledger)

    assert summary["evidence_status"] == "collecting_forward_data"
    assert summary["recommendation"] == "keep_rule_as_control"
    assert summary["games"][SUPER]["eligible_qwen_rule_pairs"] == 1
    assert summary["games"][LOTTO649]["eligible_qwen_rule_pairs"] == 0
    assert summary["verification"]["chain_valid"] is True
    assert (
        summary["operations"]["games"][SUPER]["status"]
        == "collecting_operational_data"
    )
    assert (
        summary["operations"]["deployment_gate"]["status"]
        == "collecting_joint_evidence"
    )


def test_positive_block_bootstrap_interval_is_deterministic():
    differences = [1.0] * 60
    first = _block_bootstrap_ci(differences, game=SUPER)
    second = _block_bootstrap_ci(differences, game=SUPER)
    assert first == second == (1.0, 1.0)


def test_reconcile_settles_before_registering_both_next_targets(tmp_path):
    manifest = {
        "games": {
            SUPER: {"next_decision": _decision(SUPER)},
            LOTTO649: {"next_decision": _decision(LOTTO649)},
        }
    }
    first = reconcile_forward_registry(
        tmp_path,
        FakeStore(),
        manifest,
        registered_at="2099-01-01T12:00:00+08:00",
    )
    second = reconcile_forward_registry(
        tmp_path,
        FakeStore({SUPER: [_draw(SUPER)]}),
        manifest,
        registered_at="2099-01-02T12:00:00+08:00",
    )

    assert first["settlements_created"] == 0
    assert all(
        item["status"] == "created"
        for item in first["registrations"].values()
    )
    assert second["settlements_created"] == 1
    assert all(
        item["status"] == "existing"
        for item in second["registrations"].values()
    )
    assert Path(second["status_path"]).exists()
    assert second["summary"]["verification"] == {
        "chain_valid": True,
        "events": 3,
        "registrations": 2,
        "settlements": 1,
        "pending": 1,
    }


def test_new_reveal_settles_old_targets_then_freezes_new_targets_once(
    tmp_path,
):
    first_manifest = {
        "games": {
            SUPER: {"next_decision": _decision(SUPER)},
            LOTTO649: {"next_decision": _decision(LOTTO649)},
        }
    }
    next_manifest = {
        "games": {
            SUPER: {
                "next_decision": _decision(
                    SUPER,
                    date="2099-01-08",
                    period=188000002,
                )
            },
            LOTTO649: {
                "next_decision": _decision(
                    LOTTO649,
                    date="2099-01-09",
                    period=188000002,
                )
            },
        }
    }
    revealed_store = FakeStore(
        {
            SUPER: [_draw(SUPER)],
            LOTTO649: [_draw(LOTTO649)],
        }
    )

    first = reconcile_forward_registry(
        tmp_path,
        FakeStore(),
        first_manifest,
        registered_at="2099-01-01T12:00:00+08:00",
    )
    advanced = reconcile_forward_registry(
        tmp_path,
        revealed_store,
        next_manifest,
        registered_at="2099-01-07T12:00:00+08:00",
    )
    repeated = reconcile_forward_registry(
        tmp_path,
        revealed_store,
        next_manifest,
        registered_at="2099-01-07T13:00:00+08:00",
    )

    assert first["summary"]["verification"]["pending"] == 2
    assert advanced["settlements_created"] == 2
    assert all(
        registration["status"] == "created"
        for registration in advanced["registrations"].values()
    )
    assert advanced["summary"]["verification"] == {
        "chain_valid": True,
        "events": 6,
        "registrations": 4,
        "settlements": 2,
        "pending": 2,
    }
    assert (
        advanced["summary"]["feedback_memory"][SUPER][
            "settlement_count"
        ]
        == 1
    )
    assert (
        advanced["summary"]["feedback_memory"][LOTTO649][
            "settlement_count"
        ]
        == 1
    )
    assert repeated["settlements_created"] == 0
    assert all(
        registration["status"] == "existing"
        for registration in repeated["registrations"].values()
    )
    assert repeated["summary"]["verification"]["events"] == 6


def test_predecision_settlement_builds_feedback_before_new_registration(
    tmp_path,
):
    manifest = {
        "games": {
            SUPER: {"next_decision": _decision(SUPER)},
            LOTTO649: {"next_decision": _decision(LOTTO649)},
        }
    }
    reconcile_forward_registry(
        tmp_path,
        FakeStore(),
        manifest,
        registered_at="2099-01-01T12:00:00+08:00",
    )

    settled = settle_forward_registry(
        tmp_path,
        FakeStore({SUPER: [_draw(SUPER)]}),
    )
    feedback = feedback_for_target(
        tmp_path,
        SUPER,
        {"date": "2099-01-08", "period": 188000002},
    )

    assert settled["settlements_created"] == 1
    assert settled["summary"]["verification"]["settlements"] == 1
    assert feedback["settlement_count"] == 1
    assert feedback["as_of_target"] == {
        "date": "2099-01-05",
        "period": 188000001,
    }


def test_next_qwen_registration_must_archive_exact_settled_context(
    tmp_path,
):
    initial_manifest = {
        "games": {
            SUPER: {"next_decision": _decision(SUPER)},
            LOTTO649: {"next_decision": _decision(LOTTO649)},
        }
    }
    reconcile_forward_registry(
        tmp_path,
        FakeStore(),
        initial_manifest,
        registered_at="2099-01-01T12:00:00+08:00",
    )
    settle_forward_registry(
        tmp_path,
        FakeStore({SUPER: [_draw(SUPER)]}),
    )
    decision = _decision(
        SUPER,
        date="2099-01-08",
        period=188000002,
    )
    context = feedback_for_target(
        tmp_path,
        SUPER,
        decision["target"],
    )
    judge = decision["adjudication"]["judge"]
    judge["feedback_context"] = context
    judge["feedback_provenance"] = {
        "experiment_id": context["experiment_id"],
        "status": "verified",
        "feedback_hash": context["feedback_hash"],
        "settlement_count": context["settlement_count"],
        "as_of_target": context["as_of_target"],
        "source_postmortem_hashes": context[
            "source_postmortem_hashes"
        ],
    }
    decision.pop("decision_hash")
    decision["decision_hash"] = canonical_hash(decision)

    registered = preregister_decision(
        Ledger(
            tmp_path
            / "simulation"
            / "forward"
            / "ledger.jsonl"
        ),
        decision,
        registered_at="2099-01-07T12:00:00+08:00",
    )
    qwen = registered["event"]["content"]["arms"][ARM_QWEN]

    assert context["settlement_count"] == 1
    assert qwen["eligible"] is True
    assert qwen["metadata"]["feedback_context"] == context
    assert verify_registry(
        Ledger(
            tmp_path
            / "simulation"
            / "forward"
            / "ledger.jsonl"
        )
    )["registrations"] == 3
