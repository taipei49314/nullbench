# PRD — nullbench

> **Status: FROZEN (M2), amended by nullbench 0.9.0** — originally frozen in 0.7.0.
>
> 0.9.0 is a versioned semantic break: pre-outcome registration is fail-closed, historical evaluation requires explicit backtest mode, and legacy evidence is classified without rewrite.

## Problem

People over-claim discrete decision strategies (lottery-like, portfolio picks, agent picks).
There is no small, installable lab that enforces **pre-outcome classification relative to committed study data**, **equal-cost nulls**, and **detectable inconsistent edits**.

## Goals

1. Local-first study workspace: pre-outcome freeze → outcome reveal → settle → report
2. Null-first comparison (equal-cost chance portfolios)
3. Detect casual / inconsistent tampering (M1 seals); do not claim global notary without M4
4. Extensible domains/strategies with explicit trust gates
5. Public open-source packaging: installable PyPI package, CI, docs, security policy
6. Explicit retrospective backtests that cannot be promoted to pre-registration claims

## Non-goals (through M3)

- Real-money betting integration
- Guaranteed prediction or “winning systems”
- Multi-tenant SaaS
- Unrestricted plugin execution by default
- Absolute tamper-proofing against full local rewrite (A5) without external notary (M4)
- Treating local `frozen_at` as independent proof of real-world time
- Converting backtest or legacy evidence into pre-registration after the fact

## Users

| Persona | Job |
|---------|-----|
| Skeptical engineer | Kill bad strategy narratives with evidence |
| Educator | Teach pre-registration / null models |
| Researcher | Domain packs + formal looks (26/52) |
| OSS adopter | `pip install` + demo without reading source |

## Core loop

```text
init → strategy add → freeze future PERIOD → reveal outcome → settle → report
                         └ historical data: explicit backtest, descriptive-only
```

Coach: `next`, health: `doctor`, gate: `maturity --check-m1`.

## Success metrics

| Metric | Target |
|--------|--------|
| Time to first report | < 5 min (`demo`) |
| M1 gate | `pytest -m m1` green on CI |
| Claim policy | README / PyPI description comply with CLAIM_POLICY |
| Public API | Listed in PUBLIC_API.md; covered by import smoke |
| Registration truth | Known target fails without backtest; missing target freezes as pending |
| Compatibility | v2 ledger verifies without rewrite; only v3 pre-outcome advances formal checkpoints |
| Equal-cost truth | Every committed arm declares and returns the same ticket count; formal mode requires one primary |
| M4 evolution | Receipt-v2 archives the exact snapshot; later verification labels exact vs unnotarized append-only descendant |

## Release gates

| Gate | Rule |
|------|------|
| **M1** | Required before marketing local seals / tamper-*detecting* language |
| **M2** | This PRD + THREAT_MODEL + CLAIM_POLICY + PUBLIC_API frozen |
| **M3** | OIDC publish workflow + SBOM artifact + plugin allowlist |
| **M4** | Vault-relative detection of post-receipt A5 rewrites; never an absolute guarantee |

## Related

- [PUBLIC_API.md](PUBLIC_API.md) · [THREAT_MODEL.md](THREAT_MODEL.md) · [CLAIM_POLICY.md](CLAIM_POLICY.md) · [MATURITY.md](MATURITY.md)
