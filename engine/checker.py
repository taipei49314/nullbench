"""每週核對引擎：把帳本裡未核對的 (picks × 開獎期) 全部結算。

冪等性設計：
- 核對單位 = (week_id, game, period, portfolio)。已存在同鍵的 check 事件就跳過。
- 重跑 check 永遠安全；資料還沒開出的期數自動留待下次。
"""
from __future__ import annotations

from .games import GAME_NAMES, TICKET_PRICE, Draw, match_tier, prize_value
from .ledger import Ledger
from .store import DrawStore, draws_in_week

MAIN = "main"   # 主策略組合
NULL = "null"   # 純隨機對照組合


def settle_ticket(game: str, ticket: dict, draw: Draw) -> dict:
    """單張票 × 單期 → 結算結果。ticket = {numbers, special, analyst}。"""
    special = ticket.get("special")
    tier = match_tier(game, ticket["numbers"], special, draw)
    result = {
        "numbers": ticket["numbers"],
        "special": special,
        "analyst": ticket.get("analyst"),
        "cost": TICKET_PRICE[game],
        "tier": tier.rank if tier else None,
        "tier_label": tier.label if tier else None,
        "prize": 0,
        "estimated": False,
    }
    if tier:
        value, estimated = prize_value(tier, draw)
        result["prize"] = value
        result["estimated"] = estimated
    return result


def checked_keys(ledger: Ledger) -> set:
    return {
        (e["week"], e["game"], e["period"], e["portfolio"])
        for e in ledger.events_of("check")
    }


def pending_picks(ledger: Ledger) -> list[dict]:
    """最新版優先：同 (week, game) 的 picks 事件以最後一筆為準（--force 重出時舊事件作廢）。"""
    latest = {}
    for e in ledger.events_of("picks"):
        latest[(e["week"], e["game"])] = e
    return list(latest.values())


def run_check(ledger: Ledger, store: DrawStore) -> list[dict]:
    """結算所有未核對的期數，回傳新增的 check 事件清單（已寫入帳本）。"""
    done = checked_keys(ledger)
    new_events = []
    for picks in pending_picks(ledger):
        game, week = picks["game"], picks["week"]
        for draw in draws_in_week(store.draws(game), week):
            for portfolio, key in ((MAIN, "tickets"), (NULL, "null_tickets")):
                dedupe = (week, game, draw.period, portfolio)
                if dedupe in done or not picks.get(key):
                    continue
                tickets = [settle_ticket(game, t, draw) for t in picks[key]]
                cost = sum(t["cost"] for t in tickets)
                won = sum(t["prize"] for t in tickets)
                event = ledger.append("check", {
                    "week": week,
                    "game": game,
                    "game_name": GAME_NAMES[game],
                    "period": draw.period,
                    "draw_date": draw.date,
                    "draw_numbers": list(draw.numbers),
                    "draw_special": draw.special,
                    "portfolio": portfolio,
                    "tickets": tickets,
                    "cost": cost,
                    "won": won,
                    "net": won - cost,
                    "any_estimated": any(t["estimated"] for t in tickets),
                })
                done.add(dedupe)
                new_events.append(event)
    return new_events
