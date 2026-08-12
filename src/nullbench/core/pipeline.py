"""Golden path: init → strategy → freeze → settle → report."""

from __future__ import annotations

from pathlib import Path

from nullbench.core.hashing import code_fingerprint, content_hash
from nullbench.core.models import (
    ClaimStatus,
    Draw,
    ExperimentSpec,
    FreezeRecord,
    PortfolioResult,
    ReportSummary,
    SettleRecord,
    StrategySpec,
    Ticket,
)
from nullbench.core.nullbank import evaluate_null_bank
from nullbench.core.settle_math import portfolio_cost, portfolio_payout
from nullbench.core.study import Study
from nullbench.domains import game_for, get_domain
from nullbench.errors import (
    DataError,
    FreezeError,
    SettleError,
    StrategyError,
    StudyExistsError,
    StudyNotFoundError,
)
from nullbench.scoring.summary import period_score_summary
from nullbench.strategies import get_strategy


def init_study(
    root: Path,
    *,
    experiment_id: str,
    domain: str = "demo649",
    null_portfolios: int = 200,
    null_seed: int = 42,
    demo_draws: int = 120,
    fetch: bool = False,
    max_months: int | None = None,
) -> ExperimentSpec:
    from nullbench.core.workspace import write_study_readme

    study = Study(root)
    if study.exists():
        raise StudyExistsError(
            f"study already exists: {root}",
            hint="pick a new directory name, or continue with status/next",
        )
    study.ensure_layout()
    game = game_for(domain)
    mod = get_domain(domain)
    if domain == "demo649":
        mod.write_demo_data(study.draws_path, n=demo_draws)
    elif hasattr(mod, "prepare_data") and fetch:
        mod.prepare_data(study.data_dir, max_months=max_months)
    elif not study.draws_path.exists():
        study.draws_path.write_text("", encoding="utf-8")

    spec = ExperimentSpec(
        experiment_id=experiment_id,
        domain=domain,
        game=game,
        strategies=[],
        null_portfolios=null_portfolios,
        null_seed=null_seed,
    )
    study.save_experiment(spec)
    write_study_readme(root, spec)
    return spec


def ingest_data(root: Path, *, max_months: int | None = None) -> int:
    """Fetch/refresh domain data into study draws.jsonl. Returns draw count."""
    study = Study(root)
    if not study.exists():
        raise StudyNotFoundError(f"no study at {root}")
    spec = study.load_experiment()
    mod = get_domain(spec.domain)
    if not hasattr(mod, "prepare_data"):
        raise DataError(
            f"domain {spec.domain!r} has no network prepare_data()",
            hint="use demo649 for offline, or implement prepare_data on a domain pack",
        )
    n = mod.prepare_data(study.data_dir, max_months=max_months)
    from nullbench.core.workspace import write_study_readme

    write_study_readme(root, study.load_experiment())
    return int(n)


def add_strategy(
    root: Path,
    *,
    strategy_id: str,
    kind: str,
    tickets: int = 5,
    seed: int = 0,
    params: dict | None = None,
) -> ExperimentSpec:
    study = Study(root)
    if not study.exists():
        raise StudyNotFoundError(f"no study at {root}")
    spec = study.load_experiment()
    if strategy_id in spec.strategy_ids():
        raise StrategyError(
            f"strategy id already exists: {strategy_id}",
            hint="choose a different --id",
        )
    get_strategy(kind)
    ledger = study.ledger()
    if ledger.events_of("freeze"):
        raise StrategyError(
            "cannot add strategies after freezes exist",
            hint="start a new experiment_id / new study directory",
        )
    spec.strategies.append(
        StrategySpec(
            id=strategy_id,
            kind=kind,
            tickets_per_period=tickets,
            params=params or {},
            seed=seed,
        )
    )
    study.save_experiment(spec)
    from nullbench.core.workspace import write_study_readme

    write_study_readme(root, spec)
    return spec


def load_draws(path: Path) -> list[Draw]:
    rows: list[Draw] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(Draw.model_validate_json(line))
    return rows


def _history_before(draws: list[Draw], period: str) -> list[Draw]:
    out: list[Draw] = []
    for d in draws:
        if d.period == period:
            break
        out.append(d)
    return out


def _period_seed(period: str) -> int:
    # Stable across processes (Python's hash() is randomized per process).
    from nullbench.core.hashing import sha256_hex

    return int(sha256_hex(period)[:8], 16)


def freeze_period(root: Path, period: str) -> list[FreezeRecord]:
    study = Study(root)
    if not study.exists():
        raise StudyNotFoundError(f"no study at {root}")
    spec = study.load_experiment()
    if not spec.strategies:
        raise FreezeError(
            "add at least one strategy before freeze",
            hint=f"nullbench strategy add random --study {root} --tickets 5",
        )

    draws = load_draws(study.draws_path)
    periods = {d.period for d in draws}
    if period not in periods:
        sample = sorted(periods)[-3:] if periods else []
        raise DataError(
            f"period {period!r} not found in draws data",
            hint=f"run nullbench periods --study {root}"
            + (f"  (examples: {sample})" if sample else ""),
        )

    history = _history_before(draws, period)
    ledger = study.ledger()
    settled = {
        e["period"]
        for e in ledger.events_of("settle")
        if e.get("experiment_id") == spec.experiment_id
    }
    if period in settled:
        raise FreezeError(
            f"period {period} already settled — never backfill freezes",
            hint="choose a later unsettleable period or start a new experiment",
        )

    existing = {
        (e["strategy_id"], e["period"])
        for e in ledger.events_of("freeze")
        if e.get("experiment_id") == spec.experiment_id
    }

    records: list[FreezeRecord] = []
    fp = code_fingerprint()
    pseed = _period_seed(period)

    for s in spec.strategies:
        if (s.id, period) in existing:
            # idempotent: skip
            continue
        fn = get_strategy(s.kind)
        tickets = fn(spec.game, s, history, pseed)
        payload = {
            "experiment_id": spec.experiment_id,
            "period": period,
            "strategy_id": s.id,
            "tickets": [t.model_dump() for t in tickets],
        }
        rec = FreezeRecord(
            experiment_id=spec.experiment_id,
            period=period,
            strategy_id=s.id,
            tickets=tickets,
            content_hash=content_hash(payload),
            code_fingerprint=fp,
            late=False,
            meta={"history_draws_used": len(history), "strategy_kind": s.kind},
        )
        ledger.append(rec.model_dump(mode="json"))
        records.append(rec)
    return records


def freeze_latest(root: Path) -> list[FreezeRecord]:
    """Freeze the last draw period that is not yet settled."""
    study = Study(root)
    if not study.exists():
        raise StudyNotFoundError(f"no study at {root}")
    draws = load_draws(study.draws_path)
    if not draws:
        raise DataError("no draws", hint="ingest or use demo649")
    spec = study.load_experiment()
    settled = {
        e["period"]
        for e in study.ledger().events_of("settle")
        if e.get("experiment_id") == spec.experiment_id
    }
    for d in reversed(draws):
        if d.period not in settled:
            return freeze_period(root, d.period)
    raise FreezeError("all periods already settled", hint="ingest newer draws")


def freeze_last_n(root: Path, n: int) -> list[list[FreezeRecord]]:
    """Freeze the last n unsettled periods (oldest first among the window)."""
    if n < 1:
        raise FreezeError("n must be >= 1")
    study = Study(root)
    draws = load_draws(study.draws_path)
    if not draws:
        raise DataError("no draws")
    spec = study.load_experiment()
    settled = {
        e["period"]
        for e in study.ledger().events_of("settle")
        if e.get("experiment_id") == spec.experiment_id
    }
    candidates = [d.period for d in draws if d.period not in settled][-n:]
    if not candidates:
        raise FreezeError("no unsettled periods to freeze")
    return [freeze_period(root, p) for p in candidates]


def settle_period(root: Path, period: str | None = None) -> list[SettleRecord]:
    study = Study(root)
    if not study.exists():
        raise StudyNotFoundError(f"no study at {root}")
    spec = study.load_experiment()
    draws = {d.period: d for d in load_draws(study.draws_path)}
    ledger = study.ledger()

    freezes = [
        e
        for e in ledger.events_of("freeze")
        if e.get("experiment_id") == spec.experiment_id
    ]
    settled = {
        e["period"]
        for e in ledger.events_of("settle")
        if e.get("experiment_id") == spec.experiment_id
    }

    # Group freezes by period
    by_period: dict[str, list[dict]] = {}
    for f in freezes:
        by_period.setdefault(f["period"], []).append(f)

    targets = [period] if period else sorted(by_period.keys())
    out: list[SettleRecord] = []

    for p in targets:
        if p in settled:
            continue
        if p not in by_period:
            raise SettleError(
                f"no freezes for period {p}",
                hint=f"nullbench freeze {p} --study {root}",
            )
        if p not in draws:
            raise DataError(f"no draw for period {p}")
        draw = draws[p]
        strategy_results: list[PortfolioResult] = []
        n_tickets = 0
        for f in by_period[p]:
            tickets = [Ticket.model_validate(t) for t in f["tickets"]]
            n_tickets = max(n_tickets, len(tickets))
            payout, hits = portfolio_payout(spec.game, tickets, draw)
            cost = portfolio_cost(spec.game, len(tickets))
            strategy_results.append(
                PortfolioResult(
                    portfolio_id=f["strategy_id"],
                    kind="strategy",
                    cost=cost,
                    payout=payout,
                    hits=hits,
                )
            )
            # Attach diagnostic scores into hits meta via separate field later
            _ = period_score_summary(spec.game, tickets, draw)

        if n_tickets == 0:
            n_tickets = 5
        null_results = evaluate_null_bank(
            spec.game,
            draw,
            n_tickets=n_tickets,
            n_portfolios=spec.null_portfolios,
            base_seed=spec.null_seed,
        )
        payload = {
            "experiment_id": spec.experiment_id,
            "period": p,
            "draw": draw.model_dump(),
            "strategy_results": [r.model_dump() for r in strategy_results],
            "null_pnl": [r.pnl for r in null_results],
        }
        rec = SettleRecord(
            experiment_id=spec.experiment_id,
            period=p,
            draw=draw,
            strategy_results=strategy_results,
            null_results=null_results,
            content_hash=content_hash(payload),
        )
        # Store compact null summary in ledger to keep file smaller
        ledger_row = rec.model_dump(mode="json")
        ledger_row["null_results"] = [
            {"portfolio_id": r.portfolio_id, "kind": "null", "cost": r.cost, "payout": r.payout}
            for r in null_results
        ]
        ledger_row["scores"] = {
            f["strategy_id"]: period_score_summary(
                spec.game,
                [Ticket.model_validate(t) for t in f["tickets"]],
                draw,
            )
            for f in by_period[p]
        }
        ledger.append(ledger_row)
        out.append(rec)
    return out


def build_report(root: Path) -> ReportSummary:
    from nullbench.scoring.sequential import compare_strategy_to_null

    study = Study(root)
    spec = study.load_experiment()
    ledger = study.ledger()
    settles = [
        e
        for e in ledger.events_of("settle")
        if e.get("experiment_id") == spec.experiment_id
    ]
    if not settles:
        raise RuntimeError("no settlements yet — freeze and settle at least one period")

    # Sort by period for sequential evidence
    settles = sorted(settles, key=lambda e: (e.get("draw", {}).get("date") or "", e["period"]))

    cum: dict[str, float] = {}
    null_cum_by_idx: dict[str, float] = {}
    # per-strategy period pnl series
    period_pnl: dict[str, list[float]] = {}
    null_mean_series: list[float] = []

    for s in settles:
        null_pnls = [(r["payout"] - r["cost"]) for r in s.get("null_results", [])]
        null_m = sum(null_pnls) / len(null_pnls) if null_pnls else 0.0
        null_mean_series.append(null_m)
        for r in s["strategy_results"]:
            sid = r["portfolio_id"]
            pnl = r["payout"] - r["cost"]
            cum[sid] = cum.get(sid, 0.0) + pnl
            period_pnl.setdefault(sid, []).append(pnl)
        for r in s.get("null_results", []):
            pid = r["portfolio_id"]
            null_cum_by_idx[pid] = null_cum_by_idx.get(pid, 0.0) + (
                r["payout"] - r["cost"]
            )

    null_final = list(null_cum_by_idx.values())
    null_mean = sum(null_final) / len(null_final) if null_final else 0.0

    def percentile_of(value: float, cloud: list[float]) -> float:
        if not cloud:
            return 50.0
        below = sum(1 for x in cloud if x < value)
        equal = sum(1 for x in cloud if x == value)
        return 100.0 * (below + 0.5 * equal) / len(cloud)

    percentiles = {sid: percentile_of(v, null_final) for sid, v in cum.items()}

    sequential: dict[str, dict] = {}
    for sid, series in period_pnl.items():
        n = min(len(series), len(null_mean_series))
        ev = compare_strategy_to_null(series[:n], null_mean_series[:n])
        sequential[sid] = {
            "backend": ev.backend,
            "n": ev.n,
            "mean_delta": ev.mean_delta,
            "e_value": ev.e_value,
            "log_e": ev.log_e,
            "note": ev.note,
            "lcb": ev.lcb,
            "ucb": ev.ucb,
            "e_pq": ev.e_pq,
            "e_qp": ev.e_qp,
            "alpha": ev.alpha,
        }

    warnings = [
        "Descriptive statistics only — no formal alpha spend in v0.2.",
        "Equal-cost null portfolios share ticket count with the largest strategy arm.",
        "Sequential e-values are diagnostic; do not treat E>1 as a discovery claim.",
    ]
    if any(k in (spec.domain or "") for k in ("taiwan",)):
        warnings.append(
            "Taiwan floating jackpot tiers are valued at 0 (conservative fixed-only table)."
        )
    if len(settles) < 26:
        warnings.append(
            f"Only {len(settles)} settled period(s); treat percentiles as unstable."
        )

    summary = ReportSummary(
        experiment_id=spec.experiment_id,
        periods_settled=len(settles),
        claim_status=ClaimStatus.DESCRIPTIVE_ONLY,
        strategy_cum_pnl=cum,
        null_mean_cum_pnl=null_mean,
        strategy_percentiles=percentiles,
        sequential_evidence=sequential,
        warnings=warnings,
    )

    md = render_report_markdown(spec, summary, settles)
    out_path = study.reports_dir / "latest.md"
    out_path.write_text(md, encoding="utf-8")
    (study.reports_dir / "latest.json").write_text(
        summary.model_dump_json(indent=2),
        encoding="utf-8",
    )
    return summary


def render_report_markdown(
    spec: ExperimentSpec,
    summary: ReportSummary,
    settles: list[dict],
) -> str:
    lines = [
        f"# nullbench report — `{summary.experiment_id}`",
        "",
        f"**Claim status:** {summary.claim_status.value}",
        "",
        summary.disclaimer,
        "",
        f"- Domain: `{spec.domain}` ({spec.game.name})",
        f"- Periods settled: **{summary.periods_settled}**",
        f"- Null portfolios: **{spec.null_portfolios}** (seed={spec.null_seed})",
        "",
        "## Cumulative virtual P&L vs equal-cost chance",
        "",
        "| Strategy | Cum P&L | Empirical percentile vs null |",
        "|----------|--------:|-----------------------------:|",
    ]
    for sid, pnl in sorted(summary.strategy_cum_pnl.items()):
        pct = summary.strategy_percentiles.get(sid, float("nan"))
        lines.append(f"| `{sid}` | {pnl:.2f} | {pct:.1f} |")
    lines += [
        "",
        f"Null cloud mean cum P&L: **{summary.null_mean_cum_pnl:.2f}**",
        "",
        "## Sequential evidence (strategy − null mean, per period)",
        "",
        "| Strategy | n | mean Δ | CS LCB | CS UCB | e_pq | e_qp | backend |",
        "|----------|--:|-------:|-------:|-------:|-----:|-----:|---------|",
    ]
    for sid, ev in sorted(summary.sequential_evidence.items()):
        lcb = ev.get("lcb")
        ucb = ev.get("ucb")
        lcb_s = f"{lcb:.4f}" if isinstance(lcb, (int, float)) else "—"
        ucb_s = f"{ucb:.4f}" if isinstance(ucb, (int, float)) else "—"
        epq = ev.get("e_pq", ev.get("e_value", 1))
        eqp = ev.get("e_qp", float("nan"))
        eqp_s = f"{eqp:.4g}" if isinstance(eqp, (int, float)) else "—"
        lines.append(
            f"| `{sid}` | {ev.get('n', 0)} | {ev.get('mean_delta', 0):.4f} | "
            f"{lcb_s} | {ucb_s} | {epq:.4g} | {eqp_s} | {ev.get('backend', '?')} |"
        )
    lines += [
        "",
        "## Warnings",
        "",
    ]
    for w in summary.warnings:
        lines.append(f"- {w}")
    lines += [
        "",
        "## Recent periods",
        "",
    ]
    for s in settles[-5:]:
        lines.append(f"### {s['period']}")
        draw = s["draw"]
        lines.append(
            f"Draw: {draw.get('numbers')} "
            + (f" special={draw.get('special')}" if draw.get("special") is not None else "")
        )
        for r in s["strategy_results"]:
            lines.append(
                f"- `{r['portfolio_id']}`: cost={r['cost']:.0f} payout={r['payout']:.0f} "
                f"pnl={r['payout']-r['cost']:.0f}"
            )
        lines.append("")
    lines += [
        "---",
        "",
        "_Generated by nullbench. Pre-register before outcomes. Never backfill._",
        "",
    ]
    return "\n".join(lines)


def status(root: Path) -> dict:
    study = Study(root)
    if not study.exists():
        return {"ok": False, "error": "no study"}
    spec = study.load_experiment()
    ledger = study.ledger()
    ok, msg = ledger.verify_chain()
    freezes = ledger.events_of("freeze")
    settles = ledger.events_of("settle")
    draws = load_draws(study.draws_path)
    return {
        "ok": True,
        "root": str(study.root),
        "experiment_id": spec.experiment_id,
        "domain": spec.domain,
        "strategies": spec.strategy_ids(),
        "draws": len(draws),
        "freezes": len(freezes),
        "settles": len(settles),
        "ledger_ok": ok,
        "ledger_msg": msg,
    }
