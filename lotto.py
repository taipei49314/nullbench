"""lotto-lab：虛擬彩票研究室 CLI（純模擬，不下注）。

指令（全部手動觸發、零排程零推播）：
  python lotto.py ingest    抓取／更新台彩官方全歷史開獎資料
  python lotto.py picks     本週出號：辯論＋威力彩/大樂透各 5 組＋凍結預註冊
  python lotto.py check     每週核對：結算所有未結算期數＋權重更新＋產報告
  python lotto.py report    重新產出指定/最新週的報告
  python lotto.py status    總覽：權重、累計損益 vs null、下次開獎
  python lotto.py loop      逐期 agent 提案→辯論→裁決→揭曉→檢討的完整純模擬
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")  # Windows cp950 教訓（ai-company）
    sys.stderr.reconfigure(encoding="utf-8")

from engine import agent_loop, config, debate, picker, report, settle, strategy
from engine.analysts import NAMES
from engine.env import Env
from engine.fetch import ingest as fetch_ingest
from engine.games import SUPER, LOTTO649, GAME_NAMES
from engine.ledger import TAIPEI
from engine.store import week_dates


def _now() -> datetime:
    return datetime.now(TAIPEI)


def cmd_ingest(env: Env) -> None:
    for game in picker.GAMES:
        total, fetched = fetch_ingest(game, env.data_dir)
        draws = env.store.draws(game)
        print(f"{GAME_NAMES[game]}：{len(draws)} 期在庫"
              f"（{draws[0].date} ~ {draws[-1].date}；本次更新 {fetched} 個月份）")


def _print_tickets(event: dict) -> None:
    for t in event["tickets"]:
        nums = " ".join(f"{n:02d}" for n in t["numbers"])
        sp = f" ＋第二區 {t['special']:02d}" if t.get("special") else ""
        flags = " [DUP]" if t.get("dup") else ""
        relaxed = t.get("meta", {}).get("relaxed")
        if relaxed:
            flags += f" [放寬:{','.join(relaxed)}]"
        print(f"  第{t['slot']}席 {NAMES[t['persona']]:6s} {nums}{sp}{flags}")


def cmd_picks(env: Env, week: str | None) -> None:
    now = _now()
    results = picker.generate(env.picks, env.weights, env.store, now, week)
    wk = next(iter(results.values()))["event"]["week"]
    print(f"== 週 {wk} 出號（experiment {config.EXPERIMENT_ID}，純模擬）==")
    for game in picker.GAMES:
        r = results[game]
        ev = r["event"]
        state = "既有凍結票（冪等 no-op）" if r["existing"] else "新出號，已凍結預註冊"
        late = "｜⚠ LATE（晚於首期開獎，不入正式統計）" if ev.get("late") else ""
        print(f"\n-- {GAME_NAMES[game]}：{state}{late}")
        print(f"   開獎日 {ev['expected_dates']}｜content_hash {ev['content_hash'][:16]}…")
        _print_tickets(ev)
    fresh = {g: r for g, r in results.items() if not r["existing"]}
    if fresh:
        print("\n== 董事會陳述 ==")
        for game, r in fresh.items():
            from engine.store import monday_of
            history = env.store.before(game, monday_of(wk).isoformat())
            print(f"\n-- {GAME_NAMES[game]}")
            for line in debate.persona_statements(game, history, r["event"]):
                print(line)
        print("\n== AI 評論座位 ==")
        print(debate.generate_commentary(wk, fresh, env.commentary))
    print("\n下一步：該週開獎後執行 python lotto.py check")


def cmd_check(env: Env, no_fetch: bool = False) -> None:
    today = _now().date()
    if not no_fetch:
        print("更新開獎資料…")
        for game in picker.GAMES:
            fetch_ingest(game, env.data_dir)
    summary = settle.run_settle(env.picks, env.settlements, env.weights, env.store, today)
    print(f"結算：{summary['new_draw_events']} 期新結算、{summary['new_weeks']} 週完成週結"
          + (f"、INVALID：{summary['invalid_weeks']}" if summary["invalid_weeks"] else ""))
    weeks = sorted({e["week"] for e in env.settlements.events_of("settle_draw")})
    if not weeks:
        print("尚無可結算的期數（先跑 python lotto.py picks 出號，等開獎後再核對）。")
        return
    latest = weeks[-1]
    if summary["new_weeks"]:
        digest = {}
        for game in picker.GAMES:
            ev = [e for e in strategy.weight_events(env.weights, game) if e["week"] == latest]
            if ev:
                e = ev[0]
                digest[GAME_NAMES[game]] = {
                    "成本": e["official_cost"],
                    "固定獎級獎金": e["official_fixed_won"],
                    "浮動獎級獎金": e["official_floating_won"],
                    "影子票": e.get("shadow_totals", {}),
                }
        debate.settle_commentary(latest, digest, env.commentary)
    path = report.write_report(env, latest)
    print(f"報告：{path}")


def cmd_report(env: Env, week: str | None) -> None:
    weeks = sorted({e["week"] for e in env.settlements.events_of("settle_draw")}
                   | {e["week"] for e in env.picks.events_of("picks")})
    if not weeks:
        print("尚無任何紀錄。")
        return
    wk = week or weeks[-1]
    print(f"報告：{report.write_report(env, wk)}")


def cmd_status(env: Env) -> None:
    print(f"== lotto-lab 狀態（experiment {config.EXPERIMENT_ID}，純模擬不下注）==")
    for game in picker.GAMES:
        draws = env.store.draws(game)
        n_weeks = strategy.settled_week_count(env.weights, game)
        w = strategy.current_weights(env.weights, game)
        burn = "（burn-in 凍結中）" if n_weeks < config.BURN_IN_WEEKS else ""
        print(f"\n-- {GAME_NAMES[game]}：庫存 {len(draws)} 期（最新 {draws[-1].date}）、"
              f"已核對 {n_weeks} 週")
        print("   權重" + burn + "：" +
              "、".join(f"{NAMES[p]} {w[p]:.3f}" for p in config.ADAPTIVE_PERSONAS))
        wk = picker.target_week(_now())
        print(f"   下個目標週 {wk}：開獎日 {week_dates(wk, game)}")
    pending = [e["week"] for e in env.picks.events_of("picks")]
    if pending:
        settled = {e["week"] for e in env.weights.events_of("weights")}
        waiting = sorted({w for w in pending if w not in settled})
        if waiting:
            print(f"\n待核對週：{waiting}（開獎後跑 python lotto.py check）")


def _print_loop_decision(decision: dict) -> None:
    target = decision["target"]
    print(f"  下一期：{target['date']}｜模擬期別 {target['period']}")
    for ticket in decision["selected_tickets"]:
        nums = " ".join(f"{number:02d}" for number in ticket["numbers"])
        special = (
            f" ＋第二區 {ticket['special']:02d}"
            if ticket.get("special") is not None
            else ""
        )
        print(
            f"  第{ticket['slot']}注 {nums}{special}"
            f"｜來源 {NAMES[ticket['source_agent']]}"
        )
    print(f"  decision_hash：{decision['decision_hash']}")


def cmd_loop(env: Env, output: str | None) -> None:
    output_dir = (
        env.base / "simulation" / "results"
        if output is None
        else env.base / output
    )
    print("執行逐期 agent 閉環：歷史觀察 → 提案 → 交叉辯論 → 裁決 → 揭曉 → 檢討")
    manifest = agent_loop.run_all(env.store, output_dir)
    for game in picker.GAMES:
        result = manifest["games"][game]
        print(
            f"\n-- {GAME_NAMES[game]}：完整回放 {result['draws_replayed']} 期"
            f"｜鏈驗證 {result['verification']['lines']} 期"
            f"｜ledger SHA-256 {result['ledger_sha256']}"
        )
        _print_loop_decision(result["next_decision"])
    print(f"\n模擬產物：{output_dir}")
    print(f"manifest_hash：{manifest['manifest_hash']}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="lotto-lab 虛擬彩票研究室（純模擬）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ingest")
    p = sub.add_parser("picks")
    p.add_argument("--week", help="指定週（如 2026-W30），預設自動判定")
    c = sub.add_parser("check")
    c.add_argument("--no-fetch", action="store_true", help="不先更新開獎資料")
    r = sub.add_parser("report")
    r.add_argument("--week")
    sub.add_parser("status")
    loop = sub.add_parser("loop")
    loop.add_argument(
        "--output",
        help="相對專案根目錄的輸出資料夾（預設 simulation/results）",
    )
    args = ap.parse_args(argv)

    env = Env()
    if args.cmd == "ingest":
        cmd_ingest(env)
    elif args.cmd == "picks":
        cmd_picks(env, args.week)
    elif args.cmd == "check":
        cmd_check(env, args.no_fetch)
    elif args.cmd == "report":
        cmd_report(env, args.week)
    elif args.cmd == "status":
        cmd_status(env)
    elif args.cmd == "loop":
        cmd_loop(env, args.output)


if __name__ == "__main__":
    main()
