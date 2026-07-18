"""每週董事會：人格陳述（決定性）＋ 本地 AI 評論座位（可選、非決策）。

鐵律：評論永遠不進入選號與權重管線；含禁用詞的 AI 評論原文保留但加標記前綴。
"""
from __future__ import annotations

import json
from collections import Counter

from . import config
from .analysts import NAMES, SLOGANS
from .games import GAME_NAMES
from .ledger import Ledger
from .ollama_seat import commentary as ollama_commentary
from .stats import gaps, main_freq


def _fmt(t: dict) -> str:
    sp = f" ＋第二區 {t['special']:02d}" if t.get("special") else ""
    return " ".join(f"{n:02d}" for n in t["numbers"]) + sp


def persona_statements(game: str, history, picks_event: dict) -> list[str]:
    """各人格的決定性陳述——只描述自己的統計視角與所出號碼，不做預測宣稱。"""
    lines = []
    by_persona: dict[str, list] = {}
    for t in picks_event["tickets"]:
        by_persona.setdefault(t["persona"], []).append(t)
    freq = main_freq(history, config.HOT_HUNTER["W"])
    g = gaps(history, game)
    hot = " ".join(f"{n:02d}" for n, _ in freq.most_common(6))
    cold = " ".join(f"{n:02d}" for n, _ in sorted(g.items(), key=lambda kv: -kv[1])[:6])
    views = {
        "random_monk": f"我不看歷史。均勻抽樣是所有人的基準線，我的成績就是照妖鏡。",
        "hot_hunter": f"近 {config.HOT_HUNTER['W']} 期最常出現：{hot}。我沿著出現頻率加權抽樣。",
        "cold_keeper": f"目前遺漏最深：{cold}。我知道這是賭徒謬誤，我的存在就是讓它被檢驗。",
        "balance_engineer": "我拒絕和值偏斜、連號成串、尾數擁擠的組合——講究得毫無用處也要講究。",
        "antipop_taoist": "我避開 1~31 的生日號碼帶。這不改變中獎機率，只影響同額中獎時的分彩。",
    }
    for pid in sorted(NAMES):
        seats = by_persona.get(pid, [])
        seat_str = ("、".join(_fmt(t) for t in seats)) if seats else "（本週無正式席位，影子票照跑）"
        lines.append(f"- **{NAMES[pid]}**「{SLOGANS[pid]}」：{views[pid]} 本週：{seat_str}")
    return lines


def _guard_text(text: str) -> str:
    if any(w in text for w in config.FORBIDDEN_WORDS):
        return "[違規敘事，僅供紀錄] " + text
    return text


def generate_commentary(week: str, picks_events: dict, commentary_ledger: Ledger) -> str:
    """出號後的 AI 會議紀要（150 字內）；離線以決定性模板代打。"""
    payload = {
        "week": week,
        "games": {
            g: {
                "weights": ev["event"]["weights_snapshot"],
                "seats": ev["event"]["seat_allocation"],
                "tickets": [{"persona": t["persona"], "numbers": t["numbers"],
                             "special": t["special"]} for t in ev["event"]["tickets"]],
            } for g, ev in picks_events.items()
        },
    }
    prompt = (
        "你是彩票純模擬實驗的董事會評論員。科學鐵律：每期開獎獨立、期望值為負，"
        "任何『預測、必中、即將開出、勝率提升、破解』的說法都是違規敘事。"
        "你永遠不產生號碼，只評論。\n"
        f"本週（{week}）出號資料：\n{json.dumps(payload, ensure_ascii=False)}\n"
        "請用繁體中文寫 150 字內的『董事會會議紀要』風格評論，"
        "並指出本週組合裡最像『賭徒謬誤敘事』的一句話。"
    )
    text = ollama_commentary(prompt)
    ai = text is not None
    if not ai:
        text = ("（本週 AI 評論座位離線，以模板代打）本週依既定權重與種子出號完成，"
                "全部號碼已凍結預註冊。提醒：所有人格的長期績效預期與純隨機無異，"
                "本實驗的正式問題是驗證這件事。")
    text = _guard_text(text)
    commentary_ledger.append("commentary", {
        "week": week, "phase": "generate", "ai": ai, "text": text,
        "note": "AI 評論，非決策依據",
    })
    return text


def settle_commentary(week: str, digest: dict, commentary_ledger: Ledger) -> str:
    """核對後的 AI 紅隊評論；離線以模板代打。digest = report 端整理的當週結果摘要。"""
    prompt = (
        "你是彩票純模擬實驗的紅隊評論員。鐵律：每期獨立、期望值為負；"
        "禁用詞：預測、必中、即將開出、勝率提升、破解。\n"
        f"當週（{week}）結果摘要：\n{json.dumps(digest, ensure_ascii=False)}\n"
        "請以繁體中文完成三件事，200 字內：(1) 先複誦『本系統為負期望值之純模擬實驗，"
        "統計上每期獨立』再摘要戰績；(2) 紅隊審查：指出摘要中任何聽起來像預測宣稱的表述；"
        "(3) 至多提出一個以假設句式表述的參數實驗建議（僅供人類決定是否開新實驗版本）。"
    )
    text = ollama_commentary(prompt)
    ai = text is not None
    if not ai:
        text = ("（本週 AI 評論座位離線，以模板代打）本系統為負期望值之純模擬實驗，"
                "統計上每期獨立。本週核對完成，詳見報告數字區；"
                "一切差異在未通過檢查點檢定前一律視為抽樣噪音。")
    text = _guard_text(text)
    commentary_ledger.append("commentary", {
        "week": week, "phase": "settle", "ai": ai, "text": text,
        "note": "AI 評論，非決策依據",
    })
    return text
