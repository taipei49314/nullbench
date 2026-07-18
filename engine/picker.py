"""每週出號（generate）：席位分配 → 決定性產號 → 去重 → 預註冊凍結。

冪等：同 (game, week) 已有 FROZEN 事件即 no-op 回傳既有事件。
--force 僅在該週該遊戲無任何結算紀錄時允許，舊事件標記 superseded（append-only，不刪）。
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from pathlib import Path

from . import config
from .analysts import PERSONAS
from .games import SUPER, LOTTO649, GAME_NAMES
from .ledger import Ledger, TAIPEI
from .seeds import content_hash, rng_for
from .store import DrawStore, monday_of, week_dates, week_id_of

GAMES = (SUPER, LOTTO649)


def code_hash(engine_dir: Path | None = None) -> str:
    """engine/*.py 全檔內容的 SHA-256——事後改程式碼無法假裝『當初就是這樣選的』。"""
    d = engine_dir or Path(__file__).parent
    h = hashlib.sha256()
    for f in sorted(d.glob("*.py")):
        h.update(f.name.encode())
        h.update(f.read_bytes())
    return h.hexdigest()


def first_draw_dt(game: str, week_id: str) -> datetime:
    first = week_dates(week_id, game)[0]
    hh, mm = (int(x) for x in config.LATE_CUTOFF_TIME.split(":"))
    return datetime.fromisoformat(first).replace(hour=hh, minute=mm, tzinfo=TAIPEI)


def target_week(now: datetime) -> str:
    """本週首期（週一）截止前 → 本週；否則下週。"""
    this_week = week_id_of(now.date())
    if now < first_draw_dt(SUPER, this_week):
        return this_week
    return week_id_of(monday_of(this_week) + timedelta(days=7))


def _gen_ticket(persona_id: str, game: str, history, week_id: str,
                stream: str, slot: int, retry: int = 0) -> dict:
    rng = rng_for(game, week_id, stream, persona_id, slot, retry)
    out = PERSONAS[persona_id](game, history, rng)
    return {"slot": slot, "persona": persona_id, "numbers": out["numbers"],
            "special": out["special"], "retry": retry, **({"meta": out["meta"]} if out["meta"] else {})}


def build_official(game: str, history, week_id: str, seat_alloc: dict[str, int]) -> list[dict]:
    """第 1 席永遠亂數修士；2~5 席依 persona_id 字典序連續佔位。去重 retry ≤ 20。"""
    plan = [(config.RESERVED_PERSONA, 1)]
    slot = 2
    for pid in config.ADAPTIVE_PERSONAS:  # 已是字典序
        for _ in range(seat_alloc.get(pid, 0)):
            plan.append((pid, slot))
            slot += 1
    tickets: list[dict] = []
    seen: set[frozenset] = set()
    for pid, k in plan:
        t = _gen_ticket(pid, game, history, week_id, "official", k)
        retry = 0
        while frozenset(t["numbers"]) in seen and retry < config.DEDUP_MAX_RETRY:
            retry += 1
            t = _gen_ticket(pid, game, history, week_id, "official", k, retry)
        if frozenset(t["numbers"]) in seen:
            t["dup"] = True
        seen.add(frozenset(t["numbers"]))
        tickets.append(t)
    return tickets


def build_shadow(game: str, history, week_id: str) -> list[dict]:
    """每人格每週每遊戲恰好 1 組影子票——評分資料量不因席位縮水。"""
    return [_gen_ticket(pid, game, history, week_id, "shadow", 1)
            for pid in sorted(PERSONAS)]


def null_tickets(game: str, week_id: str) -> list[list[dict]]:
    """200 組 × 5 注純隨機對照——獨立種子命名空間，不落主帳本、可隨時重放。"""
    monk = PERSONAS[config.RESERVED_PERSONA]
    ports = []
    for p in range(config.NULL_PORTFOLIOS):
        port = []
        for k in range(1, 6):
            rng = rng_for(game, week_id, f"null|port{p}", config.RESERVED_PERSONA, k)
            out = monk(game, [], rng)
            port.append({"numbers": out["numbers"], "special": out["special"]})
        ports.append(port)
    return ports


def existing_picks(picks_ledger: Ledger, game: str, week_id: str) -> dict | None:
    superseded = {e.get("supersedes") for e in picks_ledger.events_of("supersede")}
    for e in picks_ledger.events_of("picks"):
        if e["game"] == game and e["week"] == week_id and e["content_hash"] not in superseded:
            return e
    return None


def generate(picks_ledger: Ledger, weights_ledger: Ledger, store: DrawStore,
             now: datetime, week_id: str | None = None) -> dict:
    """兩遊戲各出 5 組正式票＋5 組影子票，凍結預註冊。回傳 {game: event}。"""
    from . import strategy

    week_id = week_id or target_week(now)
    monday = monday_of(week_id).isoformat()
    results = {}
    for game in GAMES:
        found = existing_picks(picks_ledger, game, week_id)
        if found:
            results[game] = {"event": found, "existing": True}
            continue
        history = store.before(game, monday)
        burn_in = strategy.settled_week_count(weights_ledger, game) < config.BURN_IN_WEEKS
        weights = strategy.UNIFORM if burn_in else strategy.current_weights(weights_ledger, game)
        seat_alloc = strategy.allocate_seats(weights)
        official = build_official(game, history, week_id, seat_alloc)
        shadow = build_shadow(game, history, week_id)
        late = now > first_draw_dt(game, week_id)
        core = {
            "experiment_id": config.EXPERIMENT_ID,
            "game": game, "week": week_id,
            "expected_dates": week_dates(week_id, game),
            "weights_snapshot": {p: round(v, 6) for p, v in weights.items()},
            "seat_allocation": seat_alloc,
            "tickets": official, "shadow": shadow,
            "history_draws_used": len(history),
            "burn_in": burn_in,
        }
        chash = content_hash(json.dumps(core, ensure_ascii=False, sort_keys=True))
        event = picks_ledger.append("picks", {
            **core,
            "status": "FROZEN",
            "late": late,
            "content_hash": chash,
            "code_hash": code_hash(),
            "game_name": GAME_NAMES[game],
        })
        results[game] = {"event": event, "existing": False}
    return results


def reproduce_check(event: dict, store: DrawStore) -> bool:
    """核對前重放：用同種子重跑產號，號碼必須位元級一致；不符 = 整週 INVALID。"""
    game, week_id = event["game"], event["week"]
    monday = monday_of(week_id).isoformat()
    history = store.before(game, monday)
    official = build_official(game, history, week_id, event["seat_allocation"])
    shadow = build_shadow(game, history, week_id)
    def key(ts):
        return [(t["persona"], t["numbers"], t["special"]) for t in ts]
    return key(official) == key(event["tickets"]) and key(shadow) == key(event["shadow"])
