# Contributing to nullbench

Thanks for helping keep an honest, local-first decision lab.

## Quick start

```bash
python -m pip install -e ".[dev]"
pytest -q
pytest -m m1 -q          # product integrity gate
nullbench maturity
nullbench demo --name try1
```

Python **3.11+**.

## What belongs here

| In scope | Out of scope |
|----------|----------------|
| Integrity / seal bugs | Real-money betting integrations |
| Domains / strategies with trust gates | “Winning number” features |
| Docs, maturity, OSS surface | Multi-tenant SaaS |
| Tests that encode adversarial mutations | Unbounded plugin auto-trust |

## Pull requests

1. Branch from `master`.
2. Keep PRs focused (one concern).
3. Add / update tests for behavior changes — integrity changes need `pytest -m m1` coverage.
4. Do not market absolute「可稽核」/「永不 backfill」without the residual-risk footnote (see [docs/CLAIM_POLICY.md](docs/CLAIM_POLICY.md)).
5. Run before push:

```bash
pytest -q
pytest -m m1 -q
```

## Code style

- Match existing modules; prefer small, typed surfaces.
- Public library API is listed in [docs/PUBLIC_API.md](docs/PUBLIC_API.md) — do not break it without a CHANGELOG note and minor/major bump.
- Orchestration stays deterministic (no LLM-driven phase transitions).

## Plugins

Entry-point plugins are **off** unless:

- `NULLBENCH_TRUST_PLUGINS=1`, or
- the plugin id is listed in a plugin allowlist file (see [docs/INTEGRITY.md](docs/INTEGRITY.md))

Ship examples under `examples/`; do not enable trust-by-default.

## License

By contributing, you agree your changes are licensed under the MIT License (see [LICENSE](LICENSE)).
