# Maturity model

Product gate: **without M1, do not claim “auditable / never backfill” as a public guarantee.**

| Level | Name | Status target | Exit criteria |
|-------|------|---------------|---------------|
| **M0** | Lab CLI / demo / PyPI alpha | *current shipping* | Installable CLI, demo path, research domains |
| **M1** | Sealed local study (must-pass) | *gate for honest marketing* | See checklist below + `pytest -m m1` green |
| **M2** | Spec freeze | next | PRD + Threat Model + Public API + Claim Policy **published & frozen** |
| **M3** | Supply chain | after M2 | Trusted Publishing (OIDC), SBOM, plugin allowlist file |
| **M4** | Remote sealed study / vault | later | External notary / vault; resists full local rewrite |

## M1 checklist (必過)

| # | Requirement | Implementation |
|---|-------------|----------------|
| M1.1 | Seal `ExperimentSpec` | `experiment_hash` on every freeze |
| M1.2 | Pin freeze content | `content_hash` over tickets + seals |
| M1.3 | Pin history / draw | `history_hash`, `outcome_hash` when draw known |
| M1.4 | Settle forced verify | `verify_freeze_row` + **hard** seal drift checks before payout |
| M1.5 | Recompute not trust | Payouts recomputed; semantic audit detects forge |
| M1.6 | Claim lint | `scan_forbidden` before report write |
| M1.7 | Stable history order | `(date, period)` not file order |
| M1.8 | Code bind | strategy/domain source fingerprint |
| M1.9 | Adversarial tests IC-01…08 + R-01/R-02 | `pytest -m m1` |

### Commands

```bash
nullbench maturity              # show ladder
nullbench maturity --check-m1   # run M1 adversarial gate (exit 0/1)
pytest -m m1 -q                 # same gate in CI
```

## What M0 may say

- Lab tool / alpha
- “designed to pre-register and detect inconsistent backfill”
- Residual risk: full filesystem adversary can rewrite seals consistently

## What requires M1+

- “可稽核”
- “永不 backfill” as a **product guarantee**
- “tamper-evident study” without residual-risk footnote

## M2 artifacts (stubs until frozen)

- [docs/PRD.md](PRD.md) — product requirements (draft)
- [docs/THREAT_MODEL.md](THREAT_MODEL.md) — threat model (draft)
- Public API list in PRD — **not frozen until M2**
- [docs/CLAIM_POLICY.md](CLAIM_POLICY.md) — claim language policy (draft)

## M3 / M4

- M3: `.github/workflows/publish-pypi.yml` OIDC; SBOM generation; plugin allowlist file
- M4: remote sealed study / vault (out of scope until M1–M3 land)
