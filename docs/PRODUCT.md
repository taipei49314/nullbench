# Product

## One-liner

**Pre-register before outcomes. Label backtests honestly. Score decisions against chance.**

(M1 local seals detect inconsistent edits; never make an absolute never-backfill claim.)

In 0.9.0, “pre-register” means the target outcome is absent when `freeze PERIOD` runs. Known data is an explicit backtest and remains descriptive-only.

## Who it is for

| Persona | Job to be done |
|---------|----------------|
| Skeptical engineer | Test whether a "system" is distinguishable from chance |
| Educator / blogger | Teach the difference between pre-outcome registration and backtesting |
| Researcher | Domain pack + sequential diagnostics without reinventing ledger |

## Who it is *not* for

- People seeking "winning numbers"
- Live betting automation
- Unregistered hyperparameter fishing

## Prospective core loop

```text
init → add strategies → freeze future period → reveal outcome → settle → report
         ↑ coach: `nullbench next`
```

For historical data, use `freeze PERIOD --backtest`, `freeze --latest --backtest`, or `freeze --last N --backtest`. `demo` uses this retrospective path.

All arms must use the same declared and actual ticket count so the shared chance cloud is equal-cost. Formal mode is primary-only: choose the primary before the first freeze; nullbench closes the endpoint rather than spending one α budget across an unspecified strategy family.

## Product principles

1. **Product tour in 5 minutes** — `nullbench demo` (synthetic backtest)
2. **Coach, don't abandon** — every command prints a next step; `next` command
3. **Honesty by default** — disclaimers, claim lint, conservative prizes
4. **Offline first** — demo649 needs no network
5. **Skeleton over features** — new science goes in extras/research, not default path
6. **No silent retrospection** — a known outcome requires explicit backtest labeling

## Command map

| Job | Command |
|-----|---------|
| Try it | `demo` (descriptive-only backtest) |
| Health | `doctor` |
| What now? | `next --study` |
| Navigate draws | `periods --study` |
| Prospective work | `init` `strategy` `freeze PERIOD` `settle` `report` |
| Historical work | `freeze PERIOD --backtest` (`--latest/--last` also require it) |
| Taiwan data | `ingest` |
| Structure | `coverage` |
| Formal α | `formal --enable --primary …` (before freeze) |
| View | `report --open` → `reports/latest.html` |

## Success metrics (product)

- Stranger runs `pip install nullbench && nullbench demo` without reading source
- Second visit uses `next` instead of asking the author
- Domain/strategy plugins land without forking pipeline
