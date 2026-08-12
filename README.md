# nullbench

[![PyPI](https://img.shields.io/pypi/v/nullbench.svg)](https://pypi.org/project/nullbench/)
[![Python](https://img.shields.io/pypi/pyversions/nullbench.svg)](https://pypi.org/project/nullbench/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**Pre-register decisions. Score them against chance.**  
Lab / alpha — local seals under **M1**; not a global notary.

> **Product gate:** without a green M1 gate, do **not** claim absolute「可稽核」or「永不 backfill」.  
> See [docs/MATURITY.md](docs/MATURITY.md).

nullbench is a **null-first decision evaluation** lab: freeze choices *before* outcomes, settle against equal-cost chance portfolios, keep an append-only ledger with **semantic seals**, and report descriptive percentiles plus sequential diagnostics.

It is **not** a lottery predictor. Negative expected-value domains are welcome as methodology stress tests.

## Maturity (M0 → M4)

| Level | Meaning |
|-------|---------|
| **M0** | Lab CLI / demo / PyPI alpha — *shipping* |
| **M1** | Sealed ExperimentSpec + pin hashes + settle verify + claim lint + adversarial IC-01…08 — *must-pass* |
| **M2** | PRD + Threat Model + Public API + Claim Policy frozen |
| **M3** | OIDC trusted publish / SBOM / plugin allowlist |
| **M4** | Remote sealed study / vault |

```bash
nullbench maturity
nullbench maturity --check-m1    # pytest -m m1
```

## Install

```bash
pip install nullbench
# from source (needed for maturity --check-m1 tests)
pip install -e ".[dev]"
```

Python **3.11+**.

## 60-second start

```bash
nullbench doctor
nullbench demo --name try1
nullbench report --study try1 --open
nullbench next --study try1
nullbench maturity --check-m1
```

## Golden path

```bash
nullbench init my-study -d demo649
nullbench strategy add random --study my-study --tickets 5 --seed 1
nullbench freeze --study my-study --latest
nullbench settle --study my-study
nullbench report --study my-study --open
```

## What M1 seals (local)

| Seal | Purpose |
|------|---------|
| `experiment_hash` | Spec cannot silently change after freeze |
| `content_hash` | Tickets + seals bound |
| `history_hash` / `outcome_hash` | Draw history / known outcome pinned |
| Tip + semantic audit | Forged payouts fail even if chain re-linked |
| Claim lint | Report text scanned for promotional language |

Residual risk: an adversary who rewrites **all** seals consistently still wins until M4. Documented in [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md).

## Commands

| Command | Purpose |
|---------|---------|
| `maturity` | Ladder + optional M1 gate |
| `doctor` | Env + chain + semantic |
| `next` / `periods` | Coach / navigation |
| `demo` / `init` / `strategy` / `freeze` / `settle` / `report` | Core loop |
| `formal` | α-spending 26/52 (before freeze) |
| `ingest` / `coverage` | Taiwan data / OR-Tools extra |
| `domains -v` / `strategies -v` | Discovery (plugins need `NULLBENCH_TRUST_PLUGINS=1`) |

## Docs

- [MATURITY.md](docs/MATURITY.md) · [INTEGRITY.md](docs/INTEGRITY.md)
- [PRD.md](docs/PRD.md) · [THREAT_MODEL.md](docs/THREAT_MODEL.md) · [CLAIM_POLICY.md](docs/CLAIM_POLICY.md) *(M2 drafts)*
- [ARCHITECTURE.md](docs/ARCHITECTURE.md) · [PRODUCT.md](docs/PRODUCT.md) · [CHANGELOG.md](CHANGELOG.md)

## Ethics

Pure simulation. No betting integration. Do not market predicted numbers.

## License

MIT
