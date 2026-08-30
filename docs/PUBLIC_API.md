# Public API (frozen — M2)

**Status:** frozen as of nullbench **0.7.0** (2026-08-12).  
Breaking changes require a minor/major bump and CHANGELOG entry.

**0.9.0 behavior amendment:** existing symbol names remain, but registration mode is now explicit so historical data cannot be mistaken for pre-outcome evidence.

## Library (import from `nullbench`)

Stable:

| Symbol | Role |
|--------|------|
| `init_study` | Create study workspace |
| `add_strategy` | Register strategy before first freeze |
| `freeze_period` | Freeze a future period by default; pass `backtest=True` for a known outcome |
| `freeze_latest` | Historical selector; requires `backtest=True` |
| `freeze_last_n` | Historical window selector; requires `backtest=True` |
| `settle_period` | Score against draws + null bank |
| `build_report` | Write md/html/json reports + claim lint |
| `GameSpec`, `Ticket`, `Draw`, `ExperimentSpec`, `StrategySpec` | Contracts |
| `RegistrationMode`, `SettlementMode`, `HistoryAnchor`, `HistoryBoundary` | Registration evidence contracts |
| `FreezeRecord`, `SettleRecord`, `ReportSummary` | Evidence / report models |
| `SpecialMode` | Game special-ball mode |
| `DomainInfo`, `StrategyFn` | Extension protocol types |
| `NullbenchError`, `OutcomePendingError` (+ subclasses) | Typed errors |
| `__version__` | Package version |

Prefer:

```python
from nullbench import init_study, add_strategy, freeze_period, settle_period, build_report

freeze_period(prospective_root, "P0121")                 # result absent
freeze_period(backtest_root, "P0120", backtest=True)     # separate experiment
```

## Registration semantics (0.9.0)

- `freeze_period(root, period, *, backtest=False)` is pre-outcome by default and refuses a target already present in draw data.
- `freeze_latest(root, *, backtest=False)` rejects its default mode because “latest” selects a known result; call it with `backtest=True`. The CLI similarly requires `--backtest` with `--latest` or `--last`.
- Settling one explicit pending period raises `OutcomePendingError`; batch settlement skips pending periods and continues with revealed outcomes.
- Backtest and legacy settlements are formal-ineligible and remain descriptive-only.
- A single experiment cannot mix registration classes; use a separate experiment id for prospective and historical evaluation.
- Every strategy must declare and return the same ticket count before a freeze commits; this is the stable equal-cost null invariant.
- Enabling a primary-only formal endpoint requires a non-empty primary id, and that strategy must exist before the first freeze.

New FreezeRecord rows use schema v3. Their hash binds `registration_mode`, `frozen_at`, and an `ordered_prefix_v1` `history_anchor` (`count` plus the final date/period boundary). A pre-outcome row has a null outcome hash; a backtest row seals the known outcome and is marked late.

SettleRecord schema v2 binds the evidence-derived registration class and sorted contributing freeze hashes. ReportSummary keeps total settled periods separately from `registration_counts` and `formal_eligible_periods`; only settled v3 `pre_outcome` periods advance formal checkpoints.

Schema-v2 rows retain exact legacy hash verification and are never rewritten. A v2 row with an outcome hash is classified `legacy_backtest`; one without it is `legacy_unknown`. Both are descriptive-only because their historical timing cannot be upgraded into v3 evidence.

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

`doctor`, `next`, `periods`, `demo`, `init`, `strategy`, `freeze`, `settle`, `report`, `maturity`, `ingest`, `formal`, `domains`, `strategies`, `seal`, `vault`

### M4 (0.8+)

| Command | Role |
|---------|------|
| `vault init` / `vault list` / `vault serve` | External vault lifecycle |
| `seal export` / `seal notarize` / `seal verify` | Bundle + notary |

`seal verify` distinguishes an exact receipt match from a receipt-v2 archived ancestor. Ancestor success means the notarized snapshot is an unchanged strict ledger prefix and its pre-outcome targets were absent then; it explicitly does not notarize the current tail. Receipt-v1 remains exact-content compatibility only.

Exact option strings may evolve with deprecation notes in CHANGELOG. Registration meaning does not silently degrade: known outcomes require `--backtest`, `--latest` and `--last` are backtest-only, and `demo` is always a descriptive backtest tutorial.
