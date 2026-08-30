"""Golden path: init → strategy → freeze → settle → report."""

from __future__ import annotations

from pathlib import Path

from nullbench.core.integrity import (
    assert_plugins_trusted,
    experiment_hash,
    freeze_content_hash,
    history_before,
    history_hash_v3,
    make_history_anchor,
    order_draws,
    outcome_hash,
    registration_class_for_freeze,
    require_freeze_seals,
    settle_content_hash,
    verify_freeze_history,
    verify_freeze_row,
)
from nullbench.core.integrity import (
    code_fingerprint as seal_code_fingerprint,
)
from nullbench.core.locking import study_lock
from nullbench.core.models import (
    ClaimStatus,
    Draw,
    ExperimentSpec,
    FreezeRecord,
    PortfolioResult,
    RegistrationMode,
    ReportSummary,
    SettlementMode,
    SettleRecord,
    StrategySpec,
    Ticket,
    utc_now,
)
from nullbench.core.nullbank import evaluate_null_bank
from nullbench.core.settle_math import portfolio_cost, portfolio_payout
from nullbench.core.study import Study
from nullbench.domains import game_for, get_domain
from nullbench.errors import (
    DataError,
    FreezeError,
    IntegrityError,
    OutcomePendingError,
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
    formal_enabled: bool = False,
    formal_primary: str | None = None,
) -> ExperimentSpec:
    """Initialize one study atomically with respect to other normal writers."""
    from nullbench.core.models import FormalEndpointSpec

    if demo_draws < 1:
        raise DataError("demo_draws must be >= 1")
    if not experiment_id.strip():
        raise DataError("experiment_id cannot be empty")
    if formal_enabled and not (formal_primary or "").strip():
        raise DataError(
            "formal endpoint requires a primary strategy id",
            hint="set --formal-primary now; that strategy must exist before the first freeze",
        )
    if root.exists() and not root.is_dir():
        raise StudyExistsError(f"study target is not a directory: {root}")
    try:
        assert_plugins_trusted(domain, is_domain=True, study_root=root)
        ExperimentSpec(
            experiment_id=experiment_id,
            domain=domain,
            game=game_for(domain),
            strategies=[],
            null_portfolios=null_portfolios,
            null_seed=null_seed,
            formal=FormalEndpointSpec(
                enabled=formal_enabled,
                primary_strategy_id=formal_primary,
            ),
        )
    except IntegrityError as e:
        raise DataError(e.message, hint=e.hint) from e
    except (KeyError, ValueError) as e:
        raise DataError("invalid study configuration", hint=str(e)) from e
    with study_lock(root):
        return _init_study(
            root,
            experiment_id=experiment_id,
            domain=domain,
            null_portfolios=null_portfolios,
            null_seed=null_seed,
            demo_draws=demo_draws,
            fetch=fetch,
            max_months=max_months,
            formal_enabled=formal_enabled,
            formal_primary=formal_primary,
        )


def _init_study(
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
    existing = [path for path in root.iterdir() if path.name != ".nullbench.lock"]
    if existing:
        raise StudyExistsError(
            f"study target directory is not empty: {root}",
            hint="pick an empty directory; nullbench will not overwrite unrelated files",
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
    """Enable formal alpha-spending before freezes, under the study lock."""
    study = Study(root)
    if not study.exists():
        raise StudyNotFoundError(f"no study at {root}")
    with study_lock(root):
        return _enable_formal_endpoint(
            root,
            primary_strategy_id=primary_strategy_id,
            enabled=enabled,
        )


def _enable_formal_endpoint(
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
    effective_primary = (
        primary_strategy_id if primary_strategy_id is not None else spec.formal.primary_strategy_id
    )
    if enabled and not (effective_primary or "").strip():
        raise StrategyError(
            "formal endpoint requires a primary strategy id",
            hint="pass --primary with one pre-specified strategy id",
        )
    if (
        effective_primary is not None
        and spec.strategies
        and effective_primary not in spec.strategy_ids()
    ):
        raise StrategyError(
            f"formal primary strategy does not exist: {effective_primary}",
            hint=f"choose one of {spec.strategy_ids()}, or add the strategy before freezing",
        )
    spec.formal.enabled = enabled
    if primary_strategy_id is not None:
        spec.formal.primary_strategy_id = primary_strategy_id
    study.save_experiment(spec)
    return spec


def ingest_data(root: Path, *, max_months: int | None = None) -> int:
    """Fetch/refresh domain data while excluding freeze commits."""
    study = Study(root)
    if not study.exists():
        raise StudyNotFoundError(f"no study at {root}")
    with study_lock(root):
        return _ingest_data(root, max_months=max_months)


def _ingest_data(root: Path, *, max_months: int | None = None) -> int:
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
    """Add one immutable strategy before freezes, under the study lock."""
    study = Study(root)
    if not study.exists():
        raise StudyNotFoundError(f"no study at {root}")
    with study_lock(root):
        return _add_strategy(
            root,
            strategy_id=strategy_id,
            kind=kind,
            tickets=tickets,
            seed=seed,
            params=params,
        )


def _add_strategy(
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
        strategy = StrategySpec(
            id=strategy_id,
            kind=kind,
            tickets_per_period=tickets,
            params=params or {},
            seed=seed,
        )
    except ValueError as e:
        raise StrategyError("invalid strategy configuration", hint=str(e)) from e
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
    spec.strategies.append(strategy)
    study.save_experiment(spec)
    from nullbench.core.workspace import write_study_readme

    write_study_readme(root, spec)
    return spec


def load_draws(path: Path) -> list[Draw]:
    rows: list[Draw] = []
    if not path.exists():
        return rows
    seen: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if line:
            draw = Draw.model_validate_json(line)
            if draw.period in seen:
                raise DataError(
                    f"duplicate draw period {draw.period!r} at line {line_number}",
                    hint="each period must identify exactly one outcome",
                )
            seen.add(draw.period)
            rows.append(draw)
    # Always return stable causal order (IC-04)
    return order_draws(rows)


def _period_seed(period: str) -> int:
    from nullbench.core.hashing import sha256_hex

    return int(sha256_hex(period)[:8], 16)


def _freeze_commit_history(
    draws: list[Draw],
    *,
    period: str,
    backtest: bool,
    sealed_outcome_hash: str | None,
) -> list[Draw]:
    by_period = {d.period: d for d in draws}
    if backtest:
        if (
            period not in by_period
            or sealed_outcome_hash is None
            or outcome_hash(by_period[period]) != sealed_outcome_hash
        ):
            raise FreezeError(
                f"target outcome changed while freezing period {period}",
                hint="retry from a stable draws snapshot",
            )
        return history_before(draws, period)
    if period in by_period:
        raise FreezeError(
            f"outcome for period {period!r} appeared while freezing; refusing pre_outcome",
            hint=f"retry explicitly with --backtest in a separate experiment for {period}",
        )
    return draws


def freeze_period(
    root: Path,
    period: str,
    *,
    backtest: bool = False,
) -> list[FreezeRecord]:
    study = Study(root)
    if not study.exists():
        raise StudyNotFoundError(f"no study at {root}")
    spec = study.load_experiment()
    if not spec.strategies:
        raise FreezeError(
            "add at least one strategy before freeze",
            hint=f"nullbench strategy add random --study {root} --tickets 5",
        )
    if spec.formal.enabled and not spec.formal.primary_strategy_id:
        raise FreezeError(
            "formal endpoint has no pre-specified primary strategy",
            hint="set one before the first freeze, or disable the formal endpoint",
        )
    if spec.formal.enabled and spec.formal.primary_strategy_id not in spec.strategy_ids():
        raise FreezeError(
            f"formal primary strategy does not exist: {spec.formal.primary_strategy_id}",
            hint=f"choose one of {spec.strategy_ids()} before the first freeze",
        )
    ticket_counts = {strategy.tickets_per_period for strategy in spec.strategies}
    if len(ticket_counts) != 1:
        raise FreezeError(
            "strategy arms must use the same tickets_per_period",
            hint=(
                "equal ticket counts are required so every arm is compared with an "
                "equal-cost null bank; start a new study with matched arms"
            ),
        )

    # Trust gate for domain plugins (IC-09)
    try:
        assert_plugins_trusted(spec.domain, is_domain=True, study_root=root)
    except IntegrityError as e:
        raise FreezeError(e.message, hint=e.hint) from e
    for s in spec.strategies:
        try:
            assert_plugins_trusted(s.kind, is_domain=False, study_root=root)
        except IntegrityError as e:
            raise FreezeError(e.message, hint=e.hint) from e

    period = period.strip()
    if not period:
        raise FreezeError("period cannot be empty")

    draws = load_draws(study.draws_path)
    by_draw_period = {d.period: d for d in draws}
    requested_mode = RegistrationMode.BACKTEST if backtest else RegistrationMode.PRE_OUTCOME
    exp_h = experiment_hash(spec)

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

    experiment_freezes = [
        e for e in ledger.events_of("freeze") if e.get("experiment_id") == spec.experiment_id
    ]
    existing = {(e["strategy_id"], e["period"]) for e in experiment_freezes}
    existing_period = [e for e in experiment_freezes if e.get("period") == period]
    try:
        existing_classes = {registration_class_for_freeze(e) for e in experiment_freezes}
        for existing_freeze in experiment_freezes:
            verify_freeze_row(existing_freeze)
            verify_freeze_history(draws, existing_freeze)
            existing_exp_h, _hh, _fp, existing_outcome_h = require_freeze_seals(existing_freeze)
            if existing_exp_h != exp_h:
                raise IntegrityError("experiment.json changed after an existing freeze")
            existing_period_id = existing_freeze["period"]
            if (
                existing_outcome_h is not None
                and existing_period_id in by_draw_period
                and existing_outcome_h != outcome_hash(by_draw_period[existing_period_id])
            ):
                raise IntegrityError(
                    f"draw outcome changed after freeze period={existing_period_id}"
                )
    except IntegrityError as e:
        raise FreezeError(e.message, hint=e.hint) from e
    requested_class = SettlementMode(requested_mode.value)
    if existing_classes and existing_classes != {requested_class}:
        raise FreezeError(
            "cannot mix registration modes in one experiment",
            hint=(
                f"existing={sorted(m.value for m in existing_classes)} "
                f"requested={requested_mode.value}; start a new experiment_id"
            ),
        )
    if existing_period and all((s.id, period) in existing for s in spec.strategies):
        return []

    if backtest:
        if period not in by_draw_period:
            raise FreezeError(
                f"backtest outcome {period!r} is not present",
                hint="remove --backtest to pre-register an unrevealed period",
            )
        history = history_before(draws, period)
        oh = outcome_hash(by_draw_period[period])
    else:
        if period in by_draw_period:
            raise FreezeError(
                f"outcome for period {period!r} is already present; use explicit backtest mode",
                hint=f"use: nullbench freeze {period} --study {root} --backtest",
            )
        history = draws
        oh = None

    anchor = make_history_anchor(history)
    h_hash = history_hash_v3(history)

    kinds = [s.kind for s in spec.strategies]
    fp = seal_code_fingerprint(strategy_kinds=kinds, domain_id=spec.domain)
    pseed = _period_seed(period)
    ledger_snapshot = [event.get("line_hash") for event in ledger]
    planned: list[tuple[StrategySpec, list[Ticket]]] = []

    for s in spec.strategies:
        if (s.id, period) in existing:
            continue
        fn = get_strategy(s.kind)
        tickets = fn(spec.game, s, history, pseed)
        try:
            actual_tickets = len(tickets)
        except TypeError as exc:
            raise FreezeError(f"strategy {s.id!r} returned a non-sized ticket collection") from exc
        if actual_tickets != s.tickets_per_period:
            raise FreezeError(
                f"strategy {s.id!r} returned {actual_tickets} ticket(s), expected "
                f"{s.tickets_per_period}",
                hint="strategy output must preserve the pre-specified equal-cost arm size",
            )
        planned.append((s, tickets))

    # Normal writers share this lock. The second snapshot below also catches
    # in-process callbacks that mutate draws while timestamps/records are built.
    with study_lock(root):
        fresh_history = _freeze_commit_history(
            load_draws(study.draws_path),
            period=period,
            backtest=backtest,
            sealed_outcome_hash=oh,
        )
        if history_hash_v3(fresh_history) != h_hash or make_history_anchor(fresh_history) != anchor:
            raise FreezeError(
                "draw history changed while strategies were running",
                hint="retry freeze from the new stable history snapshot",
            )
        if experiment_hash(study.load_experiment()) != exp_h:
            raise FreezeError(
                "experiment.json changed while strategies were running",
                hint="restore the experiment or start a new experiment_id",
            )
        if seal_code_fingerprint(strategy_kinds=kinds, domain_id=spec.domain) != fp:
            raise FreezeError("strategy/domain code changed while freezing; retry")
        if [event.get("line_hash") for event in ledger] != ledger_snapshot:
            raise FreezeError(
                "ledger changed while strategies were running",
                hint="retry freeze after the other writer finishes",
            )

        frozen_at = utc_now()
        records: list[FreezeRecord] = []
        for s, tickets in planned:
            ch = freeze_content_hash(
                schema_version="3",
                experiment_id=spec.experiment_id,
                period=period,
                strategy_id=s.id,
                tickets=tickets,
                experiment_hash_=exp_h,
                history_hash_=h_hash,
                code_fingerprint_=fp,
                registration_mode=requested_mode,
                history_anchor=anchor,
                outcome_hash=oh,
                frozen_at=frozen_at,
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
                registration_mode=requested_mode,
                history_anchor=anchor,
                outcome_hash=oh,
                frozen_at=frozen_at,
                late=backtest,
                meta={
                    "history_draws_used": len(history),
                    "strategy_kind": s.kind,
                    "null_seed": spec.null_seed,
                    "null_portfolios": spec.null_portfolios,
                    "registration_semantics": ("target_absent" if not backtest else "historical"),
                },
            )
            records.append(rec)

        commit_history = _freeze_commit_history(
            load_draws(study.draws_path),
            period=period,
            backtest=backtest,
            sealed_outcome_hash=oh,
        )
        if (
            history_hash_v3(commit_history) != h_hash
            or make_history_anchor(commit_history) != anchor
        ):
            raise FreezeError("draw history changed before freeze commit; retry")
        if [event.get("line_hash") for event in ledger] != ledger_snapshot:
            raise FreezeError("ledger changed before freeze commit; retry")
        ledger.append_many([record.model_dump(mode="json") for record in records])
    return records


def freeze_latest(root: Path, *, backtest: bool = False) -> list[FreezeRecord]:
    """Backtest the last revealed period; explicit opt-in prevents silent retrospection."""
    if not backtest:
        raise FreezeError(
            "--latest is backtest-only",
            hint="pass backtest=True (CLI: --latest --backtest)",
        )
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
            return freeze_period(root, d.period, backtest=True)
    raise FreezeError("all periods already settled", hint="ingest newer draws")


def freeze_last_n(
    root: Path,
    n: int,
    *,
    backtest: bool = False,
) -> list[list[FreezeRecord]]:
    """Backtest the last n revealed periods (oldest first among the window)."""
    if not backtest:
        raise FreezeError(
            "--last is backtest-only",
            hint="pass backtest=True (CLI: --last N --backtest)",
        )
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
    return [freeze_period(root, p, backtest=True) for p in candidates]


def _period_registration_class(freezes: list[dict], period: str) -> SettlementMode:
    try:
        modes = {registration_class_for_freeze(f) for f in freezes}
    except IntegrityError as e:
        raise SettleError(e.message, hint=e.hint) from e
    if len(modes) != 1:
        raise SettleError(
            f"registration evidence differs across arms for period {period}",
            hint="IC-13: restore the original ledger; never mix or relabel freeze modes",
        )
    v3 = [f for f in freezes if str(f.get("schema_version", "")) == "3"]
    if len(v3) > 1:
        first = v3[0]
        evidence_fields = (
            "registration_mode",
            "history_anchor",
            "history_hash",
            "outcome_hash",
            "frozen_at",
        )
        if any(any(f.get(k) != first.get(k) for k in evidence_fields) for f in v3[1:]):
            raise SettleError(
                f"registration evidence differs across arms for period {period}",
                hint="IC-13: all arms in a freeze batch must share one causal boundary",
            )
    return next(iter(modes))


def settle_period(root: Path, period: str | None = None) -> list[SettleRecord]:
    """Settle one or all ready freezes under the shared study writer lock."""
    study = Study(root)
    if not study.exists():
        raise StudyNotFoundError(f"no study at {root}")
    with study_lock(root):
        return _settle_period(root, period)


def _settle_period(root: Path, period: str | None = None) -> list[SettleRecord]:
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
    settle_rows = [
        e for e in ledger.events_of("settle") if e.get("experiment_id") == spec.experiment_id
    ]
    settle_periods = [e["period"] for e in settle_rows]
    if len(settle_periods) != len(set(settle_periods)):
        raise SettleError(
            "duplicate settle periods in ledger",
            hint="IC-13: restore the original append-only ledger before settling",
        )
    freeze_keys = [(e.get("period"), e.get("strategy_id")) for e in freezes]
    if len(freeze_keys) != len(set(freeze_keys)):
        raise SettleError(
            "duplicate freeze arms in ledger",
            hint="IC-13: each period/strategy arm may be frozen exactly once",
        )
    settled = set(settle_periods)

    by_period: dict[str, list[dict]] = {}
    for f in freezes:
        by_period.setdefault(f["period"], []).append(f)

    try:
        experiment_modes = {registration_class_for_freeze(f) for f in freezes}
    except IntegrityError as e:
        raise SettleError(e.message, hint=e.hint) from e
    if len(experiment_modes) > 1:
        raise SettleError(
            "cannot settle an experiment with mixed registration modes",
            hint="start separate experiments for prospective and historical evaluation",
        )

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
        registration_class = _period_registration_class(by_period[p], p)
        if p not in draws:
            if registration_class == SettlementMode.PRE_OUTCOME:
                if period is None:
                    continue
                raise OutcomePendingError(
                    f"outcome pending for period {p}",
                    hint="ingest or append the revealed outcome, then settle again",
                )
            raise SettleError(
                f"sealed historical outcome missing for period {p}",
                hint="restore the draw committed by the backtest/legacy freeze",
            )
        draw = draws[p]
        frozen_strategy_ids = {str(f.get("strategy_id")) for f in by_period[p]}
        expected_strategy_ids = set(spec.strategy_ids())
        if frozen_strategy_ids != expected_strategy_ids:
            raise SettleError(
                f"freeze arms incomplete for period {p}",
                hint=(
                    f"expected={sorted(expected_strategy_ids)} got={sorted(frozen_strategy_ids)}; "
                    "complete the pre-outcome freeze or start a new experiment"
                ),
            )
        # IC-02/03/05 + R-02: hard-require seals (empty hash must not skip checks)
        for f in by_period[p]:
            try:
                verify_freeze_row(f)
                eh, _hh, _fp, oh = require_freeze_seals(f)
            except IntegrityError as e:
                raise SettleError(e.message, hint=e.hint) from e
            if eh != exp_h:
                raise SettleError(
                    f"experiment.json changed after freeze (period={p})",
                    hint="IC-05: restore experiment or start new experiment_id",
                )
            try:
                verify_freeze_history(draws_list, f)
            except IntegrityError as e:
                raise SettleError(e.message, hint=e.hint) from e
            if oh is not None and oh != outcome_hash(draw):
                raise SettleError(
                    f"draw outcome changed after freeze sealed it (period={p})",
                    hint="IC-03: restore the sealed draw",
                )

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
        freeze_hashes = sorted(str(f["content_hash"]) for f in by_period[p])
        strategy_rows = [r.model_dump(mode="json") for r in strategy_results]
        ch = settle_content_hash(
            schema_version="2",
            experiment_id=spec.experiment_id,
            period=p,
            draw=draw,
            strategy_results=strategy_rows,
            null_pnl=[r.pnl for r in null_results],
            experiment_hash_=exp_h,
            outcome_hash_=outcome_hash(draw),
            registration_mode=registration_class,
            freeze_content_hashes=freeze_hashes,
        )
        rec = SettleRecord(
            experiment_id=spec.experiment_id,
            period=p,
            draw=draw,
            strategy_results=strategy_results,
            null_results=null_results,
            registration_mode=registration_class,
            freeze_content_hashes=freeze_hashes,
            content_hash=ch,
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


def build_report(root: Path) -> ReportSummary:
    """Build reports from one stable study snapshot."""
    study = Study(root)
    if not study.exists():
        raise StudyNotFoundError(f"no study at {root}")
    with study_lock(root):
        return _build_report(root)


def _build_report(root: Path) -> ReportSummary:
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
            hint=(
                f"pre-register a future period, or run `nullbench freeze --study {root} "
                "--latest --backtest` for descriptive history"
            ),
        )

    settle_periods = [e["period"] for e in settles]
    if len(settle_periods) != len(set(settle_periods)):
        raise IntegrityError(
            "duplicate settle periods in ledger — refusing report",
            hint="IC-13: one outcome cannot advance a formal endpoint more than once",
        )

    settles = sorted(settles, key=lambda e: (e.get("draw", {}).get("date") or "", e["period"]))
    freezes = [
        e for e in ledger.events_of("freeze") if e.get("experiment_id") == spec.experiment_id
    ]
    freezes_by_period: dict[str, list[dict]] = {}
    for freeze in freezes:
        freezes_by_period.setdefault(freeze["period"], []).append(freeze)
    settle_modes: list[SettlementMode] = []
    for settle in settles:
        period_freezes = freezes_by_period.get(settle["period"], [])
        if not period_freezes:
            raise IntegrityError(f"settle has no corresponding freezes period={settle['period']}")
        settle_schema = str(settle.get("schema_version", ""))
        if settle_schema == "1" and any(
            str(freeze.get("schema_version", "")) == "3" for freeze in period_freezes
        ):
            raise IntegrityError(
                f"settle schema downgrade for period={settle['period']}",
                hint="freeze-v3 evidence requires settle-v2 mode/hash binding",
            )
        settle_modes.append(_period_registration_class(period_freezes, settle["period"]))
    registration_counts: dict[str, int] = {}
    for mode in settle_modes:
        registration_counts[mode.value] = registration_counts.get(mode.value, 0) + 1

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

    formal_cum: dict[str, float] = {}
    formal_null_by_idx: dict[str, float] = {}
    formal_eligible = 0
    for settle, mode in zip(settles, settle_modes, strict=True):
        if mode != SettlementMode.PRE_OUTCOME:
            continue
        formal_eligible += 1
        for result in settle["strategy_results"]:
            sid = result["portfolio_id"]
            formal_cum[sid] = formal_cum.get(sid, 0.0) + (result["payout"] - result["cost"])
        for result in settle.get("null_results", []):
            pid = result["portfolio_id"]
            formal_null_by_idx[pid] = formal_null_by_idx.get(pid, 0.0) + (
                result["payout"] - result["cost"]
            )
    formal_null_final = list(formal_null_by_idx.values())

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
    formal_eval_cfg = FormalEndpointConfig(
        enabled=formal_cfg.enabled and formal_eligible > 0,
        primary_strategy_id=formal_cfg.primary_strategy_id,
        checkpoints=formal_cfg.checkpoints,
        primary_only_for_claim=formal_cfg.primary_only_for_claim,
    )
    formal_ev = evaluate_formal_endpoint(
        config=formal_eval_cfg,
        strategy_cum_pnl=formal_cum,
        null_cum_pnl_cloud=formal_null_final,
        n_settled=formal_eligible,
    )
    formal_dict = formal_ev.as_dict()

    claim = ClaimStatus.DESCRIPTIVE_ONLY
    authorized_formal_result = (
        formal_cfg.primary_strategy_id is not None
        and formal_cfg.primary_strategy_id in formal_ev.strategies
    )
    if (
        formal_ev.endpoint_open
        and formal_cfg.enabled
        and formal_eligible > 0
        and authorized_formal_result
    ):
        claim = ClaimStatus.FORMAL_ENDPOINT

    warnings = [
        "Equal-cost null portfolios share ticket count with the largest strategy arm.",
        "Sequential e-values are diagnostic; do not treat E>1 as a discovery claim.",
    ]
    descriptive_count = len(settles) - formal_eligible
    if descriptive_count:
        warnings.insert(
            0,
            f"{descriptive_count} backtest/legacy settlement(s) are descriptive-only and "
            "do not advance formal checkpoints.",
        )
    if not formal_cfg.enabled:
        warnings.insert(
            0,
            "Formal endpoint disabled — descriptive only. "
            "Enable via experiment formal.enabled (checkpoints 26/52).",
        )
    elif formal_eligible == 0:
        warnings.insert(
            0,
            "Formal endpoint has 0 eligible periods: only freeze-v3 pre_outcome "
            "settlements can advance it.",
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
        registration_counts=registration_counts,
        formal_eligible_periods=formal_eligible,
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
        f"- Formal-eligible pre-outcome periods: **{summary.formal_eligible_periods}**",
        "- Registration classes: "
        + ", ".join(
            f"`{mode}`={count}" for mode, count in sorted(summary.registration_counts.items())
        ),
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
        "_Generated by nullbench. Pre-register before outcomes; label historical "
        "evaluations as backtests._",
        "",
    ]
    return "\n".join(lines)


def status(root: Path) -> dict:
    """Return one writer-consistent chain and semantic health snapshot."""
    study = Study(root)
    if not study.exists():
        return {"ok": False, "error": "no study"}
    with study_lock(root):
        return _status(root)


def _status(root: Path) -> dict:
    study = Study(root)
    spec = study.load_experiment()
    ledger = study.ledger()
    ok, msg = ledger.verify_chain()
    if not ok:
        return {
            "ok": False,
            "error": f"ledger integrity failed: {msg}",
            "root": str(study.root),
            "experiment_id": spec.experiment_id,
            "domain": spec.domain,
            "ledger_ok": False,
            "ledger_msg": msg,
        }
    from nullbench.core.integrity import verify_study_semantic

    semantic_ok, semantic_issues = verify_study_semantic(root)
    if not semantic_ok:
        return {
            "ok": False,
            "error": "semantic integrity failed: " + "; ".join(semantic_issues[:3]),
            "root": str(study.root),
            "experiment_id": spec.experiment_id,
            "domain": spec.domain,
            "ledger_ok": True,
            "ledger_msg": msg,
            "semantic_ok": False,
            "semantic_issues": semantic_issues,
        }
    freezes = [
        e for e in ledger.events_of("freeze") if e.get("experiment_id") == spec.experiment_id
    ]
    settles = [
        e for e in ledger.events_of("settle") if e.get("experiment_id") == spec.experiment_id
    ]
    draws = load_draws(study.draws_path)
    draw_periods = {d.period for d in draws}
    freeze_periods: dict[str, list[dict]] = {}
    for freeze in freezes:
        freeze_periods.setdefault(freeze["period"], []).append(freeze)
    mode_counts: dict[str, int] = {}
    pending = 0
    for period, rows in freeze_periods.items():
        try:
            mode = _period_registration_class(rows, period)
        except SettleError:
            mode = SettlementMode.LEGACY_UNKNOWN
        if period not in draw_periods and mode == SettlementMode.PRE_OUTCOME:
            pending += 1
    for settle in settles:
        rows = freeze_periods.get(settle["period"], [])
        try:
            mode = _period_registration_class(rows, settle["period"])
        except SettleError:
            mode = SettlementMode.LEGACY_UNKNOWN
        mode_counts[mode.value] = mode_counts.get(mode.value, 0) + 1
    return {
        "ok": ok,
        "root": str(study.root),
        "experiment_id": spec.experiment_id,
        "domain": spec.domain,
        "strategies": spec.strategy_ids(),
        "draws": len(draws),
        "freezes": len(freezes),
        "settles": len(settles),
        "pre_outcome_pending": pending,
        "pre_outcome_settled": mode_counts.get(SettlementMode.PRE_OUTCOME.value, 0),
        "backtest_settled": mode_counts.get(SettlementMode.BACKTEST.value, 0),
        "legacy_backtest": mode_counts.get(SettlementMode.LEGACY_BACKTEST.value, 0),
        "legacy_unknown": mode_counts.get(SettlementMode.LEGACY_UNKNOWN.value, 0),
        "formal_eligible_count": mode_counts.get(SettlementMode.PRE_OUTCOME.value, 0),
        "registration_counts": mode_counts,
        "ledger_ok": ok,
        "ledger_msg": msg,
        "semantic_ok": True,
        "semantic_issues": [],
    }
