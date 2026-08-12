# Integrity controls (IC-01 … IC-10)

| ID | Threat | Mitigation |
|----|--------|------------|
| IC-01 | Full ledger rewrite; forged payout | Tip seal + **semantic recompute** of payouts from freeze tickets + sealed draw; `verify_study_semantic`; report refuses if broken |
| IC-02 | settle ignores content_hash | `verify_freeze_row` before settle; content_hash binds tickets + seals |
| IC-03 | draws.jsonl changed after freeze | `history_hash` + optional `outcome_hash` at freeze; settle checks |
| IC-04 | Reorder draws → look-ahead | History uses **stable order** (date, period), never file order |
| IC-05 | experiment.json edited after freeze | `experiment_hash` sealed; settle/report detect drift (null_seed, formal α, …) |
| IC-06 | claims.py unused | Reports run `scan_forbidden` / `assert_clean` before write |
| IC-07 | HTML/JSON script injection | Strategy ids HTML-escaped; chart JSON in `application/json` + unicode escapes |
| IC-08 | code_fingerprint = version only | Fingerprint hashes strategy + domain **source** |
| IC-09 | Arbitrary entry-point plugins | Plugins **off** unless `NULLBENCH_TRUST_PLUGINS=1` |
| IC-10 | Weak ingest/publish trust | Cache provenance JSONL; prefer **OIDC** PyPI publish |

## Commands

```bash
nullbench doctor --study ./my-study   # chain + semantic
```

## Residual risk

An adversary with full write access who rewrites ledger **and** tip **and**
draws **and** experiment consistently can still forge a study. Local seals
stop casual tampering and detect inconsistent edits; they are not a global
notary. Use external append-only storage / signing for high assurance.
