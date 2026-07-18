"""本地 Ollama AI 評論座位（可選）。

角色：每週辯論的「評論員」——讀各人格的陳述與近況統計，寫一段繁中評論收進辯論紀錄。
鐵律：評論員只能「評論」，不能改號碼——選號永遠出自決定性演算法（可重現）。
離線降級：Ollama 沒開或逾時 → 回傳 None，流程照常，辯論紀錄註記「評論員缺席」。
"""
from __future__ import annotations

import json
import re
import urllib.request

OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
# 座位模型選 qwen3:8b：它吃 think:false（實測 9 秒乾淨正文）。
# qwen3-vl:8b 無論 /no_think、think:false、generate/chat 端點都硬產思考鏈，
# num_predict 全被思考吃光、正文恆空（實測 2026-07-18），不可用於本席位。
MODEL = "qwen3:8b"
TIMEOUT = 300


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
