"""每週核對（settle）：重放驗證 → 逐期結算 → 週結 → 權重更新。全程冪等。

單一程式碼路徑鐵則：正式票、影子票、null 票走同一個 _settle_ticket——
任何記帳 bug 會同時汙染各組而在「比較」中被抵銷（執行面偏差煙霧偵測器）。
"""
from __future__ import annotations

from datetime import date, timedelta

from . import config, strategy
from .games import GAME_NAMES, TICKET_PRICE, Draw, floor_table_from_history, match_tier, prize_value
from .ledger import Ledger
from .picker import GAMES, existing_picks, null_tickets, reproduce_check
from .store import DrawStore, draws_in_week, monday_of


def _settle_ticket(game: str, ticket: dict, draw: Draw, floor_table: dict) -> dict:
    tier = match_tier(game, ticket["numbers"], ticket.get("special"), draw)
    res = {"numbers": ticket["numbers"], "special": ticket.get("special"),
           "persona": ticket.get("persona"), "tier": None, "tier_label": None,
           "prize": 0, "basis": None, "upper": 0}
    if tier:
        value, basis, upper = prize_value(tier, draw, floor_table)
        res.update(tier=tier.rank, tier_label=tier.label, prize=value,
                   basis=basis, upper=upper)
    return res


def _settled_keys(settlements: Ledger) -> set:
    keys = set()
    for e in settlements.read_all():
        if e["type"] == "settle_draw":
            keys.add((e["game"], e["week"], e["period"]))
        elif e["type"] == "week_invalid":
            keys.add((e["game"], e["week"], "INVALID"))
    return keys


def _week_complete(event: dict, draws: list[Draw], today: date) -> bool:
    sunday = monday_of(event["week"]) + timedelta(days=6)
    if today > sunday:
        return True
    have = {d.date for d in draws}
    return all(x in have for x in event["expected_dates"])


def run_settle(picks_ledger: Ledger, settlements: Ledger, weights_ledger: Ledger,
               store: DrawStore, today: date) -> dict:
    """結算所有可結算的週。回傳摘要 {new_draw_events, new_weeks, invalid_weeks}。"""
    done = _settled_keys(settlements)
    summary = {"new_draw_events": 0, "new_weeks": 0, "invalid_weeks": []}

    for game in GAMES:
        weeks = sorted({e["week"] for e in picks_ledger.events_of("picks") if e["game"] == game})
        all_draws = store.draws(game)
        floor_table = floor_table_from_history(all_draws)
        for week in weeks:
            if monday_of(week) > today:
                continue
            event = existing_picks(picks_ledger, game, week)
            if not event:
                continue
            wdraws = draws_in_week(all_draws, week)
            if not wdraws:
                continue

            # (1) 可重現性檢查：失敗 = 整週 INVALID（冪等記一次）
            if not reproduce_check(event, store):
                if (game, week, "INVALID") not in done:
                    settlements.append("week_invalid", {
                        "game": game, "week": week,
                        "reason": "REPRODUCE_MISMATCH",
                        "note": "存檔種子重跑產號與凍結票不符，本週不計分，優先修 bug",
                    })
                    done.add((game, week, "INVALID"))
                    summary["invalid_weeks"].append((game, week))
                continue

            nulls = null_tickets(game, week)

            # (2) 逐期結算（冪等）
            for draw in wdraws:
                if (game, week, draw.period) in done:
                    continue
                official = [_settle_ticket(game, t, draw, floor_table) for t in event["tickets"]]
                shadow = [_settle_ticket(game, t, draw, floor_table) for t in event["shadow"]]
                null_flat = [_settle_ticket(game, t, draw, floor_table)
                             for port in nulls for t in port]
                null_hits = {}
                for r in null_flat:
                    if r["tier"]:
                        null_hits[str(r["tier"])] = null_hits.get(str(r["tier"]), 0) + 1
                settlements.append("settle_draw", {
                    "game": game, "game_name": GAME_NAMES[game], "week": week,
                    "period": draw.period, "draw_date": draw.date,
                    "draw_numbers": list(draw.numbers), "draw_special": draw.special,
                    "official": official, "shadow": shadow,
                    "official_cost": len(official) * TICKET_PRICE[game],
                    "official_won": sum(r["prize"] for r in official),
                    "null_hit_tiers": null_hits,
                    "null_total_prize": sum(r["prize"] for r in null_flat),
                    "any_estimated": any(r["basis"] == "estimated" for r in official),
                })
                done.add((game, week, draw.period))
                summary["new_draw_events"] += 1

            # (3) 週結＋權重更新（冪等鍵 (game, week) 由 record_weights 把關）
            if _week_complete(event, wdraws, today):
                if _settle_week(game, week, event, wdraws, nulls, floor_table,
                                settlements, weights_ledger):
                    summary["new_weeks"] += 1
    return summary


def _settle_week(game: str, week: str, event: dict, wdraws: list[Draw],
                 nulls: list, floor_table: dict,
                 settlements: Ledger, weights_ledger: Ledger) -> bool:
    """週結：影子分數 vs null 分布 → 權重更新；正式組雙帳本損益一併落檔。"""
    if any(e["game"] == game and e["week"] == week
           for e in weights_ledger.events_of("weights")):
        return False

    def week_prize(ticket) -> int:
        return sum(_settle_ticket(game, ticket, d, floor_table)["prize"] for d in wdraws)

    # null：1000 張票的當週獎金總額分布 ＋ 200 組投資組合當週 P&L
    null_ticket_totals = []
    null_portfolio_pnl = []
    per_draw_cost = TICKET_PRICE[game]
    for port in nulls:
        totals = [week_prize(t) for t in port]
        null_ticket_totals.extend(totals)
        null_portfolio_pnl.append(sum(totals) - 5 * per_draw_cost * len(wdraws))

    # 影子分數：r = 百分位（同分平均名次），s = r − 0.5
    scores = {}
    shadow_totals = {}
    for t in event["shadow"]:
        pid = t["persona"]
        total = week_prize(t)
        shadow_totals[pid] = total
        if pid in config.ADAPTIVE_PERSONAS:
            r = strategy.percentile_rank(total, null_ticket_totals)
            scores[pid] = r - 0.5

    settled_before = strategy.settled_week_count(weights_ledger, game)
    burn_in = settled_before < config.BURN_IN_WEEKS
    before = strategy.current_weights(weights_ledger, game)
    after = strategy.update_weights(before, scores, burn_in)

    # 正式組雙帳本：固定獎級（精確）與浮動獎級（估計）分開，永不加總成單一英雄數字
    fixed_won = floating_won = 0
    estimated_won = 0
    ex_top2_won = 0
    for d in wdraws:
        for t in event["tickets"]:
            r = _settle_ticket(game, t, d, floor_table)
            if r["basis"] == "fixed":
                fixed_won += r["prize"]
            elif r["basis"] in ("counterfactual", "estimated"):
                floating_won += r["prize"]
                if r["basis"] == "estimated":
                    estimated_won += r["prize"]
            if r["tier"] and r["tier"] > 2:
                ex_top2_won += r["prize"]
    cost = 5 * per_draw_cost * len(wdraws)

    strategy.record_weights(weights_ledger, game, week, before, after, scores,
                            null_portfolio_pnl, extras={
        "burn_in": burn_in,
        "late": event.get("late", False),
        "shadow_totals": shadow_totals,
        "official_cost": cost,
        "official_fixed_won": fixed_won,
        "official_floating_won": floating_won,
        "official_estimated_won": estimated_won,
        "official_ex_top2_won": ex_top2_won,
        "n_draws": len(wdraws),
        "dup_flags": sum(1 for t in event["tickets"] if t.get("dup")),
        "relaxed": [t.get("meta", {}).get("relaxed") for t in event["tickets"]
                    if t.get("meta", {}).get("relaxed")],
    })
    return True
