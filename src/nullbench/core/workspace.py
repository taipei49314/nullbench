"""Study workspace helpers — product surface over on-disk layout."""

from __future__ import annotations

from pathlib import Path

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
            f"- Try freeze last period: `nullbench freeze {draws[-1].period} "
            f"--study {root}`\n"
            f"- Or: `nullbench freeze --study {root} --latest`\n"
        )
    else:
        periods_hint = (
            f"- No draws yet. If this is a network domain: `nullbench ingest --study {root}`\n"
        )

    body = f"""# Study: {root.name}

**nullbench** workspace — pre-register decisions, score against chance, never backfill.

| Field | Value |
|-------|-------|
| experiment_id | `{spec.experiment_id}` |
| domain | `{spec.domain}` |
| game | {spec.game.name} |
| null portfolios | {spec.null_portfolios} |
| strategies | {", ".join(spec.strategy_ids()) or "(none yet)"} |

## Golden path

```bash
nullbench strategy add random --study {root} --tickets 5 --seed 1
nullbench strategy add frequency --study {root} --id frequency --tickets 5 --seed 2
nullbench freeze --study {root} --latest
nullbench settle --study {root}
nullbench report --study {root}
nullbench next --study {root}
```

## Data

- Draws: `data/draws.jsonl`
- Ledger: `ledger/events.jsonl` (append-only hash chain)
- Reports: `reports/latest.md`

{periods_hint}
## Rules

1. Freeze **before** using a period's outcome for decisions.
2. Never rewrite freezes after settle.
3. Change strategy params after freezes → new `experiment_id`.
4. Reports are **descriptive** unless you open a formal endpoint.

## Replay vs prospective

Freezing a period whose draw already exists in `data/draws.jsonl` is a
**replay** freeze (`late=true` in the ledger) — fine for demos and walkthroughs,
but it is not pre-registration evidence. Prospective freezing (freeze before
the draw exists) is the north-star mode; see [NORTH_STAR.md](../NORTH_STAR.md).

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
    rows = []
    for d in draws:
        n_frozen = sum(1 for s in strat_ids if (d.period, s) in frozen)
        rows.append(
            {
                "period": d.period,
                "date": d.date,
                "frozen_arms": n_frozen,
                "strategies": len(strat_ids),
                "fully_frozen": bool(strat_ids) and n_frozen == len(strat_ids),
                "settled": d.period in settled,
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
        known = {d.period for d in draws}
        undrawn = sorted(p for p in unsettled_frozen if p not in known)
        if undrawn:
            # Prospective freezes waiting on their draws (M5.1)
            if spec.domain.startswith("taiwan"):
                actions.append(
                    f"nullbench cycle --study {root}   # ingest → settle → freeze next → notarize"
                )
                actions.append(
                    f"nullbench ingest --study {root}   # waiting for draw(s): {undrawn[:5]}"
                )
            else:
                actions.append(
                    f"waiting for draw(s): {undrawn[:5]} — append them to data/draws.jsonl"
                )
                actions.append(f"nullbench cycle --study {root}   # after the draw exists")
            actions.append(f"nullbench settle --study {root}   # only after the draw exists")
            return actions
        actions.append(
            f"nullbench settle --study {root}   # pending: {sorted(unsettled_frozen)[:5]}"
        )
        return actions
    if not freezes:
        last = draws[-1].period
        actions.append(f"nullbench freeze --study {root} --latest   # e.g. {last}")
        actions.append(f"nullbench periods --study {root}")
        return actions
    if settles and not (study.reports_dir / "latest.md").exists():
        actions.append(f"nullbench report --study {root}")
        return actions
    if settles:
        actions.append(f"nullbench report --study {root}   # refresh report")
        actions.append(
            f"nullbench freeze --study {root} --latest   # add more periods before looking"
        )
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
            from nullbench.core.pipeline import trailing_prospective_streak

            exp_settles = [
                e
                for e in study.ledger().events_of("settle")
                if e.get("experiment_id") == spec.experiment_id
            ]
            exp_settles = sorted(
                exp_settles,
                key=lambda e: (e.get("draw", {}).get("date") or "", e.get("period") or ""),
            )
            streak = trailing_prospective_streak(exp_settles)
            study_info = {
                "root": str(study.root),
                "experiment_id": spec.experiment_id,
                "domain": spec.domain,
                "draws": len(draws),
                "strategies": spec.strategy_ids(),
                "ledger_ok": ok,
                "semantic_ok": sem_ok,
                "semantic_issues": sem_issues[:5],
                "prospective_streak": streak,
            }
            checks.append(
                {
                    "name": "prospective_streak",
                    "ok": True,
                    "detail": f"{streak} (target 26)",
                }
            )
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
            try:
                from nullbench.core.seal import verify_study_vault

                v_ok, v_issues, receipt = verify_study_vault(root)
                ever_notarized = receipt is not None or any(
                    "vault has" in i and "receipt" in i for i in v_issues
                )
                if ever_notarized:
                    checks.append(
                        {
                            "name": "vault_receipt",
                            "ok": v_ok,
                            "detail": "ok" if v_ok else "; ".join(v_issues[:2]),
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
                checks.append(
                    {
                        "name": "vault_receipt",
                        "ok": False,
                        "detail": str(e),
                        "optional": True,
                    }
                )
        except Exception as e:
            checks.append({"name": "study", "ok": False, "detail": str(e)})
    return {
        "ok": all(c["ok"] for c in checks if not c.get("optional")),
        "checks": checks,
        "study": study_info,
    }
