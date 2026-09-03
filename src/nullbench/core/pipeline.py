"""Golden path: init → strategy → freeze → settle → report."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nullbench.core.hashing import content_hash
from nullbench.core.integrity import (
    assert_plugins_trusted,
    expected_settle_timing_proof,
    experiment_hash,
    freeze_content_hash,
    history_before,
    history_hash,
    order_draws,
    outcome_hash,
    require_freeze_seals,
    verify_freeze_row,
)
from nullbench.core.integrity import (
    code_fingerprint as seal_code_fingerprint,
)
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
from nullbench.core.vault import Vault
from nullbench.domains import game_for, get_domain
from nullbench.errors import (
    DataError,
    FreezeError,
    IntegrityError,
    NullbenchError,
    SettleError,
    StrategyError,
    StudyExistsError,
    StudyNotFoundError,
    VaultError,
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
    formal_enabled: bool = False,
    formal_primary: str | None = None,
) -> ExperimentSpec:
    from nullbench.core.models import FormalEndpointSpec
    from nullbench.core.workspace import write_study_readme

    study = Study(root)
    if study.exists():
        raise StudyExistsError(
            f"study already exists: {root}",
            hint="pick a new directory name, or continue with status/next",
        )
    study.ensure_layout()
    try:
        assert_plugins_trusted(domain, is_domain=True, study_root=root)
    except IntegrityError as e:
        raise DataError(e.message, hint=e.hint) from e
    game = game_for(domain)
    mod = get_domain(domain)
    if hasattr(mod, "write_demo_data") and not hasattr(mod, "prepare_data") or domain == "demo649":
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
        formal=FormalEndpointSpec(
            enabled=formal_enabled,
            primary_strategy_id=formal_primary,
        ),
    )
    study.save_experiment(spec)
    write_study_readme(root, spec)
    return spec


def enable_formal_endpoint(
    root: Path,
    *,
    primary_strategy_id: str | None = None,
    enabled: bool = True,
) -> ExperimentSpec:
    """Enable formal alpha-spending. Forbidden after first freeze."""
    study = Study(root)
    if not study.exists():
        raise StudyNotFoundError(f"no study at {root}")
    if study.ledger().events_of("freeze"):
        raise StrategyError(
            "cannot change formal endpoint after freezes exist",
            hint="start a new experiment_id",
        )
    spec = study.load_experiment()
    spec.formal.enabled = enabled
    if primary_strategy_id is not None:
        spec.formal.primary_strategy_id = primary_strategy_id
    study.save_experiment(spec)
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
    try:
        assert_plugins_trusted(kind, is_domain=False, study_root=root)
    except IntegrityError as e:
        raise StrategyError(e.message, hint=e.hint) from e
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
    # Always return stable causal order (IC-04)
    return order_draws(rows)


def _period_seed(period: str) -> int:
    from nullbench.core.hashing import sha256_hex

    return int(sha256_hex(period)[:8], 16)


def _assert_study_plugins_trusted(spec: ExperimentSpec, root: Path) -> None:
    """Trust gates for the domain and every strategy kind (IC-09)."""
    try:
        assert_plugins_trusted(spec.domain, is_domain=True, study_root=root)
    except IntegrityError as e:
        raise FreezeError(e.message, hint=e.hint) from e
    for s in spec.strategies:
        try:
            assert_plugins_trusted(s.kind, is_domain=False, study_root=root)
        except IntegrityError as e:
            raise FreezeError(e.message, hint=e.hint) from e


def _next_period_id(period: str) -> str | None:
    """Derive the following period id for sequential schemes.

    ``P0120`` → ``P0121``; ``114000041`` → ``114000042``. Returns None when the
    period id is not ``[prefix]digits`` — callers then need an explicit period.
    """
    import re

    m = re.fullmatch(r"([A-Za-z]*)([0-9]+)", period)
    if m is None:
        return None
    prefix, digits = m.group(1), m.group(2)
    return f"{prefix}{str(int(digits) + 1).zfill(len(digits))}"


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

    # Trust gate for domain plugins (IC-09)
    _assert_study_plugins_trusted(spec, root)

    draws = load_draws(study.draws_path)
    periods = {d.period for d in draws}
    if period not in periods:
        sample = sorted(periods)[-3:] if periods else []
        raise DataError(
            f"period {period!r} not found in draws data",
            hint=f"run nullbench periods --study {root}"
            + (f"  (examples: {sample})" if sample else ""),
        )

    history = history_before(draws, period)
    h_hash = history_hash(history)
    exp_h = experiment_hash(spec)
    by_period = {d.period: d for d in draws}
    # Seal outcome if already present (demo/backfill) — IC-03
    oh = outcome_hash(by_period[period]) if period in by_period else None

    ledger = study.ledger()
    settled = {
        e["period"]
        for e in ledger.events_of("settle")
        if e.get("experiment_id") == spec.experiment_id
    }
    if period in settled:
        raise FreezeError(
            f"period {period} already settled — never backfill freezes",
            hint="choose a later period or start a new experiment",
        )

    existing = {
        (e["strategy_id"], e["period"])
        for e in ledger.events_of("freeze")
        if e.get("experiment_id") == spec.experiment_id
    }

    kinds = [s.kind for s in spec.strategies]
    fp = seal_code_fingerprint(strategy_kinds=kinds, domain_id=spec.domain)
    pseed = _period_seed(period)
    records: list[FreezeRecord] = []

    for s in spec.strategies:
        if (s.id, period) in existing:
            continue
        fn = get_strategy(s.kind)
        tickets = fn(spec.game, s, history, pseed)
        ch = freeze_content_hash(
            experiment_id=spec.experiment_id,
            period=period,
            strategy_id=s.id,
            tickets=tickets,
            experiment_hash_=exp_h,
            history_hash_=h_hash,
            code_fingerprint_=fp,
            outcome_hash=oh,
        )
        rec = FreezeRecord(
            experiment_id=spec.experiment_id,
            period=period,
            strategy_id=s.id,
            tickets=tickets,
            content_hash=ch,
            code_fingerprint=fp,
            experiment_hash=exp_h,
            history_hash=h_hash,
            outcome_hash=oh,
            # Replay freeze: the outcome already existed when frozen (M5.0).
            # Prospective freezes (outcome not yet drawn) are the only honest
            # evidence for the north-star metric; they need M5.1.
            late=oh is not None,
            meta={
                "history_draws_used": len(history),
                "strategy_kind": s.kind,
                "null_seed": spec.null_seed,
                "null_portfolios": spec.null_portfolios,
            },
        )
        ledger.append(rec.model_dump(mode="json"))
        records.append(rec)
    return records


def freeze_prospective(root: Path, period: str | None = None) -> list[FreezeRecord]:
    """Freeze a period whose draw does not exist yet — north-star mode (M5.1).

    Hard contract, enforced later by the semantic audit: the period must be
    absent from ``draws.jsonl`` at freeze time, ``outcome_hash`` stays None,
    ``late`` stays False, and the history seal covers **every** draw known at
    freeze time (they are all strictly before a future period). Proves of
    "before the draw" beyond the study tree need the M4 vault: notarize each
    prospective freeze (see NORTH_STAR.md M5.4).
    """
    study = Study(root)
    if not study.exists():
        raise StudyNotFoundError(f"no study at {root}")
    spec = study.load_experiment()
    if not spec.strategies:
        raise FreezeError(
            "add at least one strategy before freeze",
            hint=f"nullbench strategy add random --study {root} --tickets 5",
        )
    _assert_study_plugins_trusted(spec, root)

    draws = load_draws(study.draws_path)
    if not draws:
        raise DataError(
            "no draws — cannot derive the next period",
            hint="ingest data first, or pass an explicit future --period",
        )
    if period is None:
        latest = draws[-1].period  # stable (date, period) order
        period = _next_period_id(latest)
        if period is None:
            raise DataError(
                f"cannot derive the period after {latest!r}",
                hint="pass the future period id explicitly",
            )
    if period in {d.period for d in draws}:
        raise FreezeError(
            f"period {period!r} already has a draw — that would be replay, not prospective",
            hint="freeze a period that has not been drawn yet (M5.1)",
        )

    history = order_draws(draws)  # everything known so far is strictly before a future period
    h_hash = history_hash(history)
    exp_h = experiment_hash(spec)

    ledger = study.ledger()
    settled = {
        e["period"]
        for e in ledger.events_of("settle")
        if e.get("experiment_id") == spec.experiment_id
    }
    if period in settled:
        raise FreezeError(
            f"period {period!r} already settled — never backfill freezes",
            hint="choose a later period or start a new experiment",
        )
    existing = {
        (e["strategy_id"], e["period"])
        for e in ledger.events_of("freeze")
        if e.get("experiment_id") == spec.experiment_id
    }

    kinds = [s.kind for s in spec.strategies]
    fp = seal_code_fingerprint(strategy_kinds=kinds, domain_id=spec.domain)
    pseed = _period_seed(period)
    records: list[FreezeRecord] = []

    for s in spec.strategies:
        if (s.id, period) in existing:
            continue
        fn = get_strategy(s.kind)
        tickets = fn(spec.game, s, history, pseed)
        ch = freeze_content_hash(
            experiment_id=spec.experiment_id,
            period=period,
            strategy_id=s.id,
            tickets=tickets,
            experiment_hash_=exp_h,
            history_hash_=h_hash,
            code_fingerprint_=fp,
            outcome_hash=None,
        )
        rec = FreezeRecord(
            experiment_id=spec.experiment_id,
            period=period,
            strategy_id=s.id,
            tickets=tickets,
            content_hash=ch,
            code_fingerprint=fp,
            experiment_hash=exp_h,
            history_hash=h_hash,
            outcome_hash=None,
            # Prospective freeze: the outcome does not exist yet (M5.1).
            late=False,
            meta={
                "history_draws_used": len(history),
                "strategy_kind": s.kind,
                "null_seed": spec.null_seed,
                "null_portfolios": spec.null_portfolios,
                "prospective": True,
                "known_draws_at_freeze": len(history),
            },
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
    exp_h = experiment_hash(spec)
    draws_list = load_draws(study.draws_path)
    draws = {d.period: d for d in draws_list}
    ledger = study.ledger()

    freezes = [
        e for e in ledger.events_of("freeze") if e.get("experiment_id") == spec.experiment_id
    ]
    settled = {
        e["period"]
        for e in ledger.events_of("settle")
        if e.get("experiment_id") == spec.experiment_id
    }

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

        # IC-02/03/05 + R-02: hard-require seals (empty hash must not skip checks)
        for f in by_period[p]:
            try:
                verify_freeze_row(f)
                eh, hh, _fp, oh = require_freeze_seals(f)
            except IntegrityError as e:
                raise SettleError(e.message, hint=e.hint) from e
            if eh != exp_h:
                raise SettleError(
                    f"experiment.json changed after freeze (period={p})",
                    hint="IC-05: restore experiment or start new experiment_id",
                )
            hist = history_before(draws_list, p)
            if hh != history_hash(hist):
                raise SettleError(
                    f"history/draws changed after freeze (period={p})",
                    hint="IC-03/04: restore draws.jsonl order and history",
                )
            if oh is not None and oh != outcome_hash(draw):
                raise SettleError(
                    f"draw outcome changed after freeze sealed it (period={p})",
                    hint="IC-03: restore the sealed draw",
                )

        try:
            proof = expected_settle_timing_proof(by_period[p], draws_list, p)
        except IntegrityError as e:
            raise SettleError(e.message, hint=e.hint) from e

        strategy_results: list[PortfolioResult] = []
        n_tickets = 0
        for f in by_period[p]:
            tickets = [Ticket.model_validate(t) for t in f["tickets"]]
            n_tickets = max(n_tickets, len(tickets))
            # Always recompute from tickets + draw (IC-01/02)
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
            _ = period_score_summary(spec.game, tickets, draw)

        if n_tickets == 0:
            n_tickets = 5
        # null_seed sealed in freeze meta — use experiment but verify match
        for f in by_period[p]:
            meta = f.get("meta") or {}
            if meta.get("null_seed") is not None and meta["null_seed"] != spec.null_seed:
                raise SettleError(
                    "null_seed changed after freeze",
                    hint="IC-05: restore experiment.null_seed",
                )
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
            "draw": draw.model_dump(mode="json"),
            "strategy_results": [r.model_dump(mode="json") for r in strategy_results],
            "null_pnl": [r.pnl for r in null_results],
            "experiment_hash": exp_h,
            "outcome_hash": outcome_hash(draw),
            "draw_entered_after_freeze": proof["draw_entered_after_freeze"],
            "freeze_line_hashes": proof["freeze_line_hashes"],
            "known_draws_at_freeze": proof["known_draws_at_freeze"],
            "known_draws_at_settle": proof["known_draws_at_settle"],
        }
        rec = SettleRecord(
            experiment_id=spec.experiment_id,
            period=p,
            draw=draw,
            strategy_results=strategy_results,
            null_results=null_results,
            content_hash=content_hash(payload),
            draw_entered_after_freeze=bool(proof["draw_entered_after_freeze"]),
            freeze_line_hashes=list(proof["freeze_line_hashes"]),
            known_draws_at_freeze=proof["known_draws_at_freeze"],
            known_draws_at_settle=proof["known_draws_at_settle"],
        )
        ledger_row = rec.model_dump(mode="json")
        ledger_row["null_results"] = [
            {
                "portfolio_id": r.portfolio_id,
                "kind": "null",
                "cost": r.cost,
                "payout": r.payout,
            }
            for r in null_results
        ]
        ledger_row["experiment_hash"] = exp_h
        ledger_row["outcome_hash"] = outcome_hash(draw)
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


def cycle_study(
    root: Path,
    *,
    allow_unnotarized: bool = False,
    max_months: int | None = None,
    vault: Vault | None = None,
) -> dict[str, Any]:
    """M5.3 north-star loop: ingest → settle pending → freeze next → notarize → report.

    Fail-closed. Ingest is skipped for offline domains (no ``prepare_data``).
    Frozen periods without a draw are skipped, not settled. Report is skipped
    until at least one settle exists. Notarize is required unless a vault is
    present or ``allow_unnotarized`` is set.
    """
    from nullbench.core.seal import notarize_study

    study = Study(root)
    if not study.exists():
        raise StudyNotFoundError(f"no study at {root}")
    spec = study.load_experiment()
    skipped: list[str] = []

    ingested: int | None = None
    mod = get_domain(spec.domain)
    if hasattr(mod, "prepare_data"):
        ingested = ingest_data(root, max_months=max_months)
    else:
        skipped.append(f"ingest: domain {spec.domain!r} has no prepare_data")

    draws = load_draws(study.draws_path)
    known = {d.period for d in draws}
    ledger = study.ledger()
    settled_ids = {
        e["period"]
        for e in ledger.events_of("settle")
        if e.get("experiment_id") == spec.experiment_id
    }
    pending = sorted(
        {
            e["period"]
            for e in ledger.events_of("freeze")
            if e.get("experiment_id") == spec.experiment_id and e["period"] not in settled_ids
        }
    )
    settled: list[SettleRecord] = []
    for p in pending:
        if p not in known:
            skipped.append(f"settle {p}: waiting for draw")
            continue
        settled.extend(settle_period(root, p))

    frozen = freeze_prospective(root)

    v = vault if vault is not None else Vault()
    receipt: dict | None = None
    if v.exists():
        receipt = notarize_study(root, vault=v)
    elif allow_unnotarized:
        skipped.append("notarize: no vault (--allow-unnotarized)")
    else:
        raise VaultError(
            f"no vault at {v.root}",
            hint="nullbench vault init   (or pass --allow-unnotarized for a local dry run)",
        )

    reported = False
    if study.ledger().events_of("settle"):
        build_report(root)
        reported = True
    else:
        skipped.append("report: no settlements yet")

    return {
        "ingested": ingested,
        "settled_periods": [r.period for r in settled],
        "frozen_period": frozen[0].period if frozen else None,
        "frozen_arms": len(frozen),
        "notarized": receipt is not None,
        "receipt_id": None if receipt is None else receipt.get("receipt_id"),
        "reported": reported,
        "skipped": skipped,
    }


def cycle_many(
    roots: list[Path],
    *,
    allow_unnotarized: bool = False,
    max_months: int | None = None,
    vault: Vault | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Cycle each study independently.

    One study failing does not skip the rest. ``errors`` is non-empty when
    any study raised; callers should treat that as a failed period loop.
    """
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    for root in roots:
        try:
            payload = cycle_study(
                root,
                allow_unnotarized=allow_unnotarized,
                max_months=max_months,
                vault=vault,
            )
            results.append({"root": str(Path(root).resolve()), "ok": True, **payload})
        except NullbenchError as e:
            loc = str(Path(root).resolve())
            errors.append(f"{loc}: {e.message}")
            results.append({"root": loc, "ok": False, "error": e.message})
    return results, errors


def build_report(root: Path) -> ReportSummary:
    from nullbench.formal.endpoints import FormalEndpointConfig, evaluate_formal_endpoint
    from nullbench.report.html import write_html_report
    from nullbench.scoring.sequential import compare_strategy_to_null

    study = Study(root)
    if not study.exists():
        raise StudyNotFoundError(f"no study at {root}")
    spec = study.load_experiment()
    ledger = study.ledger()
    settles = [
        e for e in ledger.events_of("settle") if e.get("experiment_id") == spec.experiment_id
    ]
    if not settles:
        raise SettleError(
            "no settlements yet",
            hint=f"nullbench freeze --study {root} --latest && nullbench settle --study {root}",
        )

    settles = sorted(settles, key=lambda e: (e.get("draw", {}).get("date") or "", e["period"]))

    cum: dict[str, float] = {}
    null_cum_by_idx: dict[str, float] = {}
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
            null_cum_by_idx[pid] = null_cum_by_idx.get(pid, 0.0) + (r["payout"] - r["cost"])

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

    # Formal endpoint
    formal_cfg = FormalEndpointConfig(
        enabled=spec.formal.enabled,
        primary_strategy_id=spec.formal.primary_strategy_id,
        checkpoints={int(k): float(v) for k, v in spec.formal.checkpoints.items()},
        primary_only_for_claim=spec.formal.primary_only_for_claim,
    )
    formal_ev = evaluate_formal_endpoint(
        config=formal_cfg,
        strategy_cum_pnl=cum,
        null_cum_pnl_cloud=null_final,
        n_settled=len(settles),
    )
    formal_dict = formal_ev.as_dict()

    claim = ClaimStatus.DESCRIPTIVE_ONLY
    if formal_ev.endpoint_open and formal_cfg.enabled:
        claim = ClaimStatus.FORMAL_ENDPOINT

    warnings = [
        "Equal-cost null portfolios share ticket count with the largest strategy arm.",
        "Sequential e-values are diagnostic; do not treat E>1 as a discovery claim.",
    ]
    if not formal_cfg.enabled:
        warnings.insert(
            0,
            "Formal endpoint disabled — descriptive only. "
            "Enable via experiment formal.enabled (checkpoints 26/52).",
        )
    elif not formal_ev.endpoint_open:
        warnings.insert(0, formal_ev.note)
    else:
        warnings.insert(
            0,
            f"Formal look open at n={formal_ev.n_settled} α={formal_ev.alpha_spent}. "
            f"Reject H0={formal_ev.reject_h0}.",
        )
    if any(k in (spec.domain or "") for k in ("taiwan",)):
        warnings.append(
            "Taiwan floating jackpot tiers are valued at 0 (conservative fixed-only table)."
        )
    # M5.0: say it when every freeze sealed an outcome that already existed.
    # Replay is legitimate for demos/replays, but it is not prospective
    # evidence — reports must not read as pre-registration (NORTH_STAR M5).
    all_freezes = [
        e for e in ledger.events_of("freeze") if e.get("experiment_id") == spec.experiment_id
    ]
    n_replay = sum(1 for f in all_freezes if f.get("outcome_hash") is not None or f.get("late"))
    if all_freezes and n_replay == len(all_freezes):
        warnings.insert(
            0,
            f"REPLAY: all {n_replay} freeze(s) sealed outcomes that already existed "
            "at freeze time — descriptive demonstration, not prospective "
            "pre-registration evidence (see NORTH_STAR.md M5).",
        )
    elif n_replay:
        warnings.append(
            f"{n_replay}/{len(all_freezes)} freeze(s) are replay (outcome known at freeze)."
        )
    n_prospective = len(all_freezes) - n_replay
    if n_prospective:
        warnings.insert(
            0,
            f"PROSPECTIVE: {n_prospective}/{len(all_freezes)} freeze(s) happened before "
            "their outcomes existed — this is north-star evidence (NORTH_STAR.md M5); "
            "notarize each freeze to make it verifiable beyond this machine.",
        )
    n_after = sum(1 for s in settles if s.get("draw_entered_after_freeze"))
    if n_after:
        warnings.append(
            f"PROSPECTIVE SETTLE: {n_after} period(s) record that the draw entered "
            "draws.jsonl after the freeze (NORTH_STAR.md M5.2)."
        )
    if len(settles) < 26:
        warnings.append(f"Only {len(settles)} settled period(s); treat percentiles as unstable.")

    summary = ReportSummary(
        experiment_id=spec.experiment_id,
        periods_settled=len(settles),
        claim_status=claim,
        strategy_cum_pnl=cum,
        null_mean_cum_pnl=null_mean,
        strategy_percentiles=percentiles,
        sequential_evidence=sequential,
        formal_endpoint=formal_dict,
        warnings=warnings,
    )

    # IC-06: claim language guard on generated surfaces
    from nullbench.core.claims import assert_clean, scan_forbidden
    from nullbench.core.integrity import verify_study_semantic

    sem_ok, sem_issues = verify_study_semantic(root)
    if not sem_ok:
        warnings.insert(0, f"SEMANTIC INTEGRITY FAILED: {sem_issues[:3]}")
        summary.warnings = warnings
        # Still refuse to publish a "clean" claim status if seals broken
        summary.claim_status = ClaimStatus.DESCRIPTIVE_ONLY
        summary.forbidden_hits = []
        # Do not write promotional language; hard-fail on integrity
        raise IntegrityError(
            "semantic integrity failed — refusing report",
            hint="; ".join(sem_issues[:5]),
        )

    md = render_report_markdown(spec, summary, settles)
    hits = scan_forbidden(md)
    if hits:
        raise IntegrityError(
            f"forbidden claim language in report: {hits}",
            hint="IC-06: remove promotional wording from generated text",
        )
    assert_clean(md)

    study.reports_dir.mkdir(parents=True, exist_ok=True)
    (study.reports_dir / "latest.md").write_text(md, encoding="utf-8")
    (study.reports_dir / "latest.json").write_text(
        summary.model_dump_json(indent=2),
        encoding="utf-8",
    )
    html_path = study.reports_dir / "latest.html"
    write_html_report(
        html_path,
        spec=spec,
        summary=summary,
        settles=settles,
        formal=formal_dict,
    )
    html_hits = scan_forbidden(html_path.read_text(encoding="utf-8"))
    # Allow words only inside our own disclaimer/forbidden scanner docs — scan user content
    # HTML includes fixed chrome; strip script and re-scan strategy labels already escaped
    if any(h in ("predict", "prediction", "winning numbers") for h in html_hits):
        # If injected via strategy id into template before escape — should be escaped
        # Re-check raw strategy ids
        for sid in summary.strategy_cum_pnl:
            if scan_forbidden(sid):
                raise IntegrityError(
                    f"forbidden claim language in strategy id: {sid}",
                    hint="IC-06/07: rename strategy",
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
        "## Formal endpoint",
        "",
    ]
    fe = summary.formal_endpoint or {}
    if fe:
        lines.append(
            f"- open={fe.get('endpoint_open')} n={fe.get('n_settled')} "
            f"α={fe.get('alpha_spent')} reject_H0={fe.get('reject_h0')}"
        )
        lines.append(f"- {fe.get('note', '')}")
    else:
        lines.append("- (none)")
    lines += [
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
                f"pnl={r['payout'] - r['cost']:.0f}"
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
