# nullbench

**Pre-register decisions. Score them against chance. Never backfill.**

nullbench is a **null-first decision evaluation** lab: freeze choices *before* outcomes, settle against equal-cost pure-chance portfolios, keep an append-only hash-chained ledger, and report descriptive percentiles plus sequential e-diagnostics.

It is **not** a lottery predictor. Negative expected-value domains are welcome as *stress tests* for methodology.

> Formal question: *Is any strategy distinguishable from pure chance at equal cost?*  
> Expected (and welcome) answer for fair games: **no**.

## Install

```bash
# Python 3.11+
pip install nullbench

# from source
pip install -e ".[dev]"
```

Optional extras:

```bash
pip install "nullbench[coverage]"   # OR-Tools max-disjoint coverage
pip install "nullbench[stats]"      # properscoring; comparecast on non-Windows
# Sequential CS + e-process: pure-Python comparecast algorithms always on
# (official comparecast needs confseq/MSVC on Windows — we ship a MIT port)
```

## 5-minute demo

```bash
nullbench demo --name demo-study --path .

# step by step
nullbench init my-study -e exp-v1 -d demo649
nullbench strategy add random --study my-study --tickets 5 --seed 1
nullbench strategy add frequency --study my-study --id frequency --tickets 5 --seed 2
nullbench freeze P0100 --study my-study
nullbench settle --study my-study --period P0100
nullbench report --study my-study
nullbench status --study my-study
nullbench coverage --study my-study --tickets 5 --top 30
```

## Taiwan Lottery domains (network)

```bash
# 威力彩 / 大樂透 — official API, month cache, fail-closed parse
nullbench init tw-super -d taiwan_super --fetch
# or: init without fetch, then
nullbench ingest --study tw-super

nullbench strategy add random --study tw-super -n 5
# pick a historical period id present in draws.jsonl, freeze BEFORE using that outcome
nullbench freeze 115000058 --study tw-super
nullbench settle --study tw-super --period 115000058
nullbench report --study tw-super
```

**Conservative valuation:** floating jackpot tiers score as **0** by default so reports cannot be inflated by rare top prizes. Fixed tiers only.

Pure simulation. No betting. No predicted numbers.

List domains: `nullbench domains`

## What you get

| Piece | Role |
|-------|------|
| **Freeze** | Tickets locked with `content_hash` before outcome use |
| **Null bank** | N equal-cost random portfolios (default 200) |
| **Settle** | P&L under prize table; never rewrites freezes |
| **Ledger** | Append-only JSONL + SHA-256 chain |
| **Report** | Descriptive percentiles + sequential e-diagnostics |
| **Claim guard** | Blocks promotional language scans |
| **Plugins** | `nullbench.strategies` entry points |

## Giants we stand on

| Layer | Package / plan |
|-------|----------------|
| Schemas / CLI | **Pydantic v2**, **Typer**, **Rich** |
| Numerics | **NumPy** |
| Proper scores | **properscoring** (optional) |
| Sequential CS + e-process | **comparecast** algorithms (pure-Python port; official package when confseq builds) |
| Proper scores | **properscoring** optional |
| Combinatorial coverage | **OR-Tools** CP-SAT (`nullbench coverage`) |

Core honesty machinery (freeze, null bank, ledger, claim lint) stays **ours**.

## Plugin strategies

See [examples/plugin_strategy_readme.md](examples/plugin_strategy_readme.md).

```toml
[project.entry-points."nullbench.strategies"]
cold = "mypkg.strats:propose_cold"
```

## Study layout

```text
my-study/
  experiment.json
  data/draws.jsonl
  data/cache/raw/<game>/YYYY-MM.json   # taiwan only
  ledger/events.jsonl
  reports/latest.md
  reports/latest.json
```

## Domains

| Domain | Status |
|--------|--------|
| `demo649` | Offline synthetic 6/49 |
| `taiwan_super` | 威力彩 — official API |
| `taiwan_lotto649` | 大樂透 — official API |

## Design rules

1. **No look-ahead** — strategies only see draws strictly before the period.
2. **Change params after freezes → new experiment_id**.
3. **Never backfill** freezes after settle.
4. **Core path is deterministic**, zero LLM required.
5. **Reports default descriptive** — e-values are diagnostics, not discovery claims.

## Development / release

```bash
pip install -e ".[dev]"
pytest
python -m build
# twine upload dist/*   # requires PyPI token
```

## Ethics

- Pure simulation / evaluation. No betting integration.
- Real-money wagering is out of scope and discouraged.
- Do not use this tool to market “predicted numbers.”

## License

MIT — see [LICENSE](LICENSE).

## Lineage

Methodology DNA from private research (`lotto-lab`): preregistration, equal-cost nulls, hash ledgers, honesty guards. **nullbench** is the public product; `lotto-lab` remains a historical research archive.
