"""Qwen 終局裁判：結構化輸出、合法性、降級與只呼叫下一期。"""
from copy import deepcopy
from pathlib import Path

import pytest

from engine.agent_loop import (
    apply_final_judge,
    canonical_hash,
    conduct_debate,
    initial_state,
    replay_game,
    target_from_draw,
)
from engine.forward_feedback import (
    build_feedback_context,
    build_postmortem,
)
from engine.games import SUPER
from engine.ledger import Ledger
from engine.ollama_seat import StructuredResponse
from engine.qwen_judge import (
    QwenJudgeError,
    adjudicate,
    build_prompt,
    validate_selection,
)
from engine.store import DrawStore


DATA = Path(__file__).parent.parent / "data"


def _valid_payload(proposal_ids):
    selected = list(proposal_ids[:5])
    return {
        "selected_proposal_ids": selected,
        "summary": "兼顧評議共識、分歧與候選組合分散度。",
        "reasons": [
            {"proposal_id": proposal_id, "reason": f"{proposal_id} 的公開裁決理由。"}
            for proposal_id in selected
        ],
    }


def _append_settled_feedback(ledger, decision):
    registration = {
        "game": decision["game"],
        "target": {"date": "2000-01-01", "period": 1},
        "registration_hash": "registration-sha",
    }
    arms = {
        "qwen_five": {
            "best_main_hits": 1,
            "total_main_hits": 3,
            "union_size": 20,
            "union_main_hits": 2,
            "missed_actual_numbers": [8, 18],
            "repeated_but_missed": [
                {"number": 8, "selected_count": 6}
            ],
        },
        "rule_five": {
            "best_main_hits": 2,
            "total_main_hits": 5,
            "union_size": 24,
            "union_main_hits": 4,
            "missed_actual_numbers": [8],
            "repeated_but_missed": [],
        },
        "random_five": {
            "best_main_hits": 2,
            "total_main_hits": 4,
            "union_size": 23,
            "union_main_hits": 3,
            "missed_actual_numbers": [18],
            "repeated_but_missed": [],
        },
    }
    postmortem = build_postmortem(
        registration,
        arms,
        {
            "eligible": True,
            "qwen_minus_rule_best_main_hits": -1,
        },
    )
    content = {
        "schema_version": "1",
        "experiment_id": "final-judge-forward-v1",
        "phase": "settlement",
        "registration_hash": registration["registration_hash"],
        "game": decision["game"],
        "target": registration["target"],
        "postmortem": postmortem,
    }
    ledger.append(
        "forward_settlement",
        {
            "content": content,
            "content_hash": canonical_hash(content),
        },
    )


@pytest.fixture(scope="module")
def decision():
    draws = DrawStore(DATA).draws(SUPER)
    return conduct_debate(
        SUPER,
        target_from_draw(draws[80]),
        draws[:80],
        initial_state(),
    )


def test_selection_schema_accepts_only_five_existing_proposals(decision):
    allowed = {proposal["proposal_id"] for proposal in decision["proposals"]}
    payload = _valid_payload(sorted(allowed))
    validated = validate_selection(payload, allowed)
    assert validated["selected_proposal_ids"] == payload["selected_proposal_ids"]
    assert len(validated["reasons"]) == 5

    duplicate = _valid_payload(sorted(allowed))
    duplicate["selected_proposal_ids"][-1] = duplicate["selected_proposal_ids"][0]
    with pytest.raises(QwenJudgeError, match="不可重複"):
        validate_selection(duplicate, allowed)

    unknown = _valid_payload(sorted(allowed))
    unknown["selected_proposal_ids"][-1] = "invented:99"
    unknown["reasons"][-1]["proposal_id"] = "invented:99"
    with pytest.raises(QwenJudgeError, match="不存在"):
        validate_selection(unknown, allowed)


def test_qwen_adjudicate_uses_qwen3_8b_and_returns_verified_result(decision):
    proposal_ids = [proposal["proposal_id"] for proposal in decision["proposals"]]
    calls = []

    def generator(prompt, schema, **kwargs):
        calls.append((prompt, schema, kwargs))
        return StructuredResponse(
            payload=_valid_payload(proposal_ids),
            model="qwen3:8b",
            response_hash="response-sha",
            total_duration=123_000_000,
            eval_count=77,
            load_duration=3_000_000,
            prompt_eval_count=900,
            prompt_eval_duration=20_000_000,
            eval_duration=100_000_000,
        )

    ticks = iter([1_000_000, 51_000_000])
    result = adjudicate(
        decision,
        generator=generator,
        clock_ns=lambda: next(ticks),
    )
    assert result["source"] == "ollama"
    assert result["model"] == "qwen3:8b"
    assert result["selected_proposal_ids"] == proposal_ids[:5]
    assert calls[0][2]["model"] == "qwen3:8b"
    assert calls[0][2]["seed"] == int(decision["decision_hash"][:8], 16)
    assert "不得宣稱能預知隨機開獎" in calls[0][0]
    assert result["telemetry"] == {
        "schema_version": "1",
        "outcome": "success",
        "wall_duration_ms": 50.0,
        "ollama_total_duration_ms": 123.0,
        "load_duration_ms": 3.0,
        "prompt_eval_count": 900,
        "prompt_eval_duration_ms": 20.0,
        "eval_count": 77,
        "eval_duration_ms": 100.0,
        "eval_tokens_per_second": 770.0,
        "error_type": None,
        "complete": True,
    }
    diagnostics = result["selection_diagnostics"]
    assert diagnostics["selected_count"] == 5
    assert diagnostics["source_agent_count"] >= 1
    assert 6 <= diagnostics["main_number_union_size"] <= 30
    assert diagnostics["mean_pairwise_main_overlap"] >= 0


def test_qwen_failure_keeps_structured_runtime_telemetry(decision):
    ticks = iter([10_000_000, 35_000_000])

    def generator(prompt, schema, **kwargs):
        raise TimeoutError("model timeout")

    with pytest.raises(QwenJudgeError, match="model timeout") as captured:
        adjudicate(
            decision,
            generator=generator,
            clock_ns=lambda: next(ticks),
        )

    assert captured.value.telemetry["outcome"] == "error"
    assert captured.value.telemetry["wall_duration_ms"] == 25.0
    assert captured.value.telemetry["complete"] is False
    assert captured.value.telemetry["error_type"] == "TimeoutError"


def test_qwen_consumes_verified_settled_feedback_and_returns_provenance(
    decision,
    tmp_path,
):
    ledger = Ledger(tmp_path / "forward.jsonl")
    _append_settled_feedback(ledger, decision)
    feedback = build_feedback_context(
        ledger,
        decision["game"],
        before_target=decision["target"],
    )
    proposal_ids = [
        proposal["proposal_id"] for proposal in decision["proposals"]
    ]
    prompts = []

    def generator(prompt, schema, **kwargs):
        prompts.append(prompt)
        return StructuredResponse(
            payload=_valid_payload(proposal_ids),
            model="qwen3:8b",
            response_hash="response-sha",
            total_duration=10_000_000,
            eval_count=12,
            eval_duration=8_000_000,
        )

    result = adjudicate(
        decision,
        feedback=feedback,
        generator=generator,
    )

    assert feedback["feedback_hash"] in prompts[0]
    assert "never_chase_previous_missed_numbers" in prompts[0]
    assert "絕不可追逐上一期漏掉的號碼" in prompts[0]
    assert "missed_actual_numbers" not in prompts[0]
    assert result["feedback_provenance"] == {
        "experiment_id": "settled-forward-feedback-v1",
        "status": "verified",
        "feedback_hash": feedback["feedback_hash"],
        "settlement_count": 1,
        "as_of_target": {"date": "2000-01-01", "period": 1},
        "source_postmortem_hashes": [
            feedback["rows"][0]["postmortem_hash"]
        ],
    }
    assert result["feedback_context"] == feedback


def test_qwen_rejects_tampered_feedback_before_generator(
    decision,
    tmp_path,
):
    feedback = build_feedback_context(
        Ledger(tmp_path / "forward.jsonl"),
        decision["game"],
        before_target=decision["target"],
    )
    feedback["before_target"]["period"] += 1
    feedback["feedback_hash"] = canonical_hash(
        {
            key: value
            for key, value in feedback.items()
            if key != "feedback_hash"
        }
    )
    calls = []

    with pytest.raises(QwenJudgeError, match="目標不符"):
        adjudicate(
            decision,
            feedback=feedback,
            generator=lambda *args, **kwargs: calls.append(args),
        )

    assert calls == []
    with pytest.raises(ValueError, match="目標不符"):
        build_prompt(decision, feedback)


def test_final_judge_replaces_baseline_only_with_valid_qwen_selection(decision):
    decision = deepcopy(decision)
    proposal_ids = [proposal["proposal_id"] for proposal in decision["proposals"]]
    payload = _valid_payload(proposal_ids)
    judged = apply_final_judge(
        decision,
        lambda _: {
            "source": "ollama",
            "requested_model": "qwen3:8b",
            "model": "qwen3:8b",
            **payload,
        },
    )
    assert judged["adjudication"]["judge"]["source"] == "ollama"
    assert [
        ticket["source_proposal"] for ticket in judged["selected_tickets"]
    ] == proposal_ids[:5]
    assert all(
        ranking["judge_reason"]
        for ranking in judged["adjudication"]["ranking"]
    )


def test_invalid_model_output_falls_back_without_impersonating_qwen(decision):
    decision = deepcopy(decision)
    baseline_ids = [
        ticket["source_proposal"] for ticket in decision["selected_tickets"]
    ]

    def broken(_):
        raise QwenJudgeError("測試用不合法輸出")

    judged = apply_final_judge(decision, broken)
    assert judged["adjudication"]["judge"]["source"] == "deterministic_fallback"
    assert judged["adjudication"]["judge"]["model"] is None
    assert "測試用不合法輸出" in judged["adjudication"]["judge"]["fallback_reason"]
    assert judged["adjudication"]["judge"]["telemetry"]["outcome"] == "error"
    assert (
        judged["adjudication"]["judge"]["telemetry"]["complete"]
        is False
    )
    assert [
        ticket["source_proposal"] for ticket in judged["selected_tickets"]
    ] == baseline_ids


def test_qwen_fallback_preserves_feedback_provenance(decision):
    decision = deepcopy(decision)
    provenance = {
        "experiment_id": "settled-forward-feedback-v1",
        "status": "verified",
        "feedback_hash": "feedback-sha",
        "settlement_count": 3,
        "as_of_target": {"date": "2026-01-01", "period": 3},
        "source_postmortem_hashes": ["a", "b", "c"],
    }

    def broken(_):
        raise QwenJudgeError(
            "offline",
            feedback_provenance=provenance,
        )

    judged = apply_final_judge(decision, broken)

    assert (
        judged["adjudication"]["judge"]["feedback_provenance"]
        == provenance
    )


def test_replay_calls_qwen_only_once_for_future_decision():
    draws = DrawStore(DATA).draws(SUPER)[:5]
    calls = []

    def final_judge(decision):
        calls.append(decision["history_count"])
        proposal_ids = [
            proposal["proposal_id"] for proposal in decision["proposals"]
        ]
        return {
            "source": "ollama",
            "requested_model": "qwen3:8b",
            "model": "qwen3:8b",
            **_valid_payload(proposal_ids),
        }

    summary = replay_game(
        SUPER,
        draws,
        collect_events=True,
        final_judge=final_judge,
    )
    assert calls == [len(draws)]
    assert summary["next_decision"]["adjudication"]["judge"]["source"] == "ollama"
    assert all(
        event["decision"]["adjudication"]["judge"]["source"]
        == "deterministic_replay"
        for event in summary["events"]
    )
