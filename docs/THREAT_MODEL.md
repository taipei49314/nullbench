# Threat model

> **Status: FROZEN (M2)** — nullbench 0.7.0 · 2026-08-12
>
> **0.9.0 amendment:** v3 evidence distinguishes pre-outcome registration from retrospective and legacy records.

## Assets

- Study ledger (freeze/settle evidence)
- Registration class and the causal history prefix available at freeze time
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
| Known outcome presented as pre-registered | v3 mode + history anchor; explicit backtest; legacy is formal-ineligible | | |
| Local outcome removed or clock forged before freeze | Out of scope for local evidence; a freeze-before-outcome vault receipt adds an external boundary | | trusted receipt detects later rewrite |
| Backtest/legacy rows mixed into formal sample size | Registration class bound into freezes and settlements; only v3 pre-outcome is eligible | | |
| Forged payout with re-linked chain | semantic recompute | | |
| Missing tip after rewrite | tip required when ledger non-empty | | |
| Malicious plugin | trust env off by default | allowlist file | |
| Stolen long-lived PyPI token | docs discourage | OIDC trusted publish + SBOM | |
| Consistent full rewrite (A5) | residual locally | SBOM helps consumers | **vault receipt verify** |

## External-evidence boundary

~~Proving integrity against A5 without external append-only storage or signing service.~~

### Amendment (0.8.0 — M4 shipped)

A5 is addressed **relative to an external vault** via:

- `nullbench vault init` — HMAC key + append-only `receipts.jsonl` outside the study
- `nullbench seal notarize` — exact canonical bundle archived, then tip + file hashes signed into receipt-v2
- `nullbench seal verify` — exact-current verification, or bounded proof that the archived snapshot is an unchanged ledger ancestor; later tail remains unnotarized
- optional loopback-only `nullbench vault serve` HTTP notary (`NULLBENCH_NOTARY_URL`); remote exposure requires TLS termination/tunneling

Compromise of the vault key, vault clock, or archived bundles remains out of scope for that vault. Receipt and archive checks detect corruption but cannot defeat an attacker who controls the key and consistently replaces the trust root. A remote notary receives manifest hashes rather than uploaded bundle bytes; preserve the corresponding export if the remote authority must inspect content independently.

## Assumptions

1. Single-user local study directories are the primary deployment.
2. Operators who set `NULLBENCH_TRUST_PLUGINS=1` accept in-process code execution risk.
3. PyPI Trusted Publisher is configured by the maintainer for production releases.
4. Freeze-v2 timestamps alone cannot prove when the operator first learned an outcome; v2 is therefore retained as descriptive legacy evidence only.

Notarizing a backtest does not convert it into pre-registration. A v2 receipt plus intact local archive proves that the labeled snapshot existed by the vault-recorded time. Ancestor success proves only that snapshot and unchanged ledger prefix, never the unnotarized current tail. Receipt-v1 metadata was client-overridable and is treated as content compatibility rather than a vault-clock boundary.
