# Maturity model

Product gate: **without M1, do not claim absolute “auditable / never backfill”.**  
Public open-source product (0.7+): **M0–M2 done/frozen**; **M3 partial** (in-repo); **M4 later**.

| Level | Name | Status | Exit criteria |
|-------|------|--------|---------------|
| **M0** | Lab CLI / demo / PyPI | *done* | Installable CLI, demo path |
| **M1** | Sealed local study | *done* | Checklist + `pytest -m m1` |
| **M2** | Spec freeze | *frozen* | PRD + Threat Model + Public API + Claim Policy |
| **M3** | Supply chain | *partial* | OIDC workflow + CI SBOM + plugin allowlist (Trusted Publisher must be configured on PyPI) |
| **M4** | Remote sealed study / vault | *planned* | External notary / vault; resists full local rewrite |

## M1 checklist

| # | Requirement | Implementation |
|---|-------------|----------------|
| M1.1 | Seal `ExperimentSpec` | `experiment_hash` on every freeze |
| M1.2 | Pin freeze content | `content_hash` over tickets + seals |
| M1.3 | Pin history / draw | `history_hash`, `outcome_hash` when draw known |
| M1.4 | Settle forced verify | hard seals + drift checks |
| M1.5 | Recompute not trust | semantic audit |
| M1.6 | Claim lint | `scan_forbidden` before report write |
| M1.7 | Stable history order | `(date, period)` |
| M1.8 | Code bind | strategy/domain source fingerprint |
| M1.9 | Adversarial tests | `pytest -m m1` (IC + R-01/R-02) |

```bash
nullbench maturity
nullbench maturity --check-m1
pytest -m m1 -q
```

## M2 artifacts (frozen)

- [PRD.md](PRD.md)
- [THREAT_MODEL.md](THREAT_MODEL.md)
- [CLAIM_POLICY.md](CLAIM_POLICY.md)
- [PUBLIC_API.md](PUBLIC_API.md)

## M3 artifacts (partial)

- `.github/workflows/publish-pypi.yml` — OIDC Trusted Publishing
- CI SBOM artifact (`sbom.cdx.json`)
- Plugin allowlist: `NULLBENCH_PLUGIN_ALLOWLIST` / `plugins.allowlist` (see INTEGRITY.md)
- Maintainer action: configure PyPI Trusted Publisher for `taipei49314/nullbench`

## M4

Remote sealed study / vault — out of scope until M3 Trusted Publisher is live and used for releases.
