# nullbench

[![PyPI](https://img.shields.io/pypi/v/nullbench.svg)](https://pypi.org/project/nullbench/)
[![Python](https://img.shields.io/pypi/pyversions/nullbench.svg)](https://pypi.org/project/nullbench/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**Pre-register decisions. Score them against chance. Never backfill.**

nullbench is a **null-first decision evaluation** lab: freeze choices *before* outcomes, settle against equal-cost chance portfolios, keep an append-only hash-chained ledger, and report descriptive percentiles plus sequential confidence sequences / e-diagnostics.

It is **not** a lottery predictor. Negative expected-value domains are welcome as *stress tests* for methodology.

> Formal question: *Is any strategy distinguishable from pure chance at equal cost?*  
> Expected (and welcome) answer for fair games: **no**.

## Install

```bash
pip install nullbench
# optional
pip install "nullbench[coverage]"   # OR-Tools
pip install "nullbench[stats]"      # properscoring (+ comparecast non-Windows)
```

Requires **Python 3.11+**.

## 60-second start

```bash
nullbench doctor
nullbench demo --name try1
nullbench next --study try1
```

Open `try1/reports/latest.md` and `try1/STUDY.md`.

## Golden path (manual)

```bash
nullbench init my-study -d demo649
nullbench strategy add random --study my-study --tickets 5 --seed 1
nullbench strategy add frequency --study my-study --id frequency --tickets 5
nullbench periods --study my-study
nullbench freeze --study my-study --latest
nullbench settle --study my-study
nullbench report --study my-study
nullbench next --study my-study
```

## Product commands

| Command | Purpose |
|---------|---------|
| `doctor` | Environment + optional study health |
| `next` | What to do next in this study |
| `periods` | Draw list with freeze/settle flags |
| `demo` | One-shot end-to-end |
| `init` / `strategy` / `freeze` / `settle` / `report` | Core loop |
| `ingest` | Taiwan official API domains |
| `coverage` | Max-disjoint multi-ticket plan |
| `formal` | Enable alpha-spending looks (26/52) before freezes |
| `domains -v` / `strategies -v` | Discovery (builtin + plugins) |

After `report`, open **`reports/latest.html`** (single-file static) or `latest.md`:

```bash
nullbench report --study my-study --open
```

## Taiwan domains

```bash
nullbench init tw -d taiwan_super --fetch
# or: nullbench ingest --study tw
nullbench strategy add random --study tw -n 5
nullbench freeze --study tw --latest
nullbench settle --study tw
nullbench report --study tw
```

Floating jackpot tiers value at **0** by default (conservative). Pure simulation — no betting.

## Architecture (skeleton)

```text
CLI / workspace (product)
        ↓
   pipeline (freeze → settle → report)
        ↓
 models · ledger · domains · strategies · scoring
```

- **Contracts:** `protocols.py`, `errors.py`, Pydantic models  
- **Integrity:** append-only JSONL + SHA-256 chain  
- **Plugins:** `nullbench.strategies` + `nullbench.domains` entry points  
- **Formal:** alpha-spending at n=26 (α=0.005) and n=52 (α=0.020)  
- **Docs:** [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · [docs/PRODUCT.md](docs/PRODUCT.md) · [CHANGELOG.md](CHANGELOG.md)

## Giants

| Need | We use |
|------|--------|
| Schemas / CLI | Pydantic, Typer, Rich |
| Sequential CS + e-process | comparecast algorithms (pure-Python port; official when confseq builds) |
| Coverage search | OR-Tools CP-SAT (optional) |
| Proper scores | properscoring (optional) |

## Library API

```python
from pathlib import Path
from nullbench import init_study, add_strategy, freeze_period, settle_period

root = Path("my-study")
init_study(root, experiment_id="exp-v1")
add_strategy(root, strategy_id="random", kind="random", tickets=5)
freeze_period(root, "P0100")
settle_period(root, "P0100")
```

## Design rules

1. No look-ahead  
2. Never backfill freezes after settle  
3. Change params after freezes → new experiment  
4. Core path: deterministic, zero LLM  
5. Reports default descriptive  

## Ethics

Pure simulation / evaluation. No betting integration. Do not market “predicted numbers.”

## License

MIT — see [LICENSE](LICENSE).

## Lineage

Honesty DNA from private research (`lotto-lab`). **nullbench** is the public product on [PyPI](https://pypi.org/project/nullbench/).
