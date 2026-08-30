# Maturity model

Product gate: **never claim absolute “auditable / never backfill”; describe the exact M1 or M4 trust boundary.**
**0.8+:** M0–M4 shipped in-repo. M4 resists A5 *relative to an external vault*.

**0.9.0:** v3 registration anchors separate pre-outcome evidence from backtest and legacy evidence.

| Level | Name | Status | Exit criteria |
|-------|------|--------|---------------|
| **M0** | Lab CLI / demo / PyPI | *done* | Installable CLI, demo path |
| **M1** | Sealed local study | *done* | Checklist + `pytest -m m1` |
| **M2** | Spec freeze | *frozen* | PRD + Threat Model + Public API + Claim Policy |
| **M3** | Supply chain | *done* | OIDC workflow + CI SBOM + plugin allowlist |
| **M4** | External vault notary | *done* | Vault outside study + notarize/verify + `pytest -m m4` |

## M1 checklist

- New pre-outcome freezes use schema v3 with `registration_mode=pre_outcome` and an ordered-prefix history anchor.
- Known outcomes require explicit backtest and remain descriptive-only.
- Schema-v2 rows remain verifiable as `legacy_backtest` or `legacy_unknown`; they are never upgraded into pre-registration evidence.
- Run `pytest -m m1`.

## M4 checklist

| # | Requirement | Implementation |
|---|-------------|----------------|
| M4.1 | Sealed bundle export | `nullbench seal export` |
| M4.2 | Vault outside study | `nullbench vault init` (`NULLBENCH_VAULT_DIR`) |
| M4.3 | Notarize tip | `nullbench seal notarize` |
| M4.4 | Verify vs receipt | `nullbench seal verify` (A5 rewrite fails) |
| M4.5 | HTTP notary | `nullbench vault serve` + `NULLBENCH_NOTARY_URL` |
| M4.6 | Doctor hook | optional `vault_receipt` check |
| M4.7 | Receipt-time archive | `vault/bundles/<bundle_id>` written before receipt-v2 |
| M4.8 | Append-only evolution | Exact vs ancestor status; current tail never mislabeled notarized |

```bash
nullbench maturity
nullbench maturity --check-m1
nullbench maturity --check-m4
pytest -m m4 -q
```

## M4 quick path

```bash
nullbench vault init
nullbench demo --name try1   # synthetic backtest; descriptive-only
nullbench seal notarize --study try1
nullbench seal verify --study try1
# optional remote stub
nullbench vault serve --port 8765
# NULLBENCH_NOTARY_URL=http://127.0.0.1:8765
```

This demo remains a backtest after notarization. For a pre-outcome time anchor, notarize the v3 freeze before ingesting the target result.

The built-in notary is loopback-only. Use HTTPS termination/tunneling for remote clients, retain bundle exports separately, and back up the complete vault including `bundles/`.

## Claim boundary

M4 lets you say either that the current bundle exactly matches a receipt, or that a named archived receipt-time snapshot remains an unchanged prefix of the current ledger. The second statement does **not** notarize the later tail. M4 does **not** mean the vault key/clock/archive cannot be compromised, or that a different vault cannot be forged.
