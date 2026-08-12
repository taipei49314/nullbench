# Threat model (DRAFT — M2 not frozen)

## Assets

- Study ledger (freeze/settle evidence)
- Experiment parameters (`experiment.json`)
- Draw history (`draws.jsonl` / cache)
- Generated reports (md/html/json)
- Published package integrity (PyPI)

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
[plugins] --trust gate--> [nullbench process]
[study dir] <--- seals --- [integrity module]
[PyPI] <--- OIDC (M3) --- [GitHub Actions]
```

## Controls by maturity

| Threat | M1 | M3 | M4 |
|--------|----|----|-----|
| Accidental backfill / hash drift | seals + settle verify | | |
| Forged payout with re-linked chain | semantic recompute | | |
| Malicious plugin | trust env off by default | allowlist file | |
| Stolen long-lived PyPI token | docs discourage | OIDC trusted publish | |
| Consistent full rewrite | **residual** | SBOM | remote vault/notary |

## Out of scope until M4

Proving integrity against A5 without external append-only storage or signing service.
