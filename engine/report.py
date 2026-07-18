"""繁中週報：結論先行、null 併列、雙帳本、禁用詞 lint。

排版鐵則（裁決書）：
- 首段固定模板句，不可刪。
- 每週數字區只出描述統計與百分位；正式 p 值只在第 26/52 已核對週檢查點出現。
- 固定獎級 P&L（精確）與浮動獎級 P&L（估計）永不加總成單一英雄數字。
"""
from __future__ import annotations

from datetime import date

from . import config, strategy
from .analysts import NAMES
from .env import Env
from .games import SUPER, LOTTO649, GAME_NAMES, TICKET_PRICE
from .picker import GAMES
from .seeds import mc_rng


class ReportLintError(Exception):
    pass


def lint(text: str) -> list[tuple[int, str]]:
    """掃描禁用詞；引用區（> 開頭，AI 評論已帶標記前綴）豁免。"""
    hits = []
    for i, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith(">"):
            continue
        for w in config.FORBIDDEN_WORDS:
            if w in line:
                hits.append((i, w))
    return hits


def _valid_week_events(env: Env, game: str) -> list[dict]:
    """正式統計樣本：已核對且非 LATE 的週（INVALID 週根本沒有 weights 事件）。"""
    return [e for e in strategy.weight_events(env.weights, game) if not e.get("late")]


def _cumulative(env: Env, game: str) -> dict:
    events = strategy.weight_events(env.weights, game)
    valid = _valid_week_events(env, game)
    cum = {
        "weeks": len(events), "valid_weeks": len(valid),
        "cost": sum(e["official_cost"] for e in events),
        "fixed_won": sum(e["official_fixed_won"] for e in events),
        "floating_won": sum(e["official_floating_won"] for e in events),
        "estimated_won": sum(e["official_estimated_won"] for e in events),
        "ex_top2_won": sum(e["official_ex_top2_won"] for e in events),
    }
    # 主要終點素材（valid 週）：正式組累計 P&L vs 200 組 null 累計 P&L
    if valid:
        official_cum = sum(e["official_fixed_won"] + e["official_floating_won"]
                           - e["official_cost"] for e in valid)
        null_cum = [0] * config.NULL_PORTFOLIOS
        for e in valid:
            for i, v in enumerate(e["null_portfolio_pnl"]):
                null_cum[i] += v
        cum["official_pnl_valid"] = official_cum
        cum["null_cum"] = null_cum
        cum["percentile"] = strategy.percentile_rank(official_cum, null_cum)
    return cum


def _permutation_p(env: Env, game: str, checkpoint: int) -> float:
    """檢查點置換檢定：每週從 200 組 null 抽一組重組累計 P&L，重抽 10,000 次。"""
    valid = _valid_week_events(env, game)
    official_cum = sum(e["official_fixed_won"] + e["official_floating_won"]
                      - e["official_cost"] for e in valid)
    rng = mc_rng(f"cp{checkpoint}", game)
    n = config.PERMUTATIONS
    le = ge = 0
    for _ in range(n):
        s = sum(e["null_portfolio_pnl"][rng.randrange(config.NULL_PORTFOLIOS)]
                for e in valid)
        if s <= official_cum:
            le += 1
        if s >= official_cum:
            ge += 1
    return min(1.0, 2 * min(le + 1, ge + 1) / (n + 1))


def _week_detail(env: Env, game: str, week: str) -> list[str]:
    lines = []
    draws = [e for e in env.settlements.events_of("settle_draw")
             if e["game"] == game and e["week"] == week]
    if not draws:
        return [f"（{GAME_NAMES[game]} 本週尚無已結算期數）", ""]
    for ev in sorted(draws, key=lambda e: e["period"]):
        nums = " ".join(f"{n:02d}" for n in ev["draw_numbers"])
        sp = f"{ev['draw_special']:02d}"
        sp_label = "第二區" if game == SUPER else "特別號"
        lines.append(f"**第 {ev['period']} 期（{ev['draw_date']}）** 開獎：{nums}｜{sp_label} {sp}")
        lines.append("")
        lines.append("| 席 | 人格 | 號碼 | 結果 | 虛擬獎金 | 估值基礎 |")
        lines.append("|---|------|------|------|---------:|----------|")
        for i, r in enumerate(ev["official"], 1):
            tnums = " ".join(f"{n:02d}" for n in r["numbers"])
            if r.get("special"):
                tnums += f" ＋{r['special']:02d}"
            hit = r["tier_label"] or "未中"
            basis = {"fixed": "固定", "counterfactual": "反事實", "estimated": "估值", None: "—"}[r["basis"]]
            lines.append(f"| {i} | {NAMES[r['persona']]} | {tnums} | {hit} | {r['prize']:,} | {basis} |")
        won = ev["official_won"]
        lines.append("")
        lines.append(f"本期正式組：成本 {ev['official_cost']:,} 元、獎金 {won:,} 元；"
                     f"null 對照 1,000 注共中 {sum(ev['null_hit_tiers'].values())} 注。")
        lines.append("")
    return lines


def build_report(env: Env, week: str, today: date | None = None) -> str:
    today = today or date.today()
    L = []

    # ---- 固定模板首段（不可刪）----
    cps = []
    for game in GAMES:
        n_valid = len(_valid_week_events(env, game))
        cp = next((c for c in sorted(config.CHECKPOINTS) if n_valid == c), None)
        if cp:
            p = _permutation_p(env, game, cp)
            cps.append(f"{GAME_NAMES[game]} 第 {cp} 週檢查點 p={p:.4f}"
                       f"（α={config.CHECKPOINTS[cp]}，{'顯著' if p < config.CHECKPOINTS[cp] else '不顯著'}）")
    verdictline = "；".join(cps) if cps else "無任何策略顯著異於隨機（主要終點僅於第 26／52 個已核對週正式檢定）"
    L.append(f"# lotto-lab 週報 {week}")
    L.append("")
    L.append(f"**本系統為負期望值之純模擬實驗，統計上每期獨立；截至本週，{verdictline}。**")
    L.append("")
    L.append("> 每週數字為描述性、未經順序校正、不得據以下結論。純模擬，不下注。")
    L.append("")

    # ---- 各遊戲 ----
    for game in GAMES:
        cum = _cumulative(env, game)
        L.append(f"## {GAME_NAMES[game]}")
        L.append("")
        L += _week_detail(env, game, week)
        L.append(f"### 累計（{cum['weeks']} 個已核對週，其中正式樣本 {cum['valid_weeks']} 週）")
        L.append("")
        L.append("| 帳本 | 金額 |")
        L.append("|------|-----:|")
        L.append(f"| 累計虛擬成本 | {cum['cost']:,} 元 |")
        L.append(f"| 固定獎級獎金（精確） | {cum['fixed_won']:,} 元 |")
        L.append(f"| 浮動獎級獎金（估計） | {cum['floating_won']:,} 元 |")
        L.append(f"| 穩健版：排除頭／貳獎後獎金 | {cum['ex_top2_won']:,} 元 |")
        L.append("")
        if "percentile" in cum:
            pct = cum["percentile"] * 100
            null_mean = sum(cum["null_cum"]) / len(cum["null_cum"])
            L.append(f"主要終點素材（描述性）：正式組累計損益 **{cum['official_pnl_valid']:,} 元**，"
                     f"落在 200 組純隨機對照組合的第 **{pct:.1f}** 百分位"
                     f"（null 平均 {null_mean:,.0f} 元）。")
            L.append("")
        won_total = cum["fixed_won"] + cum["floating_won"]
        if won_total and cum["estimated_won"] / won_total > config.ESTIMATED_WARN_RATIO:
            L.append(f"⚠ 估值獎金占比 {cum['estimated_won']/won_total:.0%} 超過 "
                     f"{config.ESTIMATED_WARN_RATIO:.0%}——浮動獎級估值可能主導敘事，解讀請以穩健版為準。")
            L.append("")

    # ---- 權重軌跡 ----
    L.append("## 權重軌跡（被研究的展品，不是引擎）")
    L.append("")
    for game in GAMES:
        events = strategy.weight_events(env.weights, game)
        if not events:
            continue
        L.append(f"**{GAME_NAMES[game]}**（最近 {min(8, len(events))} 週）")
        L.append("")
        L.append("| 週 | " + " | ".join(NAMES[p] for p in config.ADAPTIVE_PERSONAS) + " |")
        L.append("|---|" + "---|" * len(config.ADAPTIVE_PERSONAS))
        for e in events[-8:]:
            row = " | ".join(f"{e['after'][p]:.3f}" for p in config.ADAPTIVE_PERSONAS)
            L.append(f"| {e['week']}{'（burn-in）' if e.get('burn_in') else ''} | {row} |")
        L.append("")
    L.append("誠實註記：理論預期權重長期呈無趨勢隨機漫步；「軌跡漫步」本身就是"
             "「無人格可分辨」的證據，不得把漂移說成學習。")
    L.append("")

    # ---- 探索性 ----
    L.append("## 探索性指標（明標探索性，永不作顯著性宣稱）")
    L.append("")
    for game in GAMES:
        events = strategy.weight_events(env.weights, game)
        if not events:
            continue
        totals: dict[str, int] = {}
        cost_per_week = []
        for e in events:
            for pid, v in e.get("shadow_totals", {}).items():
                totals[pid] = totals.get(pid, 0) + v
            cost_per_week.append(TICKET_PRICE[game] * e.get("n_draws", 2))
        shadow_cost = sum(cost_per_week)
        if shadow_cost:
            L.append(f"**{GAME_NAMES[game]}** 影子票累計 ROI（每人格每週 1 注同投全部期數）：")
            L.append("")
            for pid in sorted(totals):
                roi = totals[pid] / shadow_cost - 1
                L.append(f"- {NAMES[pid]}：獎金 {totals[pid]:,} 元／成本 {shadow_cost:,} 元"
                         f"（ROI {roi:+.1%}）")
            L.append("")

    # ---- 資料品質 ----
    L.append("## 資料品質")
    L.append("")
    invalids = env.settlements.events_of("week_invalid")
    for game in GAMES:
        events = strategy.weight_events(env.weights, game)
        n_inv = sum(1 for e in invalids if e["game"] == game)
        n_late = sum(1 for e in events if e.get("late"))
        n_dup = sum(e.get("dup_flags", 0) for e in events)
        n_relaxed = sum(len(e.get("relaxed", [])) for e in events)
        total_weeks = len(events) + n_inv
        inv_ratio = n_inv / total_weeks if total_weeks else 0.0
        flag = "🔴" if inv_ratio > config.INVALID_WARN_RATIO else "OK"
        L.append(f"- {GAME_NAMES[game]}：INVALID {n_inv} 週（{inv_ratio:.0%}，{flag}）、"
                 f"LATE {n_late} 週、DUP 票 {n_dup}、均衡工程師放寬 {n_relaxed} 次。")
    L.append("")

    # ---- 委員會紀要 ----
    notes = [e for e in env.commentary.events_of("commentary") if e["week"] == week]
    if notes:
        L.append("## 委員會紀要（AI 評論，非決策依據）")
        L.append("")
        for e in notes:
            phase = "出號" if e["phase"] == "generate" else "核對"
            L.append(f"**{phase}階段**{'（本地 qwen3:8b）' if e['ai'] else '（模板代打）'}：")
            L.append("")
            for line in e["text"].splitlines():
                L.append(f"> {line}")
            L.append("")

    L.append("---")
    L.append(f"資料範圍：威力彩 2008-01 起、大樂透 2007-01 起（官方 API 全歷史；"
             f"2004–2006 北富銀時代官方不提供）。experiment_id={config.EXPERIMENT_ID}。")
    L.append("")
    return "\n".join(L)


def write_report(env: Env, week: str, today: date | None = None) -> str:
    text = build_report(env, week, today)
    hits = lint(text)
    if hits:
        raise ReportLintError(f"報告含禁用詞，拒絕產檔：{hits}")
    out = env.reports_dir / f"{week}.md"
    out.write_text(text, encoding="utf-8")
    return str(out)
