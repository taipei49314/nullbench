"""Typer CLI — product surface for nullbench."""

from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path

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
from nullbench.errors import FreezeError, NullbenchError
from nullbench.strategies import list_strategies, list_strategy_infos


def _configure_output_streams() -> None:
    """Keep CLI output usable when the terminal cannot encode Unicode."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        encoding = getattr(stream, "encoding", None)
        if not encoding:
            continue
        try:
            "nullbench → 測試 🙂".encode(encoding)
        except (LookupError, UnicodeEncodeError):
            pass
        else:
            continue
        # Captured or embedded streams may reject reconfiguration.
        with contextlib.suppress(OSError, TypeError, ValueError):
            reconfigure(errors="backslashreplace")


_configure_output_streams()

app = typer.Typer(
    name="nullbench",
    help=(
        "nullbench — pre-register before outcomes; label backtests honestly.\n\n"
        "Quickstart:  nullbench demo --name try1\n"
        "Coach:       nullbench next --study try1\n"
        "Health:      nullbench doctor"
    ),
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode="rich",
)
console = Console()


def _root(path: Path | None) -> Path:
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
def maturity(
    check_m1: bool = typer.Option(
        False, "--check-m1", help="Run M1 adversarial gate (pytest -m m1)"
    ),
    check_m4: bool = typer.Option(False, "--check-m4", help="Run M4 vault gate (pytest -m m4)"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Show maturity ladder M0-M4; optionally run M1/M4 product gates."""
    from nullbench.maturity import PRODUCT_GATE, describe, run_m1_gate, run_m4_gate

    status = describe()
    table = Table(title="nullbench maturity")
    table.add_column("Level")
    table.add_column("Name")
    table.add_column("Role")
    for lv in status.levels:
        table.add_row(lv["id"], lv["name"], lv["note"])
    console.print(table)
    console.print(Panel(PRODUCT_GATE, title="Product gate", border_style="yellow"))
    console.print("[bold]M1 checklist[/bold]")
    for item in status.m1_checklist:
        console.print(f"  {item['id']}  {item['item']}")
    console.print("[bold]M4 checklist[/bold]")
    for item in status.m4_checklist:
        console.print(f"  {item['id']}  {item['item']}")
    if not check_m1 and not check_m4:
        console.print(
            "\nGates: [cyan]nullbench maturity --check-m1[/cyan] | [cyan]--check-m4[/cyan]"
        )
        return
    failed = False
    if check_m1:
        console.print("\n[bold]Running M1 gate...[/bold]")
        ok, log = run_m1_gate(verbose=verbose)
        console.print(log)
        if ok:
            console.print("[green]M1 GATE PASS[/green]")
        else:
            console.print("[red]M1 GATE FAIL[/red]")
            failed = True
    if check_m4:
        console.print("\n[bold]Running M4 gate...[/bold]")
        ok, log = run_m4_gate(verbose=verbose)
        console.print(log)
        if ok:
            console.print("[green]M4 GATE PASS[/green] — vault notary adversarial suite green")
        else:
            console.print("[red]M4 GATE FAIL[/red]")
            failed = True
    if failed:
        raise typer.Exit(1)


@app.command()
def doctor(
    study: Path | None = typer.Option(None, "--study", "-s"),
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
    table.add_column("Outcome")
    table.add_column("Registration")
    table.add_column("Settled")
    for r in rows:
        fr = f"{r['frozen_arms']}/{r['strategies']}"
        if r["fully_frozen"]:
            fr = f"[green]{fr}[/green]"
        st = "[green]yes[/green]" if r["settled"] else "no"
        if r.get("outcome_available"):
            outcome = "yes"
        elif r.get("pending"):
            outcome = "[yellow]pending[/yellow]"
        else:
            outcome = "[red]MISSING[/red]"
        table.add_row(
            r["period"],
            r.get("date") or "—",
            fr,
            outcome,
            r.get("registration_mode") or "—",
            st,
        )
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
    from nullbench.domains import _BUILTIN

    for info in list_domain_infos():
        src = "builtin" if info.id in _BUILTIN else "plugin"
        table.add_row(
            info.id,
            f"{info.name} [{src}]",
            "yes" if info.network else "no",
            (info.description or "")[:70],
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
    null_portfolios: int = typer.Option(200, "--nulls", min=1),
    demo_draws: int = typer.Option(120, "--demo-draws", min=1),
    fetch: bool = typer.Option(False, "--fetch", help="Fetch network data (taiwan_*)"),
    max_months: int | None = typer.Option(None, "--max-months", min=1),
    formal: bool = typer.Option(
        False, "--formal", help="Enable alpha-spending formal endpoint (26/52)"
    ),
    formal_primary: str | None = typer.Option(
        None, "--formal-primary", help="Primary strategy id for formal claim"
    ),
    path: Path | None = typer.Option(None, "--path", help="Parent directory"),
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
            formal_enabled=formal,
            formal_primary=formal_primary,
        )
    except NullbenchError as e:
        _fail(e)
    draws = pipeline.load_draws(Study(root).draws_path)
    console.print(f"[green]Initialized[/green] {root}")
    console.print(f"  experiment={spec.experiment_id}  domain={spec.domain}  draws={len(draws)}")
    console.print(f"  guide → {root / 'STUDY.md'}")
    console.print(f"  next  → nullbench next --study {root}")


@app.command("formal")
def formal_cmd(
    study: Path = typer.Option(..., "--study", "-s"),
    enable: bool = typer.Option(True, "--enable/--disable"),
    primary: str | None = typer.Option(None, "--primary", help="Primary strategy id"),
) -> None:
    """Enable/disable formal alpha-spending endpoint (before any freeze)."""
    try:
        spec = pipeline.enable_formal_endpoint(
            _root(study), primary_strategy_id=primary, enabled=enable
        )
    except NullbenchError as e:
        _fail(e)
    console.print(
        f"[green]Formal endpoint[/green] enabled={spec.formal.enabled} "
        f"primary={spec.formal.primary_strategy_id} "
        f"checkpoints={spec.formal.checkpoints}"
    )


@app.command("ingest")
def ingest_cmd(
    study: Path = typer.Option(..., "--study", "-s"),
    max_months: int | None = typer.Option(None, "--max-months"),
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
    strategy_id: str | None = typer.Option(None, "--id"),
    tickets: int = typer.Option(5, "--tickets", "-n", min=1),
    seed: int = typer.Option(0, "--seed"),
    window: int = typer.Option(50, "--window", min=1),
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
    console.print(f"  next → nullbench freeze FUTURE_PERIOD --study {_root(study)}")
    console.print(f"  history → nullbench freeze --study {_root(study)} --latest --backtest")


@app.command("freeze")
def freeze_cmd(
    period: str | None = typer.Argument(None, help="Future period id (or historical id)"),
    study: Path = typer.Option(..., "--study", "-s"),
    latest: bool = typer.Option(False, "--latest", help="Backtest newest unsettled period"),
    last: int | None = typer.Option(
        None, "--last", min=1, help="Backtest last N unsettled periods"
    ),
    backtest: bool = typer.Option(
        False,
        "--backtest",
        help="Explicitly label known-outcome evaluation as descriptive-only",
    ),
) -> None:
    """Pre-register an unrevealed period, or explicitly label a backtest."""
    root = _root(study)
    try:
        if last is not None and (latest or period is not None):
            raise FreezeError("choose exactly one of PERIOD, --latest, or --last")
        if latest and period is not None:
            raise FreezeError("choose either PERIOD or --latest, not both")
        if period is None and not latest and last is None:
            raise FreezeError(
                "future PERIOD is required for pre-outcome registration",
                hint="for history, use --latest --backtest or --last N --backtest",
            )
        if (latest or last is not None) and not backtest:
            raise FreezeError(
                "--latest and --last are backtest-only",
                hint="add --backtest to acknowledge descriptive historical evaluation",
            )
        if last is not None:
            batches = pipeline.freeze_last_n(root, last, backtest=True)
            total = sum(len(b) for b in batches)
            console.print(
                f"[yellow]BACKTEST[/yellow] {total} arm-rows across {len(batches)} period(s) "
                "— descriptive-only"
            )
            console.print(f"  next → nullbench settle --study {root}")
            return
        if latest:
            records = pipeline.freeze_latest(root, backtest=True)
        else:
            assert period is not None
            records = pipeline.freeze_period(root, period, backtest=backtest)
    except NullbenchError as e:
        _fail(e)
    if not records:
        console.print("[yellow]No new freezes[/yellow] (already frozen)")
    else:
        record_mode = records[0].registration_mode
        is_backtest = record_mode is not None and record_mode.value == "backtest"
        label = "[yellow]BACKTEST[/yellow]" if is_backtest else "[green]Pre-registered[/green]"
        suffix = " — descriptive-only" if is_backtest else " — outcome pending"
        console.print(f"{label} {len(records)} arm(s) for {records[0].period}{suffix}")
        for r in records:
            console.print(f"  {r.strategy_id}: {r.content_hash[:12]}…")
    if (
        records
        and records[0].registration_mode is not None
        and records[0].registration_mode.value == "pre_outcome"
    ):
        console.print("  next → ingest/append the outcome, then settle")
    else:
        console.print(f"  next → nullbench settle --study {root}")


@app.command("settle")
def settle_cmd(
    study: Path = typer.Option(..., "--study", "-s"),
    period: str | None = typer.Option(None, "--period", "-p"),
) -> None:
    """Settle frozen periods (never rewrites freezes)."""
    try:
        recs = pipeline.settle_period(_root(study), period)
    except NullbenchError as e:
        _fail(e)
    pending = pipeline.status(_root(study)).get("pre_outcome_pending", 0)
    if not recs:
        if pending:
            console.print(
                f"[yellow]Nothing ready to settle[/yellow] ({pending} pre-outcome period(s) pending)"
            )
        else:
            console.print("[yellow]Nothing new to settle[/yellow]")
        return
    console.print(f"[green]Settled[/green] {len(recs)} period(s)")
    for r in recs:
        for s in r.strategy_results:
            console.print(f"  {r.period} `{s.portfolio_id}` pnl={s.pnl:.0f}")
    if pending:
        console.print(f"  skipped {pending} pending pre-outcome period(s)")
    console.print(f"  next → nullbench report --study {_root(study)}")


@app.command("report")
def report_cmd(
    study: Path = typer.Option(..., "--study", "-s"),
    open_html: bool = typer.Option(False, "--open", help="Open latest.html in the default browser"),
) -> None:
    """Build descriptive report vs null cloud + sequential evidence."""
    try:
        summary = pipeline.build_report(_root(study))
    except Exception as e:
        if isinstance(e, NullbenchError):
            _fail(e)
        _fail(NullbenchError(str(e)))
    reports = Study(_root(study)).reports_dir
    html_path = reports / "latest.html"
    console.print(f"[green]Report[/green] → {reports / 'latest.md'}")
    console.print(f"  html  → {html_path}")
    console.print(f"  json  → {reports / 'latest.json'}")
    if summary.formal_endpoint:
        fe = summary.formal_endpoint
        console.print(
            f"  formal: open={fe.get('endpoint_open')} "
            f"n={fe.get('n_settled')} reject_H0={fe.get('reject_h0')}"
        )
    if open_html and html_path.exists():
        import webbrowser

        webbrowser.open(html_path.resolve().as_uri())
        console.print("  opened in browser")
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
    try:
        info = pipeline.status(_root(study))
    except NullbenchError as e:
        _fail(e)
    except Exception as e:
        _fail(NullbenchError(f"status failed: {e}"))
    if as_json:
        console.print_json(json.dumps(info))
        if not info.get("ok"):
            raise typer.Exit(1)
        return
    if not info.get("ok"):
        console.print(f"[red]{info.get('error')}[/red]")
        raise typer.Exit(1)
    console.print(f"study: {info['root']}")
    console.print(f"experiment: {info['experiment_id']}  domain: {info['domain']}")
    console.print(f"strategies: {info['strategies']}")
    console.print(f"draws={info['draws']} freezes={info['freezes']} settles={info['settles']}")
    console.print(
        "registration: "
        f"pending={info['pre_outcome_pending']} "
        f"pre_outcome_settled={info['pre_outcome_settled']} "
        f"backtest_settled={info['backtest_settled']} "
        f"legacy_backtest={info['legacy_backtest']} "
        f"legacy_unknown={info['legacy_unknown']} "
        f"formal_eligible={info['formal_eligible_count']}"
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
    path: Path | None = typer.Option(None, "--path"),
    settle_last: int = typer.Option(10, "--periods", min=1, max=100),
) -> None:
    """One-shot historical BACKTEST tutorial; never formal-eligible."""
    parent = path or Path.cwd()
    root = (parent / name).resolve()
    try:
        if settle_last < 1:
            raise NullbenchError("demo --periods must be at least 1")
        console.print(
            "[yellow]BACKTEST TUTORIAL[/yellow] — historical outcomes; "
            "not pre-registered or formal-eligible"
        )
        if root.exists() and (root / "experiment.json").exists():
            spec = Study(root).load_experiment()
            actual_strategies = [
                (s.id, s.kind, s.tickets_per_period, s.seed, s.params) for s in spec.strategies
            ]
            expected_strategies = [
                ("random", "random", 5, 1, {}),
                ("frequency", "frequency", 5, 2, {"window": 50}),
            ]
            demo_contract_matches = (
                spec.experiment_id == "demo-v1"
                and spec.domain == "demo649"
                and spec.null_portfolios == 200
                and spec.null_seed == 42
                and not spec.formal.enabled
                and actual_strategies == expected_strategies
            )
            if not demo_contract_matches:
                raise NullbenchError(
                    f"refusing to reuse non-demo study: {root}",
                    hint="choose a new --name so demo cannot modify an existing study",
                )
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
        demo_study = Study(root)
        experiment_id = demo_study.load_experiment().experiment_id
        settled_periods = {
            event["period"]
            for event in demo_study.ledger().events_of("settle")
            if event.get("experiment_id") == experiment_id
        }
        for p in targets:
            if p not in settled_periods:
                pipeline.freeze_period(root, p, backtest=True)
        pipeline.settle_period(root)
        summary = pipeline.build_report(root)
    except NullbenchError as e:
        _fail(e)
    console.print(
        Panel(
            f"[bold yellow]BACKTEST tutorial complete[/bold yellow]\n"
            "descriptive-only; not pre-registered or formal-eligible\n"
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
            "backends": {k: v.get("backend") for k, v in summary.sequential_evidence.items()},
        }
    )


# --- M4: sealed export / vault notary -----------------------------------------

seal_app = typer.Typer(help="M4 sealed bundle export / notarize / verify", no_args_is_help=True)
vault_app = typer.Typer(help="M4 external vault (outside study tree)", no_args_is_help=True)
app.add_typer(seal_app, name="seal")
app.add_typer(vault_app, name="vault")


@vault_app.command("init")
def vault_init(
    path: Path | None = typer.Option(None, "--path", help="Vault directory"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Initialize a vault outside the study (HMAC key + receipts log)."""
    from nullbench.core.vault import Vault

    try:
        v = Vault(path)
        meta = v.init(force=force)
    except NullbenchError as e:
        _fail(e)
    console.print(f"[green]Vault ready[/green] {v.root}")
    console.print(meta)


@vault_app.command("list")
def vault_list(
    path: Path | None = typer.Option(None, "--path"),
    tail: int = typer.Option(10, "--tail"),
) -> None:
    """List recent vault receipts."""
    from nullbench.core.vault import Vault

    try:
        v = Vault(path)
        if not v.exists():
            raise NullbenchError(f"no vault at {v.root}", hint="nullbench vault init")
        rows = v.iter_receipts()[-tail:]
    except NullbenchError as e:
        _fail(e)
    table = Table(title=f"Vault receipts ({v.root})")
    table.add_column("When")
    table.add_column("Experiment")
    table.add_column("Tip")
    table.add_column("Receipt")
    for r in rows:
        table.add_row(
            str(r.get("notarized_at", ""))[:19],
            str(r.get("experiment_id", "")),
            str(r.get("tip_line_hash", ""))[:12] + "…",
            str(r.get("receipt_id", ""))[:8],
        )
    console.print(table)


@vault_app.command("serve")
def vault_serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8765, "--port"),
    path: Path | None = typer.Option(None, "--path"),
) -> None:
    """Run a local HTTP notary bound to this vault (Bearer token required)."""
    from nullbench.core.notary_http import TOKEN_ENV, serve_notary
    from nullbench.core.vault import Vault

    try:
        v = Vault(path)
        if not v.exists():
            v.init()
        server, token = serve_notary(host, port, vault=v)
    except NullbenchError as e:
        _fail(e)
    console.print(
        f"[green]Notary listening[/green] http://{host}:{port}/v1/notarize (vault={v.root})"
    )
    console.print(f"Set NULLBENCH_NOTARY_URL=http://{host}:{port} on clients.")
    console.print(f"Set {TOKEN_ENV}={token} on clients (Authorization: Bearer).")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        console.print("stopped")


@seal_app.command("export")
def seal_export(
    study: Path = typer.Option(..., "--study", "-s"),
    out: Path = typer.Option(..., "--out", "-o", help="Output bundle directory"),
) -> None:
    """Export a sealed study bundle (manifest + tip-bound files)."""
    from nullbench.core.seal import export_bundle

    try:
        manifest = export_bundle(_root(study), out)
    except NullbenchError as e:
        _fail(e)
    console.print(f"[green]Exported[/green] {out}")
    console.print({"bundle_id": manifest["bundle_id"], "tip": manifest["tip_line_hash"]})


@seal_app.command("notarize")
def seal_notarize(
    study: Path = typer.Option(..., "--study", "-s"),
    vault_path: Path | None = typer.Option(None, "--vault"),
    remote: bool = typer.Option(
        False,
        "--remote",
        help="Also POST to the required NULLBENCH_NOTARY_URL",
    ),
) -> None:
    """Notarize study tip into the external vault (A5 control)."""
    from nullbench.core.locking import study_lock
    from nullbench.core.seal import _write_receipt_copy, notarize_study
    from nullbench.core.vault import Vault

    remote_receipt_path: Path | None = None
    study_root = _root(study)
    try:
        v = Vault(vault_path)
        remote_url: str | None = None
        if remote:
            from nullbench.core import notary_http

            remote_url = notary_http.notary_url()
            if remote_url is None:
                raise NullbenchError(
                    "--remote requires NULLBENCH_NOTARY_URL",
                    hint="set the remote notary URL, or omit --remote for local vault only",
                )
        receipt = notarize_study(study_root, vault=v, reuse_existing=True)
        if remote and remote_url is not None:
            payload_fields = (
                "bundle_id",
                "experiment_id",
                "experiment_hash",
                "domain",
                "tip_line_hash",
                "tip_n_lines",
                "file_hashes",
                "nullbench_version",
            )
            try:
                remote_receipt = notary_http.post_receipt(
                    {key: receipt[key] for key in payload_fields},
                    url=remote_url,
                )
                remote_receipt_path = study_root / "vault" / "latest_remote_receipt.json"
                with study_lock(study_root):
                    _write_receipt_copy(remote_receipt_path, remote_receipt)
            except NullbenchError as exc:
                raise NullbenchError(
                    f"local vault receipt {receipt.get('receipt_id')} was committed, but "
                    f"remote notarization failed: {exc.message}",
                    hint="fix the remote endpoint and retry --remote; the local retry is safe",
                ) from exc
            console.print(
                {
                    "remote_receipt_id": remote_receipt.get("receipt_id"),
                    "remote_receipt": str(remote_receipt_path),
                }
            )
    except NullbenchError as e:
        _fail(e)
    console.print("[green]Local vault notarized[/green]")
    console.print(
        {
            "receipt_id": receipt["receipt_id"],
            "bundle_id": receipt["bundle_id"],
            "tip": receipt["tip_line_hash"],
            "vault": str(v.root),
        }
    )
    if remote_receipt_path is not None:
        console.print(
            "[yellow]Remote receipt saved separately; standard seal verify uses the local "
            "vault key. Remote authority must verify its own signed receipt.[/yellow]"
        )


@seal_app.command("verify")
def seal_verify(
    study: Path = typer.Option(..., "--study", "-s"),
    receipt: Path | None = typer.Option(None, "--receipt", "-r"),
    vault_path: Path | None = typer.Option(None, "--vault"),
) -> None:
    """Verify an exact bundle or a bounded archived ancestor against a vault receipt."""
    from nullbench.core.seal import verify_study_vault
    from nullbench.core.vault import Vault

    try:
        ok, issues, rec = verify_study_vault(
            _root(study), receipt_path=receipt, vault=Vault(vault_path)
        )
    except NullbenchError as e:
        _fail(e)
    if ok:
        ancestor_verified = any(issue.startswith("ANCESTOR VERIFIED:") for issue in issues)
        if ancestor_verified:
            console.print(
                "[green]ANCESTOR VERIFIED[/green] / [yellow]CURRENT BUNDLE NOT NOTARIZED[/yellow]"
            )
        else:
            console.print("[green]VAULT VERIFY PASS[/green]")
        if rec:
            console.print({"receipt_id": rec.get("receipt_id"), "bundle_id": rec.get("bundle_id")})
        for issue in issues:
            console.print(f"[yellow]{issue}[/yellow]")
    else:
        console.print("[red]VAULT VERIFY FAIL[/red]")
        for i in issues:
            console.print(f"  - {i}")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
