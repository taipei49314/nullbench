# Architecture

nullbench is a thin **honesty layer** over domain games and scoring giants.

```text
┌─────────────────────────────────────────────────────────────┐
│  CLI (product)          doctor · next · periods · demo      │
├─────────────────────────────────────────────────────────────┤
│  Pipeline               init → strategy → freeze            │
│                         → settle → report                   │
├───────────────┬─────────────────────┬───────────────────────┤
│  Study /      │  Strategies         │  Domains              │
│  Ledger       │  Protocol + plugins │  DomainInfo registry  │
│  hash chain   │  entry_points       │  offline / network    │
├───────────────┴─────────────────────┴───────────────────────┤
│  Scoring        comparecast port · brier · null bank        │
│  Formal         alpha-spending looks (26 / 52)              │
│  Report         markdown · JSON · single-file HTML          │
│  Coverage       OR-Tools (optional extra)                   │
└─────────────────────────────────────────────────────────────┘
```

## Layers

| Layer | Package path | Responsibility |
|-------|--------------|----------------|
| Product | `cli.py`, `core/workspace.py` | UX, coach (`next`), doctor, STUDY.md |
| Pipeline | `core/pipeline.py` | Golden path orchestration |
| Contracts | `protocols.py`, `core/models.py`, `errors.py` | Stable types, registration modes & errors |
| Integrity | `core/ledger.py`, `core/hashing.py` | Append-only evidence |
| Domain | `domains/*` + entry points `nullbench.domains` | Game rules + data bootstrap |
| Strategy | `strategies/*` + entry points `nullbench.strategies` | Pure proposal functions |
| Scoring | `scoring/*` | Null comparison diagnostics |
| Formal | `formal/*` | Pre-registered α-spending |
| Report | `report/html.py` | Static single-file HTML |
| Coverage | `coverage/*` | Combinatorial extras |

## Invariants

1. **Causal history** — a v3 `pre_outcome` freeze seals an ordered history prefix before the target outcome exists.
2. **Explicit retrospection** — a known outcome requires `backtest`; it is never represented as pre-registered.
3. **Experiment identity** — strategy set frozen after first freeze row.
4. **Ledger append-only** — SHA-256 chain; `doctor` / `status` verify.
5. **Claims are bounded** — backtest and legacy settlements are always `descriptive_only`.
6. **Pending is valid** — batch settlement skips an unrevealed pre-outcome target.
7. **Cohorts do not mix** — one experiment cannot combine prospective and historical registration classes.
8. **Writers cooperate** — normal state-changing commands serialize through a per-study lock; deliberate direct file edits remain inside the local-operator trust boundary.
9. **Equal-cost arms** — all StrategySpec ticket counts, and the tickets actually returned by plugins, match before a freeze can commit.
10. **Bounded notarization** — receipt-v2 archives the exact bundle before signing; descendant verification attests only its unchanged ledger prefix, not later tail rows.

## Registration evidence (0.9.0)

```text
pre_outcome: target absent → freeze v3 → optional notarize → reveal outcome → settle v2
backtest:    target present + explicit backtest → freeze v3 → settle v2 → descriptive-only
```

Freeze schema v3 binds `registration_mode`, `frozen_at`, and a `history_anchor` to the content hash. The `ordered_prefix_v1` anchor stores the number of historical draws and the final `(date, period)` boundary; verification re-hashes that exact prefix.

- `pre_outcome`: target outcome absent, `outcome_hash=null`, `late=false`.
- `backtest`: target outcome already known, non-null `outcome_hash`, `late=true`.

Freeze schema v2 remains readable and is hashed with its original payload. It is not rewritten as v3: records with an outcome hash classify as `legacy_backtest`; records without one classify as `legacy_unknown`. Both classes are formal-ineligible.

The local `frozen_at` value is sealed metadata, not trusted wall-clock proof. A receipt-v2 created after freeze and before the outcome archives the exact target-absent snapshot and adds an external boundary only relative to that vault's key, clock, and retained archive. After outcome/settlement append, verification can prove the snapshot remains a strict ledger ancestor while clearly labeling the new tail unnotarized. Legacy receipt-v1 supports exact content compatibility but not this clock/ancestor claim.

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

freeze_period(prospective_root, "P0121")
freeze_period(backtest_root, "P0120", backtest=True)  # separate experiment
```

Avoid importing private CLI helpers.
