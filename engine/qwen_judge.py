"""Qwen3:8b 終局裁判。

模型只能從 15 組已驗證提案中挑選五組，不可自創或修改號碼。歷史逐期回放
不呼叫本模組；它只處理回放完成後的下一期終局決策。
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
import time
from collections import Counter
from itertools import combinations
from typing import Callable

from .forward_feedback import (
    FEEDBACK_EXPERIMENT_ID,
    verify_feedback_context,
)
from .ollama_seat import MODEL, StructuredResponse, generate_structured


FINAL_COUNT = 5
MAX_SUMMARY_LENGTH = 240
MAX_REASON_LENGTH = 180

FINAL_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["selected_proposal_ids", "summary", "reasons"],
    "properties": {
        "selected_proposal_ids": {
            "type": "array",
            "minItems": FINAL_COUNT,
            "maxItems": FINAL_COUNT,
            "uniqueItems": True,
            "items": {"type": "string"},
        },
        "summary": {"type": "string", "minLength": 1, "maxLength": MAX_SUMMARY_LENGTH},
        "reasons": {
            "type": "array",
            "minItems": FINAL_COUNT,
            "maxItems": FINAL_COUNT,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["proposal_id", "reason"],
                "properties": {
                    "proposal_id": {"type": "string"},
                    "reason": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": MAX_REASON_LENGTH,
                    },
                },
            },
        },
    },
}


class QwenJudgeError(RuntimeError):
    """Qwen 終局結果不符合裁決契約。"""

    def __init__(
        self,
        message: str,
        *,
        telemetry: dict | None = None,
        feedback_provenance: dict | None = None,
        feedback_context: dict | None = None,
    ):
        super().__init__(message)
        self.telemetry = telemetry
        self.feedback_provenance = feedback_provenance
        self.feedback_context = feedback_context


def _duration_ms(value: int | None) -> float | None:
    if value is None:
        return None
    return round(max(0, int(value)) / 1_000_000, 3)


def _runtime_telemetry(
    response: StructuredResponse | None,
    *,
    wall_duration_ms: float,
    outcome: str,
    error_type: str | None = None,
) -> dict:
    eval_count = response.eval_count if response is not None else None
    eval_duration = response.eval_duration if response is not None else None
    tokens_per_second = None
    if (
        eval_count is not None
        and eval_duration is not None
        and int(eval_duration) > 0
    ):
        tokens_per_second = round(
            int(eval_count) / (int(eval_duration) / 1_000_000_000),
            3,
        )
    telemetry = {
        "schema_version": "1",
        "outcome": outcome,
        "wall_duration_ms": round(max(0.0, wall_duration_ms), 3),
        "ollama_total_duration_ms": _duration_ms(
            response.total_duration if response is not None else None
        ),
        "load_duration_ms": _duration_ms(
            response.load_duration if response is not None else None
        ),
        "prompt_eval_count": (
            response.prompt_eval_count if response is not None else None
        ),
        "prompt_eval_duration_ms": _duration_ms(
            response.prompt_eval_duration
            if response is not None
            else None
        ),
        "eval_count": eval_count,
        "eval_duration_ms": _duration_ms(eval_duration),
        "eval_tokens_per_second": tokens_per_second,
        "error_type": error_type,
    }
    telemetry["complete"] = bool(
        outcome == "success"
        and telemetry["ollama_total_duration_ms"] is not None
        and telemetry["eval_count"] is not None
    )
    return telemetry


def selection_diagnostics(
    decision: dict,
    selected_proposal_ids: list[str],
) -> dict:
    """只用開獎前候選與評議，量化終局五注的分散與基準排名。"""
    proposals = {
        proposal["proposal_id"]: proposal
        for proposal in decision["proposals"]
    }
    scores = {
        score["proposal_id"]: score
        for score in decision["adjudication"]["candidate_scores"]
    }
    baseline_ranks = {
        score["proposal_id"]: rank
        for rank, score in enumerate(
            decision["adjudication"]["candidate_scores"],
            1,
        )
    }
    selected = [proposals[proposal_id] for proposal_id in selected_proposal_ids]
    agent_counts = Counter(proposal["agent"] for proposal in selected)
    pair_overlaps = [
        len(set(left["numbers"]) & set(right["numbers"]))
        for left, right in combinations(selected, 2)
    ]
    union = set().union(
        *(set(proposal["numbers"]) for proposal in selected)
    )
    return {
        "schema_version": "1",
        "selected_count": len(selected),
        "source_agent_count": len(agent_counts),
        "source_agent_counts": dict(sorted(agent_counts.items())),
        "max_source_agent_share": round(
            max(agent_counts.values()) / len(selected),
            3,
        ),
        "main_number_union_size": len(union),
        "mean_pairwise_main_overlap": round(
            sum(pair_overlaps) / len(pair_overlaps),
            3,
        ),
        "max_pairwise_main_overlap": max(pair_overlaps),
        "mean_debate_score": round(
            sum(scores[item]["debate_score"] for item in selected_proposal_ids)
            / len(selected_proposal_ids),
            6,
        ),
        "mean_disagreement": round(
            sum(scores[item]["disagreement"] for item in selected_proposal_ids)
            / len(selected_proposal_ids),
            6,
        ),
        "mean_baseline_rank": round(
            sum(baseline_ranks[item] for item in selected_proposal_ids)
            / len(selected_proposal_ids),
            3,
        ),
    }


def _clean_text(value: object, *, field: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise QwenJudgeError(f"{field} 必須是字串")
    text = re.sub(r"\s+", " ", value).strip()
    if not text:
        raise QwenJudgeError(f"{field} 不可空白")
    if len(text) > maximum:
        raise QwenJudgeError(f"{field} 超過 {maximum} 字")
    if "<think>" in text.lower() or "</think>" in text.lower():
        raise QwenJudgeError(f"{field} 含未允許的思考標記")
    return text


def validate_selection(payload: dict, allowed_ids: set[str]) -> dict:
    """嚴格驗證模型只能選五個現有 proposal_id，且每組都有簡短理由。"""
    if not isinstance(payload, dict):
        raise QwenJudgeError("裁決根節點必須是物件")
    if set(payload) != {"selected_proposal_ids", "summary", "reasons"}:
        raise QwenJudgeError("裁決欄位不符合契約")

    selected = payload["selected_proposal_ids"]
    if not isinstance(selected, list) or len(selected) != FINAL_COUNT:
        raise QwenJudgeError("必須剛好選五個 proposal_id")
    if any(not isinstance(item, str) for item in selected):
        raise QwenJudgeError("proposal_id 必須是字串")
    if len(set(selected)) != FINAL_COUNT:
        raise QwenJudgeError("五個 proposal_id 不可重複")
    unknown = set(selected) - allowed_ids
    if unknown:
        raise QwenJudgeError(f"模型選了不存在的提案：{sorted(unknown)}")

    raw_reasons = payload["reasons"]
    if not isinstance(raw_reasons, list) or len(raw_reasons) != FINAL_COUNT:
        raise QwenJudgeError("五個入選提案都必須有理由")
    reasons = []
    for index, item in enumerate(raw_reasons, 1):
        if not isinstance(item, dict) or set(item) != {"proposal_id", "reason"}:
            raise QwenJudgeError(f"第 {index} 個理由欄位不符合契約")
        proposal_id = item["proposal_id"]
        if not isinstance(proposal_id, str):
            raise QwenJudgeError(f"第 {index} 個理由缺少 proposal_id")
        reasons.append(
            {
                "proposal_id": proposal_id,
                "reason": _clean_text(
                    item["reason"],
                    field=f"第 {index} 個理由",
                    maximum=MAX_REASON_LENGTH,
                ),
            }
        )
    reason_ids = [item["proposal_id"] for item in reasons]
    if len(set(reason_ids)) != FINAL_COUNT or set(reason_ids) != set(selected):
        raise QwenJudgeError("理由必須與五個入選 proposal_id 一一對應")
    reason_map = {item["proposal_id"]: item["reason"] for item in reasons}

    return {
        "selected_proposal_ids": selected,
        "summary": _clean_text(
            payload["summary"],
            field="summary",
            maximum=MAX_SUMMARY_LENGTH,
        ),
        "reasons": [
            {"proposal_id": proposal_id, "reason": reason_map[proposal_id]}
            for proposal_id in selected
        ],
    }


def _compact_evidence(proposal: dict) -> dict:
    evidence = proposal.get("evidence", {})
    return {
        "hypothesis_code": evidence.get("hypothesis_code"),
        "evidence_strength": evidence.get("evidence_strength"),
        "mean_relative_to_uniform": evidence.get(
            "mean_relative_to_uniform"
        ),
        "diagnostics": evidence.get("diagnostics", {}),
        "distribution_hash": evidence.get("distribution_hash"),
    }


def _feedback_provenance(
    decision: dict,
    feedback: dict | None,
) -> dict:
    if feedback is None:
        return {
            "experiment_id": FEEDBACK_EXPERIMENT_ID,
            "status": "not_supplied",
            "feedback_hash": None,
            "settlement_count": 0,
            "as_of_target": None,
            "source_postmortem_hashes": [],
        }
    verify_feedback_context(
        feedback,
        game=decision["game"],
        target=decision["target"],
    )
    return {
        "experiment_id": FEEDBACK_EXPERIMENT_ID,
        "status": (
            "verified"
            if feedback["settlement_count"] > 0
            else "verified_empty"
        ),
        "feedback_hash": feedback["feedback_hash"],
        "settlement_count": feedback["settlement_count"],
        "as_of_target": deepcopy(feedback["as_of_target"]),
        "source_postmortem_hashes": list(
            feedback["source_postmortem_hashes"]
        ),
    }


def build_prompt(
    decision: dict,
    feedback: dict | None = None,
) -> str:
    _feedback_provenance(decision, feedback)
    proposal_map = {
        proposal["proposal_id"]: proposal for proposal in decision["proposals"]
    }
    candidates = []
    for score in decision["adjudication"]["candidate_scores"]:
        proposal = proposal_map[score["proposal_id"]]
        candidates.append(
            {
                "id": proposal["proposal_id"],
                "agent": proposal["agent"],
                "numbers": proposal["numbers"],
                "special": proposal["special"],
                "baseline": score["debate_score"],
                "consensus": score["consensus_score"],
                "disagreement": score["disagreement"],
                "critics": [
                    [
                        item["critic"],
                        item["score"],
                        item["confidence"],
                    ]
                    for item in score["critic_scores"]
                ],
                "evidence": _compact_evidence(proposal),
            }
        )
    input_payload = {
        "game": decision["game"],
        "target": decision["target"],
        "agent_ratings": {
            agent: state["rating"]
            for agent, state in decision["state_before"]["agents"].items()
        },
        "settled_forward_feedback": (
            deepcopy(feedback)
            if feedback is not None
            else {
                "experiment_id": FEEDBACK_EXPERIMENT_ID,
                "status": "not_supplied",
                "settlement_count": 0,
            }
        ),
        "candidates": candidates,
    }
    compact_json = json.dumps(
        input_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return (
        "你是 LOTTO//LAB 的終局裁判。這是純模擬，真實生成機制未知；不得先宣告"
        "開獎必為獨立隨機，也不得先宣告歷史必有規律，更不得宣稱能預知下一期。"
        "請只從下列 15 個 id 中依序挑出剛好 5 個，絕不可"
        "自創、修改或重複號碼。綜合評議分數與信心度、較低分歧、五組之間的主號"
        "分散、假說來源多樣性。H0 獨立均勻只是普通競爭基準，不享有保留席位或"
        "裁決加成；H1–H4 也只能靠嚴格逐期盲測證據取得權重。"
        "settled_forward_feedback 只包含嚴格早於本期的已結算組合層診斷；"
        "它不是生成機制的因果證據。絕不可追逐上一期漏掉的號碼、不可把單期結果"
        "升格為熱冷號規律。若含 profit_portfolio_aggregate，只能用 eligible_pair_count"
        "及相對 coverage 的彙總值作為低權重組合結構護欄；不得由單期輸贏反推號碼，"
        "其中 common_special_shadow 也只能看相對 baseline 的彙總差，"
        "不得要求、猜測或追逐其候選第二區號碼。"
        "也不得忽略開獎前精確有限枚舉證明。其餘回饋也只能把重複出現的覆蓋、"
        "集中度或相對表現訊號當作組合結構護欄。"
        "summary 與每組 reason 請用精簡繁體中文，只寫可公開的決策依據，"
        "不要輸出思考過程。輸出必須符合指定 JSON Schema。\nDATA="
        + compact_json
    )


def adjudicate(
    decision: dict,
    *,
    feedback: dict | None = None,
    generator: Callable[..., StructuredResponse] = generate_structured,
    model: str = MODEL,
    clock_ns: Callable[[], int] = time.perf_counter_ns,
) -> dict:
    """呼叫 qwen3:8b 並回傳已驗證、可公開的終局裁決資訊。"""
    started_ns = clock_ns()
    response = None
    feedback_provenance = None
    feedback_context = None
    try:
        feedback_provenance = _feedback_provenance(decision, feedback)
        feedback_context = (
            deepcopy(feedback) if feedback is not None else None
        )
        allowed_ids = {
            proposal["proposal_id"] for proposal in decision["proposals"]
        }
        prompt = build_prompt(decision, feedback)
        prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        seed = int(decision["decision_hash"][:8], 16)
        response = generator(
            prompt,
            FINAL_SCHEMA,
            seed=seed,
            model=model,
        )
        if response.model != model:
            raise QwenJudgeError(
                f"模型不符：要求 {model}，實際 {response.model or 'unknown'}"
            )
        validated = validate_selection(response.payload, allowed_ids)
    except Exception as exc:
        telemetry = _runtime_telemetry(
            response,
            wall_duration_ms=(clock_ns() - started_ns) / 1_000_000,
            outcome="error",
            error_type=type(exc).__name__,
        )
        raise QwenJudgeError(
            str(exc),
            telemetry=telemetry,
            feedback_provenance=feedback_provenance,
            feedback_context=feedback_context,
        ) from exc
    telemetry = _runtime_telemetry(
        response,
        wall_duration_ms=(clock_ns() - started_ns) / 1_000_000,
        outcome="success",
    )
    return {
        "source": "ollama",
        "requested_model": model,
        "model": response.model,
        "selected_proposal_ids": validated["selected_proposal_ids"],
        "summary": validated["summary"],
        "reasons": validated["reasons"],
        "prompt_hash": prompt_hash,
        "response_hash": response.response_hash,
        "eval_count": response.eval_count,
        "telemetry": telemetry,
        "feedback_provenance": feedback_provenance,
        "feedback_context": feedback_context,
        "selection_diagnostics": selection_diagnostics(
            decision,
            validated["selected_proposal_ids"],
        ),
    }
