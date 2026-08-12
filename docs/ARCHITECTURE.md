# Architecture

nullbench is a thin **honesty layer** over domain games and scoring giants.

```text
┌─────────────────────────────────────────────────────────────┐
│  CLI (product)          doctor · next · periods · demo      │
├─────────────────────────────────────────────────────────────┤
│  Pipeline               init → strategy → freeze → settle   │
│                         → report                            │
├───────────────┬─────────────────────┬───────────────────────┤
│  Study /      │  Strategies         │  Domains              │
│  Ledger       │  Protocol + plugins │  DomainInfo registry  │
│  hash chain   │  entry_points       │  offline / network    │
├───────────────┴─────────────────────┴───────────────────────┤
│  Scoring        comparecast port · brier · null bank        │
│  Coverage       OR-Tools (optional extra)                   │
└─────────────────────────────────────────────────────────────┘
```

## Layers

| Layer | Package path | Responsibility |
|-------|--------------|----------------|
| Product | `cli.py`, `core/workspace.py` | UX, coach (`next`), doctor, STUDY.md |
| Pipeline | `core/pipeline.py` | Golden path orchestration |
| Contracts | `protocols.py`, `core/models.py`, `errors.py` | Stable types & errors |
| Integrity | `core/ledger.py`, `core/hashing.py` | Append-only evidence |
| Domain | `domains/*` | Game rules + data bootstrap |
| Strategy | `strategies/*` | Pure proposal functions |
| Scoring | `scoring/*` | Null comparison diagnostics |
| Coverage | `coverage/*` | Combinatorial extras |

## Invariants

1. **Causal history** — strategies never see the target period's outcome.
2. **Freeze-before-settle** — no backfill freezes after settle.
3. **Experiment identity** — strategy set frozen after first freeze row.
4. **Ledger append-only** — SHA-256 chain; `doctor` / `status` verify.
5. **Claims are soft** — reports default `descriptive_only`.

## Extension points

### Domain pack

Register in `domains/__init__.py` with `DomainInfo`. Provide:

- `DOMAIN_ID`, `GAME: GameSpec`
- optional `prepare_data(data_dir, max_months=...)` for network
- optional `write_demo_data` for offline

### Strategy plugin

```toml
[project.entry-points."nullbench.strategies"]
my_kind = "mypkg:propose"
```

Signature: `(game, spec, history, period_seed) -> list[Ticket]`.

## Public library API

Prefer:

```python
from nullbench import init_study, add_strategy, freeze_period, settle_period
```

Avoid importing private CLI helpers.
