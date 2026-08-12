# Product

## One-liner

**Pre-register decisions. Score them against chance. Never backfill.**

## Who it is for

| Persona | Job to be done |
|---------|----------------|
| Skeptical engineer | Prove a "system" is not better than chance |
| Educator / blogger | Reproducible demo of pre-registration |
| Researcher | Domain pack + sequential diagnostics without reinventing ledger |

## Who it is *not* for

- People seeking "winning numbers"
- Live betting automation
- Unregistered hyperparameter fishing

## Core loop (always the same)

```text
init → add strategies → freeze → settle → report → (repeat freeze)
         ↑ coach: `nullbench next`
```

## Product principles

1. **Golden path in 5 minutes** — `nullbench demo`
2. **Coach, don't abandon** — every command prints a next step; `next` command
3. **Honesty by default** — disclaimers, claim lint, conservative prizes
4. **Offline first** — demo649 needs no network
5. **Skeleton over features** — new science goes in extras/research, not default path

## Command map

| Job | Command |
|-----|---------|
| Try it | `demo` |
| Health | `doctor` |
| What now? | `next --study` |
| Navigate draws | `periods --study` |
| Work | `init` `strategy` `freeze` `settle` `report` |
| Taiwan data | `ingest` |
| Structure | `coverage` |
| Formal α | `formal --enable --primary …` (before freeze) |
| View | `report --open` → `reports/latest.html` |

## Success metrics (product)

- Stranger runs `pip install nullbench && nullbench demo` without reading source
- Second visit uses `next` instead of asking the author
- Domain/strategy plugins land without forking pipeline
