# Claim policy

> **Status: FROZEN (M2)** — nullbench 0.7.0 · 2026-08-12

## Always forbidden (reports + marketing)

- Prediction / 必中 / winning numbers / guaranteed win / beat the lottery
- Language covered by `nullbench.core.claims.FORBIDDEN`

## Before M1 gate green

Forbidden as product guarantees:

- “可稽核” / “fully auditable” as absolute
- “永不 backfill” / “never backfill” as absolute
- “tamper-proof”

## Allowed after M1 green (with residual footnote)

- Lab / research tool with **M1 local seals**
- Detects **inconsistent** edits (seal drift, forged payouts vs recomputation)
- “Tamper-detecting under the M1 model”
- Must mention residual risk: consistent full local rewrite (A5) until M4

## Allowed after M2 freeze

- “Stable public API” (see PUBLIC_API.md)
- “Frozen PRD / threat model / claim policy”

## Allowed after M3

- “OIDC Trusted Publishing workflow in-repo”
- “SBOM produced in CI”
- “Plugin allowlist supported”

Still not allowed without M4: absolute never-backfill against A5.

## Report claims

| Claim status | When |
|--------------|------|
| `descriptive_only` | Default; between formal looks |
| `formal_endpoint` | Only at α-spending checkpoints with formal enabled |

Report generator must run claim lint before write.

## Human marketing checklist

1. `nullbench maturity --check-m1`
2. If fail → no M1 seal marketing
3. If pass → “M1 local seals; residual risk in THREAT_MODEL”
4. Cite M2 freeze for API stability claims
5. Cite M3 for supply-chain claims
