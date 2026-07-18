"""Qwen 終局裁判：結構化輸出、合法性、降級與只呼叫下一期。"""
from copy import deepcopy
from pathlib import Path

import pytest

from engine.agent_loop import (
    apply_final_judge,
    conduct_debate,
    initial_state,
    replay_game,
    target_from_draw,
)
from engine.games import SUPER
from engine.ollama_seat import StructuredResponse
from engine.qwen_judge import QwenJudgeError, adjudicate, validate_selection
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
