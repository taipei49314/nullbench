"""Typer CLI — the main user surface."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from nullbench import __version__
from nullbench.core import pipeline
from nullbench.core.study import Study

app = typer.Typer(
    name="nullbench",
    help="Pre-register decisions. Score them against chance. Never backfill.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


def _root(path: Optional[Path]) -> Path:
    return (path or Path.cwd()).resolve()


@app.callback()
def main() -> None:
    """nullbench CLI."""


@app.command()
def version() -> None:
    """Print version."""
    console.print(f"nullbench {__version__}")


@app.command("init")
def init_cmd(
    name: str = typer.Argument(..., help="Study directory name or path"),
    experiment_id: str = typer.Option("exp-v1", "--experiment-id", "-e"),
    domain: str = typer.Option("demo649", "--domain", "-d"),
    null_portfolios: int = typer.Option(200, "--nulls"),
    demo_draws: int = typer.Option(120, "--demo-draws"),
    path: Optional[Path] = typer.Option(None, "--path", help="Parent directory"),
) -> None:
    """Create a new study with offline demo data (demo649)."""
    parent = path or Path.cwd()
    root = (parent / name).resolve() if not Path(name).is_absolute() else Path(name)
    spec = pipeline.init_study(
        root,
        experiment_id=experiment_id,
        domain=domain,
        null_portfolios=null_portfolios,
        demo_draws=demo_draws,
    )
    console.print(f"[green]Initialized[/green] study at {root}")
    console.print(f"  experiment_id={spec.experiment_id} domain={spec.domain}")
    console.print(f"  draws → {Study(root).draws_path}")
    console.print("Next: nullbench strategy add random --study ...")


@app.command("strategy")
def strategy_cmd(
    action: str = typer.Argument(..., help="add"),
    kind: str = typer.Argument(..., help="random | frequency"),
    study: Path = typer.Option(..., "--study", "-s", help="Study directory"),
    strategy_id: Optional[str] = typer.Option(None, "--id"),
    tickets: int = typer.Option(5, "--tickets", "-n"),
    seed: int = typer.Option(0, "--seed"),
    window: int = typer.Option(50, "--window", help="frequency window"),
) -> None:
    """Manage strategies (currently: add)."""
    if action != "add":
        raise typer.BadParameter("only 'add' is supported in v0.1")
    sid = strategy_id or kind
    params = {"window": window} if kind == "frequency" else {}
    spec = pipeline.add_strategy(
        _root(study),
        strategy_id=sid,
        kind=kind,
        tickets=tickets,
        seed=seed,
        params=params,
    )
    console.print(f"[green]Added[/green] strategy `{sid}` ({kind}) tickets={tickets}")
    console.print(f"  strategies now: {spec.strategy_ids()}")


@app.command("freeze")
def freeze_cmd(
    period: str = typer.Argument(..., help="Period id, e.g. P0100"),
    study: Path = typer.Option(..., "--study", "-s"),
) -> None:
    """Freeze strategy tickets for a period (before using its outcome)."""
    records = pipeline.freeze_period(_root(study), period)
    if not records:
        console.print(f"[yellow]No new freezes[/yellow] (already frozen for {period})")
    else:
        console.print(f"[green]Froze[/green] {len(records)} strategy arm(s) for {period}")
        for r in records:
            console.print(f"  {r.strategy_id}: hash={r.content_hash[:12]}… n={len(r.tickets)}")


@app.command("settle")
def settle_cmd(
    study: Path = typer.Option(..., "--study", "-s"),
    period: Optional[str] = typer.Option(None, "--period", "-p"),
) -> None:
    """Settle frozen periods that have draws (never rewrites freezes)."""
    recs = pipeline.settle_period(_root(study), period)
    if not recs:
        console.print("[yellow]Nothing new to settle[/yellow]")
        return
    console.print(f"[green]Settled[/green] {len(recs)} period(s)")
    for r in recs:
        for s in r.strategy_results:
            console.print(
                f"  {r.period} `{s.portfolio_id}` pnl={s.pnl:.0f} "
                f"(payout={s.payout:.0f} cost={s.cost:.0f})"
            )


@app.command("report")
def report_cmd(
    study: Path = typer.Option(..., "--study", "-s"),
) -> None:
    """Build descriptive report vs null cloud."""
    summary = pipeline.build_report(_root(study))
    root = _root(study)
    path = Study(root).reports_dir / "latest.md"
    console.print(f"[green]Report[/green] → {path}")
    console.print(f"  periods={summary.periods_settled} claim={summary.claim_status.value}")
    table = Table(title="Strategy vs null (descriptive)")
    table.add_column("Strategy")
    table.add_column("Cum P&L", justify="right")
    table.add_column("Null percentile", justify="right")
    for sid, pnl in sorted(summary.strategy_cum_pnl.items()):
        table.add_row(sid, f"{pnl:.2f}", f"{summary.strategy_percentiles[sid]:.1f}")
    console.print(table)
    console.print(f"Null mean cum P&L: {summary.null_mean_cum_pnl:.2f}")
    for w in summary.warnings:
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
    flag = "ok" if info["ledger_ok"] else "BROKEN"
    console.print(f"ledger: {flag} ({info['ledger_msg']})")


@app.command("demo")
def demo_cmd(
    name: str = typer.Option("demo-study", "--name"),
    path: Optional[Path] = typer.Option(None, "--path"),
    settle_last: int = typer.Option(10, "--periods", help="How many tail periods to run"),
) -> None:
    """One-shot golden path: init + strategies + freeze/settle tail + report."""
    parent = path or Path.cwd()
    root = (parent / name).resolve()
    if root.exists() and (root / "experiment.json").exists():
        console.print(f"[yellow]Reusing[/yellow] existing study {root}")
    else:
        if root.exists():
            raise typer.BadParameter(f"{root} exists but is not a study")
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
        raise typer.Exit("not enough draws for demo")
    # Use late periods so frequency has history
    targets = [d.period for d in draws[-(settle_last):]]
    for p in targets:
        pipeline.freeze_period(root, p)
    pipeline.settle_period(root)
    summary = pipeline.build_report(root)
    console.print(f"[bold green]Demo complete[/bold green] → {root / 'reports' / 'latest.md'}")
    console.print(summary.model_dump())


if __name__ == "__main__":
    app()
