# Claim policy (DRAFT — M2 freezes)

## Forbidden product claims before M1 gate green

- “可稽核” / “fully auditable” as absolute
- “永不 backfill” / “never backfill” as absolute guarantee
- “tamper-proof” (prefer “tamper-detecting for inconsistent edits”)
- Any prediction / 必中 / winning numbers language (always forbidden in reports)

## Allowed M0 language

- Lab / alpha / experimental
- Pre-register decisions; score against chance
- Detects inconsistent edits under the M1 seal model
- Residual risk footnote for full local rewrite

## Report claims

| Claim status | When |
|--------------|------|
| `descriptive_only` | Default; between formal looks |
| `formal_endpoint` | Only at α-spending checkpoints with formal enabled |

Report generator must run claim lint (`scan_forbidden`) before write (M1.6).

## Human marketing checklist

1. Run `nullbench maturity --check-m1`
2. If fail → no M1 marketing
3. If pass → may say “M1 local seals; residual risk documented in THREAT_MODEL”
4. M2 freeze required before “stable API” claims
