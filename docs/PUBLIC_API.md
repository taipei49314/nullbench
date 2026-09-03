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

### M5 additions (0.9.0)

| Symbol | Role |
|--------|------|
| `freeze_prospective` | Freeze a period whose draw does not exist yet (north-star mode); `outcome_hash=None`, `late=False`, history seal covers all known draws |

### M5.3 additions (unreleased, additive)

| Symbol | Role |
|--------|------|
| `cycle_study` | One fail-closed loop: ingest → settle pending → freeze next → notarize → report |

CLI: `nullbench cycle --study …` (`--allow-unnotarized` skips notarize when no vault).

### M5.2 additions (unreleased, additive)

`SettleRecord` schema v2 fields (new rows; not a breaking change):

| Field | Role |
|-------|------|
| `draw_entered_after_freeze` | `True` iff this settle proved the period entered `draws.jsonl` after freeze |
| `freeze_line_hashes` | Freeze row `line_hash`es bound to this settle |
| `known_draws_at_freeze` | Draw count sealed on the prospective freeze (`None` for replay) |
| `known_draws_at_settle` | Draw count at settle time |

## CLI product surface (stable jobs)

`doctor`, `next`, `periods`, `demo`, `init`, `strategy`, `freeze`, `settle`, `cycle`, `report`, `maturity`, `ingest`, `formal`, `domains`, `strategies`, `seal`, `vault`

### M4 (0.8+)

| Command | Role |
|---------|------|
| `vault init` / `vault list` / `vault serve` | External vault lifecycle |
| `seal export` / `seal notarize` / `seal verify` | Bundle + notary |

Exact option strings may evolve with deprecation notes in CHANGELOG.
