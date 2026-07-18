"""本地 Ollama AI 評論座位（可選）。

角色：每週辯論的「評論員」——讀各人格的陳述與近況統計，寫一段繁中評論收進辯論紀錄。
鐵律：評論員只能「評論」，不能改號碼——選號永遠出自決定性演算法（可重現）。
離線降級：Ollama 沒開或逾時 → 回傳 None，流程照常，辯論紀錄註記「評論員缺席」。
"""
from __future__ import annotations

import hashlib
import json
import re
import urllib.request
from dataclasses import dataclass

OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
# 座位模型選 qwen3:8b：它吃 think:false（實測 9 秒乾淨正文）。
# qwen3-vl:8b 無論 /no_think、think:false、generate/chat 端點都硬產思考鏈，
# num_predict 全被思考吃光、正文恆空（實測 2026-07-18），不可用於本席位。
MODEL = "qwen3:8b"
TIMEOUT = 300


@dataclass(frozen=True)
class StructuredResponse:
    payload: dict
    model: str
    response_hash: str
    total_duration: int | None
    eval_count: int | None


class OllamaRequestError(RuntimeError):
    """本機模型無法提供可驗證輸出。"""


def generate_structured(
    prompt: str,
    schema: dict,
    *,
    seed: int,
    url: str = OLLAMA_URL,
    model: str = MODEL,
    timeout: int = TIMEOUT,
) -> StructuredResponse:
    """要求 Ollama 依 JSON Schema 回覆；失敗時拋錯，由上層明確降級。"""
    body = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "think": False,
            "format": schema,
            "options": {
                "temperature": 0,
                "seed": seed,
                "num_ctx": 4096,
                "num_predict": 900,
            },
        },
        ensure_ascii=False,
    ).encode("utf-8")
    try:
        request = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise OllamaRequestError(f"Ollama 連線或回應失敗：{exc}") from exc

    response_model = str(data.get("model") or "")
    if response_model != model:
        raise OllamaRequestError(
            f"模型不符：要求 {model}，實際 {response_model or 'unknown'}"
        )
    raw = (data.get("response") or "").strip()
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    if not raw:
        raise OllamaRequestError("Ollama 回傳空白內容")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OllamaRequestError(f"Ollama 未回傳合法 JSON：{exc}") from exc
    if not isinstance(payload, dict):
        raise OllamaRequestError("Ollama JSON 根節點不是物件")
    return StructuredResponse(
        payload=payload,
        model=response_model,
        response_hash=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        total_duration=data.get("total_duration"),
        eval_count=data.get("eval_count"),
    )


def commentary(prompt: str, url: str = OLLAMA_URL, model: str = MODEL,
               timeout: int = TIMEOUT) -> str | None:
    """向本地模型要一段評論；任何失敗都回 None（絕不讓評論員拖垮流程）。"""
    body = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "options": {"temperature": 0.7, "num_predict": 800},
    }).encode("utf-8")
    try:
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text = (data.get("response") or "").strip()
        # 剝 <think>...</think> 思考前綴（qwen 系列的習慣）
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
        return text or None
    except Exception:
        return None
