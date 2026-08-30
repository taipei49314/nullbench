"""Study workspace helpers — product surface over on-disk layout."""

from __future__ import annotations

from pathlib import Path

from nullbench.core.integrity import registration_class_for_freeze
from nullbench.core.models import ExperimentSpec
from nullbench.core.pipeline import load_draws
from nullbench.core.study import Study
from nullbench.errors import IntegrityError, StudyNotFoundError


def require_study(root: Path) -> Study:
    study = Study(root)
    if not study.exists():
        raise StudyNotFoundError(
            f"no study at {root}",
            hint=f"run: nullbench init {root.name}  (or pass --study correctly)",
        )
    return study


def write_study_readme(root: Path, spec: ExperimentSpec) -> Path:
    """Onboarding file inside every new study."""
    study = Study(root)
    draws = load_draws(study.draws_path)
    periods_hint = ""
    if draws:
        periods_hint = (
            f"- Sample periods: `{draws[0].period}` … `{draws[-1].period}` "
            f"({len(draws)} draws)\n"
            f"- Historical backtest: `nullbench freeze {draws[-1].period} "
            f"--study {root} --backtest`\n"
            f"- Or: `nullbench freeze --study {root} --latest --backtest`\n"
        )
    else:
        periods_hint = (
            f"- No draws yet. If this is a network domain: `nullbench ingest --study {root}`\n"
        )

    body = f"""# Study: {root.name}

**nullbench** workspace — pre-register before outcomes, label backtests, score against chance.

| Field | Value |
|-------|-------|
| experiment_id | `{spec.experiment_id}` |
| domain | `{spec.domain}` |
| game | {spec.game.name} |
| null portfolios | {spec.null_portfolios} |
| strategies | {", ".join(spec.strategy_ids()) or "(none yet)"} |

## Strategy setup (before either track)

Add strategies if they are not already present:

```bash
nullbench strategy add random --study {root} --tickets 5 --seed 1
nullbench strategy add frequency --study {root} --id frequency --tickets 5 --seed 2
```

## Choose exactly one registration track

### Track A — prospective

```bash
nullbench freeze FUTURE_PERIOD --study {root}
# after the outcome is appended/ingested:
nullbench settle --study {root}
nullbench report --study {root}
nullbench next --study {root}
```

### Track B — historical alternative

Use this instead of Track A in this experiment. Historical data must be labeled explicitly and never advances formal endpoints:

```bash
nullbench freeze --study {root} --latest --backtest
nullbench settle --study {root}
nullbench report --study {root}
```

## Data

- Draws: `data/draws.jsonl`
- Ledger: `ledger/events.jsonl` (append-only hash chain)
- Reports: `reports/latest.md`

{periods_hint}
## Rules

1. A pre-outcome target must be absent from `draws.jsonl` at freeze time.
2. Existing outcomes require explicit backtest mode and are descriptive-only.
3. Never rewrite or relabel an appended freeze.
4. Change strategy params after freezes → new `experiment_id`.
5. Reports are **descriptive** unless eligible pre-outcome data opens a formal endpoint.
6. One experiment cannot mix prospective, backtest, or legacy registration classes.

## Ethics

Pure simulation. No real-money wagering. Not a prediction product.
"""
    path = root / "STUDY.md"
    path.write_text(body, encoding="utf-8")
    return path


def period_index(root: Path) -> list[dict]:
    """List draws with freeze/settle status for product navigation."""
    study = require_study(root)
    spec = study.load_experiment()
    draws = load_draws(study.draws_path)
    ledger = study.ledger()
    frozen = {
        (e["period"], e["strategy_id"])
        for e in ledger.events_of("freeze")
        if e.get("experiment_id") == spec.experiment_id
    }
    settled = {
        e["period"]
        for e in ledger.events_of("settle")
        if e.get("experiment_id") == spec.experiment_id
    }
    strat_ids = spec.strategy_ids()
    draw_by_period = {d.period: d for d in draws}
    freeze_rows: dict[str, list[dict]] = {}
    for event in ledger.events_of("freeze"):
        if event.get("experiment_id") == spec.experiment_id:
            freeze_rows.setdefault(event["period"], []).append(event)
    rows = []
    ordered_periods = [d.period for d in draws]
    ordered_periods.extend(sorted(set(freeze_rows) - set(ordered_periods)))
    for period in ordered_periods:
        d = draw_by_period.get(period)
        n_frozen = sum(1 for s in strat_ids if (period, s) in frozen)
        modes = set()
        for event in freeze_rows.get(period, []):
            try:
                modes.add(registration_class_for_freeze(event).value)
            except IntegrityError:
                modes.add("invalid")
        registration = next(iter(modes)) if len(modes) == 1 else ("mixed" if modes else None)
        rows.append(
            {
                "period": period,
                "date": d.date if d else None,
                "frozen_arms": n_frozen,
                "strategies": len(strat_ids),
                "fully_frozen": bool(strat_ids) and n_frozen == len(strat_ids),
                "settled": period in settled,
                "outcome_available": d is not None,
                "registration_mode": registration,
                "pending": d is None and registration == "pre_outcome",
            }
        )
    return rows


def next_actions(root: Path) -> list[str]:
    """Product coach: ordered next steps."""
    study = require_study(root)
    spec = study.load_experiment()
    draws = load_draws(study.draws_path)
    ledger = study.ledger()
    freezes = [
        e for e in ledger.events_of("freeze") if e.get("experiment_id") == spec.experiment_id
    ]
    settles = [
        e for e in ledger.events_of("settle") if e.get("experiment_id") == spec.experiment_id
    ]
    ok, msg = ledger.verify_chain()
    actions: list[str] = []
    if not ok:
        actions.append(f"FIX ledger integrity: {msg}")
        return actions
    if not draws:
        if spec.domain.startswith("taiwan"):
            actions.append(f"nullbench ingest --study {root}")
        else:
            actions.append("No draws — re-init with demo649 or add data/draws.jsonl")
        return actions
    if not spec.strategies:
        actions.append(f"nullbench strategy add random --study {root} --tickets 5 --seed 1")
        actions.append(
            f"nullbench strategy add frequency --study {root} --id frequency --tickets 5"
        )
        return actions
    unsettled_frozen = set()
    settled_periods = {e["period"] for e in settles}
    for e in freezes:
        if e["period"] not in settled_periods:
            unsettled_frozen.add(e["period"])
    if unsettled_frozen:
        draw_periods = {d.period for d in draws}
        revealed = sorted(p for p in unsettled_frozen if p in draw_periods)
        pending: list[str] = []
        missing_historical: list[str] = []
        for period in sorted(set(unsettled_frozen) - set(revealed)):
            period_freezes = [e for e in freezes if e["period"] == period]
            try:
                modes = {registration_class_for_freeze(e).value for e in period_freezes}
            except IntegrityError:
                modes = {"invalid"}
            if modes == {"pre_outcome"}:
                pending.append(period)
            else:
                missing_historical.append(period)
        if missing_historical:
            actions.append(f"FIX missing sealed historical outcome(s): {missing_historical[:5]}")
        if revealed:
            actions.append(f"nullbench settle --study {root}   # ready: {revealed[:5]}")
        if pending:
            actions.append(f"Outcome pending for {pending[:5]} — ingest/append it, then settle")
        return actions
    if not freezes:
        last = draws[-1].period
        actions.append("Choose ONE track; do not run both in the same study:")
        actions.append(f"nullbench freeze FUTURE_PERIOD --study {root}   # prospective")
        actions.append(
            "Historical alternative: initialize a separate NEW_BACKTEST_STUDY, add its "
            "strategies, then run `nullbench freeze --study NEW_BACKTEST_STUDY "
            f"--latest --backtest` (for example {last})."
        )
        actions.append(f"nullbench periods --study {root}")
        return actions
    if settles and not (study.reports_dir / "latest.md").exists():
        actions.append(f"nullbench report --study {root}")
        return actions
    if settles:
        actions.append(f"nullbench report --study {root}   # refresh report")
        try:
            modes = {registration_class_for_freeze(e).value for e in freezes}
        except IntegrityError:
            modes = {"invalid"}
        if modes == {"pre_outcome"}:
            actions.append(
                f"nullbench freeze FUTURE_PERIOD --study {root}   # register before outcome"
            )
        elif modes == {"backtest"}:
            actions.append(f"nullbench freeze --study {root} --latest --backtest   # more history")
        else:
            actions.append("Start a new study for additional v3 registration evidence.")
        actions.append("Remember: descriptive only — e-values are diagnostics, not discoveries.")
        return actions
    actions.append(f"nullbench status --study {root}")
    return actions


def doctor(root: Path | None = None) -> dict:
    """Environment + optional study health check."""
    import importlib.util
    import sys

    from nullbench import __version__

    checks: list[dict] = []
    checks.append(
        {"name": "python", "ok": sys.version_info >= (3, 11), "detail": sys.version.split()[0]}
    )
    checks.append({"name": "nullbench", "ok": True, "detail": __version__})
    for mod, label in (
        ("numpy", "numpy"),
        ("scipy", "scipy"),
        ("pydantic", "pydantic"),
        ("typer", "typer"),
        ("ortools", "ortools (coverage extra)"),
        ("properscoring", "properscoring (stats extra)"),
    ):
        present = importlib.util.find_spec(mod) is not None
        checks.append(
            {
                "name": label,
                "ok": present if mod not in ("ortools", "properscoring") else True,
                "detail": "installed" if present else "optional — not installed",
                "optional": mod in ("ortools", "properscoring"),
            }
        )
    study_info = None
    if root is not None:
        try:
            study = require_study(root)
            spec = study.load_experiment()
            ok, msg = study.ledger().verify_chain()
            if not ok:
                raise IntegrityError(msg)
            from nullbench.core.integrity import verify_study_semantic

            sem_ok, sem_issues = verify_study_semantic(root)
            draws = load_draws(study.draws_path)
            study_info = {
                "root": str(study.root),
                "experiment_id": spec.experiment_id,
                "domain": spec.domain,
                "draws": len(draws),
                "strategies": spec.strategy_ids(),
                "ledger_ok": ok,
                "semantic_ok": sem_ok,
                "semantic_issues": sem_issues[:5],
            }
            checks.append({"name": "study", "ok": True, "detail": study.root.name})
            checks.append({"name": "ledger_chain", "ok": ok, "detail": msg})
            checks.append(
                {
                    "name": "ledger_semantic",
                    "ok": sem_ok,
                    "detail": "ok" if sem_ok else "; ".join(sem_issues[:2]),
                }
            )
            # M4: vault receipts are optional until the experiment was notarized
            local_receipt_present = (root / "vault" / "latest_receipt.json").is_file()
            vault_state_present = False
            try:
                from nullbench.core.seal import verify_study_vault
                from nullbench.core.vault import Vault

                active_vault = Vault()
                vault_state_present = any(
                    path.exists()
                    for path in (
                        active_vault.meta_path,
                        active_vault.key_path,
                        active_vault.receipts_path,
                    )
                )

                v_ok, v_issues, receipt = verify_study_vault(root)
                ever_notarized = (
                    local_receipt_present
                    or receipt is not None
                    or any("vault has" in i and "receipt" in i for i in v_issues)
                )
                if ever_notarized:
                    checks.append(
                        {
                            "name": "vault_receipt",
                            "ok": v_ok,
                            "detail": "; ".join(v_issues[:2]) if v_issues else "ok",
                        }
                    )
                    study_info["vault_ok"] = v_ok
                    if receipt is not None:
                        study_info["vault_receipt_id"] = receipt.get("receipt_id")
                else:
                    checks.append(
                        {
                            "name": "vault_receipt",
                            "ok": True,
                            "detail": "none (optional M4)",
                            "optional": True,
                        }
                    )
            except Exception as e:  # noqa: BLE001
                optional = not (local_receipt_present or vault_state_present)
                checks.append(
                    {
                        "name": "vault_receipt",
                        "ok": False,
                        "detail": str(e),
                        "optional": optional,
                    }
                )
        except Exception as e:
            checks.append({"name": "study", "ok": False, "detail": str(e)})
    return {
        "ok": all(c["ok"] for c in checks if not c.get("optional")),
        "checks": checks,
        "study": study_info,
    }
