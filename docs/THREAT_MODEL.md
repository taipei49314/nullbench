# Threat model

> **Status: FROZEN (M2)** — nullbench 0.7.0 · 2026-08-12

## Assets

- Study ledger (freeze/settle evidence)
- Experiment parameters (`experiment.json`)
- Draw history (`draws.jsonl` / cache)
- Generated reports (md/html/json)
- Published package integrity (PyPI)
- Plugin entry points loaded into the user process

## Adversaries

| Actor | Capability |
|-------|------------|
| A1 Honest mistake | Accidental edit, reorder, re-run |
| A2 Local tamperer | Read/write study directory |
| A3 Plugin author | Malicious entry-point code |
| A4 Supply chain | Compromised release token / build |
| A5 Full disk god | Arbitrary consistent rewrite of all seals |

## Trust boundaries

```text
[plugins] --trust env / allowlist--> [nullbench process]
[study dir] <--- seals + tip --- [integrity module]
[PyPI] <--- OIDC Trusted Publishing --- [GitHub Actions]
```

## Controls by maturity

| Threat | M1 | M3 | M4 |
|--------|----|----|-----|
| Accidental backfill / hash drift | seals + settle verify + hard non-empty seals | | |
| Forged payout with re-linked chain | semantic recompute | | |
| Missing tip after rewrite | tip required when ledger non-empty | | |
| Malicious plugin | trust env off by default | allowlist file | |
| Stolen long-lived PyPI token | docs discourage | OIDC trusted publish + SBOM | |
| Consistent full rewrite (A5) | **residual** | SBOM helps consumers | remote vault/notary |

## Out of scope until M4

Proving integrity against A5 without external append-only storage or signing service.

## Assumptions

1. Single-user local study directories are the primary deployment.
2. Operators who set `NULLBENCH_TRUST_PLUGINS=1` accept in-process code execution risk.
3. PyPI Trusted Publisher is configured by the maintainer for production releases.
