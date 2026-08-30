# nullbench

[![CI](https://github.com/taipei49314/nullbench/actions/workflows/ci.yml/badge.svg)](https://github.com/taipei49314/nullbench/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/nullbench.svg)](https://pypi.org/project/nullbench/)
[![Python](https://img.shields.io/pypi/pyversions/nullbench.svg)](https://pypi.org/project/nullbench/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**Pre-register before outcomes. Label backtests honestly. Score decisions against chance.**

Open-source **null-first decision lab**: freeze choices before outcomes, settle against equal-cost chance portfolios, keep a sealed local ledger, and report descriptive evidence — not predictions. Since 0.9.0, a normal `freeze PERIOD` only accepts an outcome that is not yet present; historical analysis must opt in with `--backtest`.

> **Not** a lottery predictor. No betting integration.  
> **M1** detects inconsistent local edits. **M4** detects post-receipt divergence relative to a trusted vault; neither is an absolute tamper-proof guarantee. See [CLAIM_POLICY](docs/CLAIM_POLICY.md) and [THREAT_MODEL](docs/THREAT_MODEL.md).

## Why this exists

People over-claim strategies. nullbench makes the honest experiment cheap:

1. Pre-register (freeze before the outcome exists)
2. Score vs equal-cost chance (settle)  
3. Label retrospective work as backtest instead of pre-registration

## Install

```bash
pip install nullbench
# contributors / M1 gate from source:
pip install -e ".[dev]"
```

Requires **Python 3.11+**.

## 60-second start

```bash
nullbench doctor
nullbench demo --name try1
nullbench report --study try1 --open
nullbench next --study try1
```

`demo` replays synthetic outcomes as a **backtest**. It is useful for learning the product, but its results are always descriptive-only and are not pre-registered evidence.

## Pre-outcome path

```bash
nullbench init my-study -d demo649
nullbench strategy add random --study my-study --tickets 5 --seed 1
# P0121 must not exist in draws.jsonl yet.
nullbench freeze P0121 --study my-study
# Optional stronger anchor: notarize this freeze before the outcome.
nullbench vault init  # once per vault/machine
nullbench seal notarize --study my-study
# After the P0121 outcome is ingested or appended:
nullbench settle --study my-study --period P0121
nullbench report --study my-study --open
# Prove the current ledger extends the receipt-time snapshot:
nullbench seal verify --study my-study
```

Settling one still-pending period raises an outcome-pending error; batch `settle` skips pending periods.
Every strategy arm must declare and return the same number of tickets, so the shared null bank is genuinely equal-cost. A formal endpoint additionally requires one pre-specified primary strategy before the first freeze.

## Historical backtest

Known outcomes require an explicit retrospective flag:

```bash
nullbench init my-backtest -d demo649
nullbench strategy add random --study my-backtest --tickets 5 --seed 1
nullbench freeze P0120 --study my-backtest --backtest
nullbench freeze --study my-backtest --latest --backtest
nullbench freeze --study my-backtest --last 10 --backtest
nullbench settle --study my-backtest
```

`--latest` and `--last` are historical selectors and are rejected without `--backtest`. Backtest and legacy records remain descriptive-only, even when formal endpoints are enabled.

One experiment cannot mix prospective and historical registration modes; start a separate study or experiment id for the backtest. `pre_outcome` describes the study state at freeze time, not independent proof of real-world time. A trusted vault receipt created before the outcome provides a stronger external anchor.

## Maturity

| Level | Status |
|-------|--------|
| **M0** Lab / PyPI | done |
| **M1** Local seals + adversarial tests | done |
| **M2** PRD / threat model / API / claims frozen | frozen |
| **M3** OIDC publish + SBOM + plugin allowlist | done |
| **M4** External vault notary (A5 control) | done |

```bash
nullbench maturity
nullbench maturity --check-m1
nullbench maturity --check-m4
```

### M4 notarize

```bash
nullbench vault init
nullbench seal notarize --study my-study
nullbench seal verify --study my-study
```

Receipt-v2 notarization stores a content-addressed snapshot under the external vault before signing. Verification either reports an exact bundle match, or `ANCESTOR VERIFIED / CURRENT BUNDLE NOT NOTARIZED` when the current ledger is a strict append-only descendant and the archived snapshot proves its v3 `pre_outcome` targets were absent. The latter attests only the unchanged notarized prefix; notarize again to anchor the current tail. Notarization never converts a backtest or legacy record into pre-registration.

## Library

```python
from nullbench import init_study, add_strategy, freeze_period, settle_period, build_report

freeze_period(prospective_root, "P0121")                 # target absent
freeze_period(backtest_root, "P0120", backtest=True)     # separate experiment
```

Stable surface: [docs/PUBLIC_API.md](docs/PUBLIC_API.md).

## Docs

| Doc | Purpose |
|-----|---------|
| [PRD](docs/PRD.md) | Product requirements (frozen) |
| [PUBLIC_API](docs/PUBLIC_API.md) | Stable imports / CLI jobs |
| [INTEGRITY](docs/INTEGRITY.md) | Seal model + plugin allowlist |
| [THREAT_MODEL](docs/THREAT_MODEL.md) | Adversaries A1–A5 |
| [CLAIM_POLICY](docs/CLAIM_POLICY.md) | What you may say publicly |
| [MATURITY](docs/MATURITY.md) | M0–M4 ladder |
| [RUNBOOK](docs/RUNBOOK.md) | Release, Trusted Publisher, ops |
| [ARCHITECTURE](docs/ARCHITECTURE.md) | Layers |
| [CONTRIBUTING](CONTRIBUTING.md) | How to hack |
| [SECURITY](SECURITY.md) | How to report issues |
| [PUBLISH](PUBLISH.md) | Build / PyPI |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).  
PRs that touch seals must keep `pytest -m m1` green.

## Ethics

Pure simulation / evaluation. Do not market predicted numbers.

## License

MIT — [LICENSE](LICENSE).
