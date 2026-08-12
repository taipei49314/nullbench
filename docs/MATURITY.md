# Maturity model

Product gate: **without M1, do not claim absolute “auditable / never backfill”.**  
**0.8+:** M0–M4 shipped in-repo. M4 resists A5 *relative to an external vault*.

| Level | Name | Status | Exit criteria |
|-------|------|--------|---------------|
| **M0** | Lab CLI / demo / PyPI | *done* | Installable CLI, demo path |
| **M1** | Sealed local study | *done* | Checklist + `pytest -m m1` |
| **M2** | Spec freeze | *frozen* | PRD + Threat Model + Public API + Claim Policy |
| **M3** | Supply chain | *done* | OIDC workflow + CI SBOM + plugin allowlist |
| **M4** | External vault notary | *done* | Vault outside study + notarize/verify + `pytest -m m4` |

## M1 checklist

See prior releases — `pytest -m m1`.

## M4 checklist

| # | Requirement | Implementation |
|---|-------------|----------------|
| M4.1 | Sealed bundle export | `nullbench seal export` |
| M4.2 | Vault outside study | `nullbench vault init` (`NULLBENCH_VAULT_DIR`) |
| M4.3 | Notarize tip | `nullbench seal notarize` |
| M4.4 | Verify vs receipt | `nullbench seal verify` (A5 rewrite fails) |
| M4.5 | HTTP notary | `nullbench vault serve` + `NULLBENCH_NOTARY_URL` |
| M4.6 | Doctor hook | optional `vault_receipt` check |

```bash
nullbench maturity
nullbench maturity --check-m1
nullbench maturity --check-m4
pytest -m m4 -q
```

## M4 quick path

```bash
nullbench vault init
nullbench demo --name try1
nullbench seal notarize --study try1
nullbench seal verify --study try1
# optional remote stub
nullbench vault serve --port 8765
# NULLBENCH_NOTARY_URL=http://127.0.0.1:8765
```

## Claim boundary

M4 lets you say the study tip was **notarized to vault X** and still matches.  
It does **not** mean the vault key cannot be stolen, or that a different vault cannot be forged.
