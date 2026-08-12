# Public API (frozen — M2)

**Status:** frozen as of nullbench **0.7.0** (2026-08-12).  
Breaking changes require a minor/major bump and CHANGELOG entry.

## Library (import from `nullbench`)

Stable:

| Symbol | Role |
|--------|------|
| `init_study` | Create study workspace |
| `add_strategy` | Register strategy before first freeze |
| `freeze_period` / `freeze_latest` | Pre-register tickets |
| `settle_period` | Score against draws + null bank |
| `build_report` | Write md/html/json reports + claim lint |
| `GameSpec`, `Ticket`, `Draw`, `ExperimentSpec`, `StrategySpec` | Contracts |
| `FreezeRecord`, `SettleRecord`, `ReportSummary` | Evidence / report models |
| `SpecialMode` | Game special-ball mode |
| `DomainInfo`, `StrategyFn` | Extension protocol types |
| `NullbenchError` (+ subclasses) | Typed errors |
| `__version__` | Package version |

Prefer:

```python
from nullbench import init_study, add_strategy, freeze_period, settle_period, build_report
```

## Entry points

| Group | Purpose | Trust |
|-------|---------|-------|
| `nullbench.strategies` | Strategy `propose` callables | Allowlist or `NULLBENCH_TRUST_PLUGINS=1` |
| `nullbench.domains` | Domain packs | Same |

## Explicitly unstable

- Private modules under `nullbench.core.*` except via public re-exports
- CLI flag names may gain aliases; behavior of the golden path is stable
- HTML report visual layout
- Formal α checkpoint constants (documented; changing them is an experiment-breaking change)

## CLI product surface (stable jobs)

`doctor`, `next`, `periods`, `demo`, `init`, `strategy`, `freeze`, `settle`, `report`, `maturity`, `ingest`, `formal`, `domains`, `strategies`

Exact option strings may evolve with deprecation notes in CHANGELOG.
