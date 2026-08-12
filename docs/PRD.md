# PRD — nullbench (DRAFT — M2 not frozen)

> Status: **draft**. M2 freezes this document. Until then, treat as intent only.

## Problem

People over-claim discrete decision strategies (lottery-like, portfolio picks, agent picks).
There is no small, installable lab that forces **pre-registration**, **equal-cost nulls**, and **detectable inconsistent edits**.

## Goals

1. Local-first study workspace: freeze → settle → report
2. Null-first comparison (equal cost chance portfolios)
3. Detect casual tampering (M1 seals); do not claim global notary without M4
4. Extensible domains/strategies with explicit trust gates

## Non-goals (M0–M2)

- Real-money betting integration
- Guaranteed prediction or “winning systems”
- Multi-tenant SaaS
- Unrestricted plugin execution by default

## Users

| Persona | Job |
|---------|-----|
| Skeptical engineer | Kill bad strategy narratives with evidence |
| Educator | Teach pre-registration / null models |
| Researcher | Domain packs + formal looks (26/52) |

## Core loop

```text
init → strategy add → freeze → settle → report → (repeat freeze)
```

Coach: `next`, health: `doctor`, gate: `maturity --check-m1`.

## Success metrics

| Metric | Target |
|--------|--------|
| Time to first report | < 5 min (`demo`) |
| M1 gate | `pytest -m m1` green on CI |
| Overclaim rate | Zero README lines promising absolute never-backfill before M1 badge |

## API surface (to freeze at M2)

Stable (intent):

- `init_study`, `add_strategy`, `freeze_period`, `settle_period`, `build_report`
- Models: `GameSpec`, `Ticket`, `Draw`, `ExperimentSpec`, `ReportSummary`
- Entry points: `nullbench.strategies`, `nullbench.domains` (trust-gated)

Unstable until M2: CLI flag names, HTML report layout, formal checkpoint constants.

## Release gate

- **M1** must pass before any marketing that says auditable / never-backfill **guarantee**
- **M2** freezes this PRD + threat model + claim policy + public API
