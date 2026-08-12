# nullbench

**Pre-register decisions. Score them against chance. Never backfill.**

nullbench is a **null-first decision evaluation** lab: freeze choices *before* outcomes, settle against equal-cost pure-chance portfolios, and keep an append-only hash-chained ledger.

It is **not** a lottery predictor. Negative expected-value domains are welcome as *stress tests* for methodology.

> Formal question: *Is any strategy distinguishable from pure chance at equal cost?*  
> Expected (and welcome) answer for fair games: **no**.

## 5-minute demo

```bash
# Python 3.11+
pip install -e ".[dev]"

# One-shot golden path
nullbench demo --name demo-study --path .

# Or step by step
nullbench init my-study -e exp-v1 -d demo649
nullbench strategy add random --study my-study --tickets 5 --seed 1
nullbench strategy add frequency --study my-study --id frequency --tickets 5 --seed 2
nullbench freeze P0100 --study my-study
nullbench settle --study my-study --period P0100
nullbench report --study my-study
nullbench status --study my-study
```

Open `my-study/reports/latest.md`.

## What you get

| Piece | Role |
|-------|------|
| **Freeze** | Tickets locked with `content_hash` before outcome use |
| **Null bank** | N equal-cost random portfolios (default 200) |
| **Settle** | P&L under published prize table; never rewrites freezes |
| **Ledger** | Append-only JSONL + SHA-256 chain |
| **Report** | Descriptive percentiles only (v0.1 has no alpha spend) |
| **Claim guard** | Blocks promotional language in claim scans |

## Giants we stand on

| Layer | We use / will use |
|-------|-------------------|
| Schemas / CLI | **Pydantic v2**, **Typer**, **Rich** |
| Numerics | **NumPy** |
| Proper scores | **properscoring** (optional extra) — thin adapter in `nullbench.scoring` |
| Sequential e-values | Planned adapter: [expectation](https://github.com/jakorostami/expectation) |
| Forecaster comparison | Planned adapter: [comparecast](https://github.com/yjchoe/ComparingForecasters) |
| Combinatorial coverage | Planned extra: OR-Tools |

Core honesty machinery (freeze, null bank, ledger, claim lint) stays **ours** — that is the product.

## Study layout

```text
my-study/
  experiment.json      # immutable experiment identity
  data/draws.jsonl     # outcomes (demo is synthetic offline)
  ledger/events.jsonl  # freezes + settles (hash chain)
  reports/latest.md
  reports/latest.json
```

## Domains

| Domain | Status |
|--------|--------|
| `demo649` | Built-in offline 6/49-style synthetic game |
| `taiwan` | Planned pack (port from lotto-lab research archive) |

## Design rules

1. **No look-ahead** — strategies only see draws strictly before the period.
2. **Change params → new `experiment_id`** after freezes exist.
3. **Never backfill** freezes after settle.
4. **LLM optional later** — core path is deterministic, zero network.
5. **Reports default pessimistic / descriptive** — no “winning system” narrative.

## Library usage

```python
from pathlib import Path
from nullbench.core import pipeline

root = Path("my-study")
pipeline.init_study(root, experiment_id="exp-v1")
pipeline.add_strategy(root, strategy_id="random", kind="random", tickets=5)
pipeline.freeze_period(root, "P0100")
pipeline.settle_period(root, "P0100")
print(pipeline.build_report(root))
```

## Development

```bash
pip install -e ".[dev]"
pytest
```

## Ethics

- Pure simulation / evaluation. No betting integration.
- Real-money wagering is out of scope and discouraged.
- Do not use this tool to market “predicted numbers.”

## License

MIT — see [LICENSE](LICENSE).

## Lineage

Methodology DNA distilled from private research (`lotto-lab`): preregistration, equal-cost nulls, hash ledgers, honesty guards. **nullbench** is the public, domain-general product layer.
