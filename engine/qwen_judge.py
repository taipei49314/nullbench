"""Qwen3:8b 終局裁判。

模型只能從 15 組已驗證提案中挑選五組，不可自創或修改號碼。歷史逐期回放
不呼叫本模組；它只處理回放完成後的下一期終局決策。
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Callable

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
    agent = proposal["agent"]
    if agent == "hot_hunter":
        return {
            "window_average_counts": [
                round(
                    sum(item["count"] for item in window["selected_counts"]) / 6,
                    3,
                )
                for window in evidence.get("windows", [])
            ]
        }
    if agent == "cold_keeper":
        values = [
            item["relative_to_expected"]
            for item in evidence.get("selected_gaps", [])
        ]
        return {
            "mean_relative_gap": round(sum(values) / len(values), 3)
            if values
            else 0
        }
    if agent == "balance_engineer":
        keys = (
            "sum",
            "odd",
            "consecutive_pairs",
            "tail_kinds",
            "range",
            "bucket_kinds",
            "max_same_tail",
            "gap_kinds",
        )
        return {key: evidence[key] for key in keys if key in evidence}
    if agent == "antipop_taoist":
        return {
            key: evidence[key]
            for key in (
                "above_31",
                "month_band",
                "birthday_band",
                "round_numbers",
                "repeated_tail_pairs",
                "arithmetic_sequence",
            )
            if key in evidence
        }
    return {"calibration": "uniform-null"}


def build_prompt(decision: dict) -> str:
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
        "candidates": candidates,
    }
    compact_json = json.dumps(
        input_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return (
        "你是 LOTTO//LAB 的終局裁判。這是純模擬；每個合法組合的理論開出機率相同，"
        "不得宣稱能預知隨機開獎。請只從下列 15 個 id 中依序挑出剛好 5 個，絕不可"
        "自創、修改或重複號碼。綜合評議分數與信心度、較低分歧、五組之間的主號"
        "分散、Agent 來源多樣性；將亂數修士視為零假設，避免把微弱歷史波動說成"
        "因果。summary 與每組 reason 請用精簡繁體中文，只寫可公開的決策依據，"
        "不要輸出思考過程。輸出必須符合指定 JSON Schema。\nDATA="
        + compact_json
    )


def adjudicate(
    decision: dict,
    *,
    generator: Callable[..., StructuredResponse] = generate_structured,
    model: str = MODEL,
) -> dict:
    """呼叫 qwen3:8b 並回傳已驗證、可公開的終局裁決資訊。"""
    allowed_ids = {
        proposal["proposal_id"] for proposal in decision["proposals"]
    }
    prompt = build_prompt(decision)
    prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    seed = int(decision["decision_hash"][:8], 16)
    try:
        response = generator(
            prompt,
            FINAL_SCHEMA,
            seed=seed,
            model=model,
        )
    except Exception as exc:
        raise QwenJudgeError(str(exc)) from exc
    if response.model != model:
        raise QwenJudgeError(
            f"模型不符：要求 {model}，實際 {response.model or 'unknown'}"
        )
    validated = validate_selection(response.payload, allowed_ids)
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
    }
