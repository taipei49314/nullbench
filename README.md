# nullbench

[![CI](https://github.com/taipei49314/nullbench/actions/workflows/ci.yml/badge.svg)](https://github.com/taipei49314/nullbench/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/nullbench.svg)](https://pypi.org/project/nullbench/)
[![Python](https://img.shields.io/pypi/pyversions/nullbench.svg)](https://pypi.org/project/nullbench/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**Write the decision down before the result. Then score it against chance.**

Did your picks beat a pile of random tickets that cost the same? nullbench
makes that experiment cheap, local, and hard to cheat: freeze first, settle
later, refuse silent edits.

It is **not** a lottery predictor and has no betting integration. Residual
risks (what an attacker can still do) live in [CLAIM_POLICY](docs/CLAIM_POLICY.md)
and [THREAT_MODEL](docs/THREAT_MODEL.md).

## Why this exists

People over-claim strategies. nullbench makes the honest experiment cheap:

1. Pre-register (freeze)  
2. Score vs equal-cost chance (settle)  
3. Refuse silent backfill when seals disagree  

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

The demo is **replay mode**: it freezes periods whose outcomes already
exist, so it demonstrates the mechanics — not prospective pre-registration.
The north-star mode (freeze before the draw exists) is stage M5; see
[NORTH_STAR.md](NORTH_STAR.md).

## Golden path

```bash
nullbench init my-study -d demo649
nullbench strategy add random --study my-study --tickets 5 --seed 1
nullbench freeze --study my-study --latest
nullbench settle --study my-study
nullbench report --study my-study --open
```

## Maturity

| Level | Status |
|-------|--------|
| **M0** Lab / PyPI | done |
| **M1** Local seals + adversarial tests | done |
| **M2** PRD / threat model / API / claims frozen | frozen |
| **M3** OIDC publish + SBOM + plugin allowlist | done |
| **M4** External vault notary (A5 control) | done |
| **M5** First real prospective experiment | **in progress** — M5.0–M5.2 on master (0.9.0 tag is void, never published to PyPI). M5.3 `nullbench cycle` is in this unreleased branch. See [NORTH_STAR](NORTH_STAR.md) |

```bash
nullbench maturity
nullbench maturity --check-m1
nullbench maturity --check-m4
```

### M4 notarize

```bash
nullbench vault init
nullbench seal notarize --study try1
nullbench seal verify --study try1
```

## Library

```python
from nullbench import init_study, add_strategy, freeze_period, settle_period, build_report
```

Stable surface: [docs/PUBLIC_API.md](docs/PUBLIC_API.md).

## Docs

| Doc | Purpose |
|-----|---------|
| [NORTH_STAR](NORTH_STAR.md) | Stage M5: the first real prospective experiment |
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
