"""Typer CLI — product surface for nullbench."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from nullbench import __version__
from nullbench.core import pipeline
from nullbench.core.study import Study
from nullbench.core.workspace import doctor as run_doctor
from nullbench.core.workspace import next_actions, period_index
from nullbench.domains import list_domain_infos, list_domains
from nullbench.errors import NullbenchError
from nullbench.strategies import list_strategies, list_strategy_infos

app = typer.Typer(
    name="nullbench",
    help=(
        "nullbench — pre-register decisions, score them against chance, never backfill.\n\n"
        "Quickstart:  nullbench demo --name try1\n"
        "Coach:       nullbench next --study try1\n"
        "Health:      nullbench doctor"
    ),
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode="rich",
)
console = Console()


def _root(path: Optional[Path]) -> Path:
    return (path or Path.cwd()).resolve()


def _fail(err: Exception) -> None:
    if isinstance(err, NullbenchError):
        console.print(f"[red]error:[/red] {err.format()}")
    else:
        console.print(f"[red]error:[/red] {err}")
    raise typer.Exit(1) from err


@app.callback()
def main() -> None:
    """nullbench CLI."""


@app.command()
def version() -> None:
    """Print version."""
    console.print(f"nullbench {__version__}")


@app.command()
def doctor(
    study: Optional[Path] = typer.Option(None, "--study", "-s"),
) -> None:
    """Check environment (and optional study) health."""
    info = run_doctor(_root(study) if study else None)
    table = Table(title="nullbench doctor")
    table.add_column("Check")
    table.add_column("OK")
    table.add_column("Detail")
    for c in info["checks"]:
        flag = "[green]yes[/green]" if c["ok"] else "[red]no[/red]"
        if c.get("optional") and not c["ok"]:
            flag = "[yellow]opt[/yellow]"
        table.add_row(c["name"], flag, str(c.get("detail", "")))
    console.print(table)
    if info.get("study"):
        console.print(info["study"])
    if not info["ok"]:
        raise typer.Exit(1)


@app.command("next")
def next_cmd(
    study: Path = typer.Option(..., "--study", "-s"),
) -> None:
    """Suggest the next product action for this study."""
    try:
        actions = next_actions(_root(study))
    except NullbenchError as e:
        _fail(e)
    console.print(Panel("\n".join(f"→ {a}" for a in actions), title="Next", border_style="cyan"))


@app.command("periods")
def periods_cmd(
    study: Path = typer.Option(..., "--study", "-s"),
    tail: int = typer.Option(15, "--tail", help="Show last N periods"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """List draw periods with freeze/settle status."""
    try:
        rows = period_index(_root(study))
    except NullbenchError as e:
        _fail(e)
    rows = rows[-tail:] if tail > 0 else rows
    if as_json:
        console.print_json(json.dumps(rows))
        return
    table = Table(title=f"Periods (last {len(rows)})")
    table.add_column("Period")
    table.add_column("Date")
    table.add_column("Frozen")
    table.add_column("Settled")
    for r in rows:
        fr = f"{r['frozen_arms']}/{r['strategies']}"
        if r["fully_frozen"]:
            fr = f"[green]{fr}[/green]"
        st = "[green]yes[/green]" if r["settled"] else "no"
        table.add_row(r["period"], r.get("date") or "—", fr, st)
    console.print(table)


@app.command("domains")
def domains_cmd(
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """List built-in domains."""
    if not verbose:
        for d in list_domains():
            console.print(f"  {d}")
        return
    table = Table(title="Domains")
    table.add_column("ID")
    table.add_column("Name")
    table.add_column("Network")
    table.add_column("Description")
    for info in list_domain_infos():
        table.add_row(
            info.id,
            info.name,
            "yes" if info.network else "no",
            (info.description or "")[:80],
        )
    console.print(table)


@app.command("strategies")
def strategies_cmd(
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """List built-in + plugin strategy kinds."""
    if not verbose:
        for s in list_strategies():
            console.print(f"  {s}")
        return
    table = Table(title="Strategies")
    table.add_column("ID")
    table.add_column("Source")
    table.add_column("Description")
    for row in list_strategy_infos():
        table.add_row(row["id"], row["source"], row["description"])
    console.print(table)


@app.command("init")
def init_cmd(
    name: str = typer.Argument(..., help="Study directory name or path"),
    experiment_id: str = typer.Option("exp-v1", "--experiment-id", "-e"),
    domain: str = typer.Option("demo649", "--domain", "-d"),
    null_portfolios: int = typer.Option(200, "--nulls"),
    demo_draws: int = typer.Option(120, "--demo-draws"),
    fetch: bool = typer.Option(False, "--fetch", help="Fetch network data (taiwan_*)"),
    max_months: Optional[int] = typer.Option(None, "--max-months"),
    path: Optional[Path] = typer.Option(None, "--path", help="Parent directory"),
) -> None:
    """Create a new study workspace (writes STUDY.md)."""
    parent = path or Path.cwd()
    root = (parent / name).resolve() if not Path(name).is_absolute() else Path(name)
    try:
        spec = pipeline.init_study(
            root,
            experiment_id=experiment_id,
            domain=domain,
            null_portfolios=null_portfolios,
            demo_draws=demo_draws,
            fetch=fetch,
            max_months=max_months,
        )
    except NullbenchError as e:
        _fail(e)
    draws = pipeline.load_draws(Study(root).draws_path)
    console.print(f"[green]Initialized[/green] {root}")
    console.print(f"  experiment={spec.experiment_id}  domain={spec.domain}  draws={len(draws)}")
    console.print(f"  guide → {root / 'STUDY.md'}")
    console.print(f"  next  → nullbench next --study {root}")


@app.command("ingest")
def ingest_cmd(
    study: Path = typer.Option(..., "--study", "-s"),
    max_months: Optional[int] = typer.Option(None, "--max-months"),
) -> None:
    """Fetch/refresh official data for network domains."""
    try:
        n = pipeline.ingest_data(_root(study), max_months=max_months)
    except NullbenchError as e:
        _fail(e)
    console.print(f"[green]Ingested[/green] {n} draws")


@app.command("strategy")
def strategy_cmd(
    action: str = typer.Argument(..., help="add"),
    kind: str = typer.Argument(..., help="random | frequency | plugin"),
    study: Path = typer.Option(..., "--study", "-s"),
    strategy_id: Optional[str] = typer.Option(None, "--id"),
    tickets: int = typer.Option(5, "--tickets", "-n"),
    seed: int = typer.Option(0, "--seed"),
    window: int = typer.Option(50, "--window"),
) -> None:
    """Manage strategies (add)."""
    if action != "add":
        raise typer.BadParameter("only 'add' is supported")
    sid = strategy_id or kind
    params = {"window": window} if kind == "frequency" else {}
    try:
        spec = pipeline.add_strategy(
            _root(study),
            strategy_id=sid,
            kind=kind,
            tickets=tickets,
            seed=seed,
            params=params,
        )
    except NullbenchError as e:
        _fail(e)
    console.print(f"[green]Added[/green] `{sid}` ({kind}) tickets={tickets}")
    console.print(f"  strategies: {spec.strategy_ids()}")
    console.print(f"  next → nullbench freeze --study {_root(study)} --latest")


@app.command("freeze")
def freeze_cmd(
    period: Optional[str] = typer.Argument(None, help="Period id (or use --latest)"),
    study: Path = typer.Option(..., "--study", "-s"),
    latest: bool = typer.Option(False, "--latest", help="Freeze newest unsettled period"),
    last: Optional[int] = typer.Option(None, "--last", help="Freeze last N unsettled periods"),
) -> None:
    """Freeze strategy tickets before using outcomes."""
    root = _root(study)
    try:
        if last is not None:
            batches = pipeline.freeze_last_n(root, last)
            total = sum(len(b) for b in batches)
            console.print(f"[green]Froze[/green] {total} arm-rows across {len(batches)} period(s)")
            console.print(f"  next → nullbench settle --study {root}")
            return
        if latest or period is None:
            records = pipeline.freeze_latest(root)
        else:
            records = pipeline.freeze_period(root, period)
    except NullbenchError as e:
        _fail(e)
    if not records:
        console.print("[yellow]No new freezes[/yellow] (already frozen)")
    else:
        console.print(f"[green]Froze[/green] {len(records)} arm(s) for {records[0].period}")
        for r in records:
            console.print(f"  {r.strategy_id}: {r.content_hash[:12]}…")
    console.print(f"  next → nullbench settle --study {root}")


@app.command("settle")
def settle_cmd(
    study: Path = typer.Option(..., "--study", "-s"),
    period: Optional[str] = typer.Option(None, "--period", "-p"),
) -> None:
    """Settle frozen periods (never rewrites freezes)."""
    try:
        recs = pipeline.settle_period(_root(study), period)
    except NullbenchError as e:
        _fail(e)
    if not recs:
        console.print("[yellow]Nothing new to settle[/yellow]")
        return
    console.print(f"[green]Settled[/green] {len(recs)} period(s)")
    for r in recs:
        for s in r.strategy_results:
            console.print(f"  {r.period} `{s.portfolio_id}` pnl={s.pnl:.0f}")
    console.print(f"  next → nullbench report --study {_root(study)}")


@app.command("report")
def report_cmd(
    study: Path = typer.Option(..., "--study", "-s"),
) -> None:
    """Build descriptive report vs null cloud + sequential evidence."""
    try:
        summary = pipeline.build_report(_root(study))
    except Exception as e:
        if isinstance(e, NullbenchError):
            _fail(e)
        _fail(NullbenchError(str(e)))
    path = Study(_root(study)).reports_dir / "latest.md"
    console.print(f"[green]Report[/green] → {path}")
    table = Table(title="Strategy vs null")
    table.add_column("Strategy")
    table.add_column("Cum P&L", justify="right")
    table.add_column("%ile", justify="right")
    table.add_column("e_pq", justify="right")
    table.add_column("CS LCB", justify="right")
    for sid, pnl in sorted(summary.strategy_cum_pnl.items()):
        ev = summary.sequential_evidence.get(sid, {})
        lcb = ev.get("lcb")
        table.add_row(
            sid,
            f"{pnl:.2f}",
            f"{summary.strategy_percentiles[sid]:.1f}",
            f"{ev.get('e_pq', ev.get('e_value', float('nan'))):.4g}",
            f"{lcb:.4f}" if isinstance(lcb, (int, float)) else "—",
        )
    console.print(table)
    for w in summary.warnings[:4]:
        console.print(f"[yellow]![/yellow] {w}")


@app.command("status")
def status_cmd(
    study: Path = typer.Option(..., "--study", "-s"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Show study status and ledger integrity."""
    info = pipeline.status(_root(study))
    if as_json:
        console.print_json(json.dumps(info))
        return
    if not info.get("ok"):
        console.print(f"[red]{info.get('error')}[/red]")
        raise typer.Exit(1)
    console.print(f"study: {info['root']}")
    console.print(f"experiment: {info['experiment_id']}  domain: {info['domain']}")
    console.print(f"strategies: {info['strategies']}")
    console.print(
        f"draws={info['draws']} freezes={info['freezes']} settles={info['settles']}"
    )
    flag = "[green]ok[/green]" if info["ledger_ok"] else "[red]BROKEN[/red]"
    console.print(f"ledger: {flag} ({info['ledger_msg']})")
    try:
        actions = next_actions(_root(study))
        console.print(f"next: {actions[0]}")
    except Exception:
        pass


@app.command("coverage")
def coverage_cmd(
    study: Path = typer.Option(..., "--study", "-s"),
    n_tickets: int = typer.Option(5, "--tickets", "-n"),
    top: int = typer.Option(30, "--top"),
    window: int = typer.Option(50, "--window"),
) -> None:
    """Max-disjoint multi-ticket coverage plan (OR-Tools if installed)."""
    from collections import Counter

    from nullbench.coverage import select_max_disjoint_coverage

    root = _root(study)
    study_obj = Study(root)
    if not study_obj.exists():
        _fail(NullbenchError(f"no study at {root}"))
    spec = study_obj.load_experiment()
    draws = pipeline.load_draws(study_obj.draws_path)
    use = draws[-window:] if window > 0 else draws
    counts: Counter = Counter()
    for d in use:
        counts.update(d.numbers)
    ranked = [n for n, _ in counts.most_common()]
    for n in range(1, spec.game.main_max + 1):
        if n not in counts:
            ranked.append(n)
    ranked = ranked[: max(top, n_tickets * spec.game.main_count)]
    plan = select_max_disjoint_coverage(spec.game, ranked, n_tickets=n_tickets)
    console.print(f"[green]Coverage[/green] backend={plan.backend} union={plan.union_size}")
    for t in plan.tickets:
        console.print(f"  {t.label}: {t.numbers}" + (f" +{t.special}" if t.special else ""))
    out = study_obj.reports_dir / "coverage_plan.json"
    study_obj.reports_dir.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "backend": plan.backend,
                "union_size": plan.union_size,
                "tickets": [t.model_dump() for t in plan.tickets],
                "note": plan.note,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    console.print(f"  wrote {out}")


@app.command("demo")
def demo_cmd(
    name: str = typer.Option("demo-study", "--name"),
    path: Optional[Path] = typer.Option(None, "--path"),
    settle_last: int = typer.Option(10, "--periods"),
) -> None:
    """One-shot golden path: init → strategies → freeze/settle → report."""
    parent = path or Path.cwd()
    root = (parent / name).resolve()
    try:
        if root.exists() and (root / "experiment.json").exists():
            console.print(f"[yellow]Reusing[/yellow] {root}")
        else:
            pipeline.init_study(root, experiment_id="demo-v1", domain="demo649")
            pipeline.add_strategy(root, strategy_id="random", kind="random", tickets=5, seed=1)
            pipeline.add_strategy(
                root,
                strategy_id="frequency",
                kind="frequency",
                tickets=5,
                seed=2,
                params={"window": 50},
            )
            console.print(f"[green]Created[/green] {root}")
        draws = pipeline.load_draws(Study(root).draws_path)
        if len(draws) < settle_last + 20:
            raise NullbenchError("not enough draws for demo")
        targets = [d.period for d in draws[-settle_last:]]
        for p in targets:
            pipeline.freeze_period(root, p)
        pipeline.settle_period(root)
        summary = pipeline.build_report(root)
    except NullbenchError as e:
        _fail(e)
    console.print(
        Panel(
            f"[bold green]Demo complete[/bold green]\n"
            f"report → {root / 'reports' / 'latest.md'}\n"
            f"guide  → {root / 'STUDY.md'}\n"
            f"coach  → nullbench next --study {root}",
            title="nullbench",
        )
    )
    console.print(
        {
            "periods": summary.periods_settled,
            "pnl": summary.strategy_cum_pnl,
            "backends": {
                k: v.get("backend") for k, v in summary.sequential_evidence.items()
            },
        }
    )


if __name__ == "__main__":
    app()
