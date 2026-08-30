# Claim policy

> **Status: FROZEN (M2)** — nullbench 0.7.0 · 2026-08-12
>
> **0.9.0 amendment:** registration class is evidence-derived; backtest and legacy records are descriptive-only.

## Always forbidden (reports + marketing)

- Prediction / 必中 / winning numbers / guaranteed win / beat the lottery
- Language covered by `nullbench.core.claims.FORBIDDEN`
- Calling a backtest, `legacy_backtest`, or `legacy_unknown` record “pre-registered”

## Before M1 gate green

Forbidden as product guarantees:

- “可稽核” / “fully auditable” as absolute
- “永不 backfill” / “never backfill” as absolute
- “tamper-proof”

## Allowed after M1 green (with residual footnote)

- Lab / research tool with **M1 local seals**
- Detects **inconsistent** edits (seal drift, forged payouts vs recomputation)
- “Tamper-detecting under the M1 model”
- Must mention residual risk: consistent full local rewrite (A5); M4 only detects divergence relative to a trusted prior receipt

## Allowed after M2 freeze

- “Stable public API” (see PUBLIC_API.md)
- “Frozen PRD / threat model / claim policy”

## Allowed after M3

- “OIDC Trusted Publishing workflow in-repo”
- “SBOM produced in CI”
- “Plugin allowlist supported”

Still not allowed: absolute never-backfill against A5. M4 permits only a vault-relative claim.

## Allowed after M4

- For exact mode: “Current bundle matches receipt … from vault …”
- For ancestor mode: “Receipt-time snapshot … remains an unchanged ledger prefix”; also state that the current tail is not notarized
- “Post-notarize rewrite of the notarized prefix/archive is detected against that vault”

Still forbidden: calling an ancestor-verified current tail “notarized”, or claiming absolute never-backfill when the vault key, clock, or archive is attacker-controlled.

## Report claims

| Claim status | When |
|--------------|------|
| `descriptive_only` | Default; all backtest and legacy evidence; between formal looks |
| `formal_endpoint` | Only from eligible v3 `pre_outcome` settlements at an enabled α-spending checkpoint |

`--backtest` is an honest retrospective workflow, not a weaker spelling of pre-registration. Freeze schema v2 remains verifiable for compatibility, but v2 records are classified as `legacy_backtest` when they contain an outcome hash and `legacy_unknown` otherwise. Neither class may be promoted to formal evidence.

A v3 `pre_outcome` label proves that the target was absent from the study data committed by that freeze. Its sealed `frozen_at` value is not an independently trusted clock. A receipt-v2 plus its intact archived bundle, created before the outcome, can support a stronger time-anchor statement relative to that vault. Descendant verification rechecks target absence in the archived snapshot and ledger-prefix identity, but does not notarize later events. Receipt-v1 metadata is client-overridable and supports exact content compatibility only. Notarizing a backtest does not change its registration class.

Report generator must run claim lint before write.

## Human marketing checklist

1. `nullbench maturity --check-m1`
2. If fail → no M1 seal marketing
3. If pass → “M1 local seals; residual risk in THREAT_MODEL”
4. Cite M2 freeze for API stability claims
5. Cite M3 for supply-chain claims
