# PRD — nullbench

> **Status: FROZEN (M2)** — nullbench 0.7.0 · 2026-08-12  
> Changes to goals / non-goals / stable API require a version bump and CHANGELOG.

## Problem

People over-claim discrete decision strategies (lottery-like, portfolio picks, agent picks).
There is no small, installable lab that forces **pre-registration**, **equal-cost nulls**, and **detectable inconsistent edits**.

## Goals

1. Local-first study workspace: freeze → settle → report
2. Null-first comparison (equal-cost chance portfolios)
3. Detect casual / inconsistent tampering (M1 seals); do not claim global notary without M4
4. Extensible domains/strategies with explicit trust gates
5. Public open-source packaging: installable PyPI package, CI, docs, security policy

## Non-goals (through M3)

- Real-money betting integration
- Guaranteed prediction or “winning systems”
- Multi-tenant SaaS
- Unrestricted plugin execution by default
- Absolute tamper-proofing against full local rewrite (A5) without external notary (M4)

## Users

| Persona | Job |
|---------|-----|
| Skeptical engineer | Kill bad strategy narratives with evidence |
| Educator | Teach pre-registration / null models |
| Researcher | Domain packs + formal looks (26/52) |
| OSS adopter | `pip install` + demo without reading source |

## Core loop

```text
init → strategy add → freeze → settle → report → (repeat freeze)
```

Coach: `next`, health: `doctor`, gate: `maturity --check-m1`.

## Success metrics

| Metric | Target |
|--------|--------|
| Time to first report | < 5 min (`demo`) |
| M1 gate | `pytest -m m1` green on CI |
| Claim policy | README / PyPI description comply with CLAIM_POLICY |
| Public API | Listed in PUBLIC_API.md; covered by import smoke |

## Release gates

| Gate | Rule |
|------|------|
| **M1** | Required before marketing local seals / tamper-*detecting* language |
| **M2** | This PRD + THREAT_MODEL + CLAIM_POLICY + PUBLIC_API frozen |
| **M3** | OIDC publish workflow + SBOM artifact + plugin allowlist |
| **M4** | Only then: remote sealed study / vault; absolute never-backfill vs A5 |

## Related

- [PUBLIC_API.md](PUBLIC_API.md) · [THREAT_MODEL.md](THREAT_MODEL.md) · [CLAIM_POLICY.md](CLAIM_POLICY.md) · [MATURITY.md](MATURITY.md)
