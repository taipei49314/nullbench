"""下一期終局裁判前向 A/B：凍結、結算、雜湊與門檻。"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from engine.agent_loop import apply_final_judge, conduct_debate, initial_state
from engine.forward_lab import (
    ARM_QWEN,
    ARM_RANDOM,
    ARM_RULE,
    ARMS,
    FORWARD_EXPERIMENT_ID,
    _block_bootstrap_ci,
    build_summary,
    preregister_decision,
    reconcile_forward_registry,
    settle_ready,
    verify_registry,
)
from engine.games import LOTTO649, SUPER, Draw
from engine.ledger import Ledger
from engine.store import DrawStore


BASE = Path(__file__).parent.parent
DATA = BASE / "data"


def _qwen_payload(decision):
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
    assert repeated["settlements_created"] == 0
    assert all(
        registration["status"] == "existing"
        for registration in repeated["registrations"].values()
    )
    assert repeated["summary"]["verification"]["events"] == 6
