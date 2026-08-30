# Integrity controls (IC-01 … IC-13)

**M1 gate:** `nullbench maturity --check-m1` or `pytest -m m1`.
Product rule: even with M1 green, describe only the bounded local consistency checks below; never claim an absolute「可稽核 / 永不 backfill」guarantee.

| ID | Threat | Mitigation |
|----|--------|------------|
| IC-01 | Full ledger rewrite; forged payout | Tip seal **required** when ledger has events + semantic recompute; `verify_study_semantic`; report refuses if broken |
| IC-02 | settle ignores content_hash | `verify_freeze_row` before settle; content_hash binds tickets + seals |
| IC-03 | draws.jsonl changed after freeze | Historical outcome pin when present; settle checks revealed outcome against source data |
| IC-04 | Reorder draws → look-ahead | History uses **stable order** (date, period), never file order |
| IC-05 | experiment.json edited after freeze | `experiment_hash` sealed and **must be non-empty**; settle/report detect drift |
| IC-06 | claims.py unused | Reports run `scan_forbidden` / `assert_clean` before write |
| IC-07 | HTML/JSON script injection | Strategy ids HTML-escaped; chart JSON in `application/json` + unicode escapes |
| IC-08 | code_fingerprint = version only | Fingerprint hashes strategy + domain **source** |
| IC-09 | Arbitrary entry-point plugins | Plugins **off** unless allowlisted or `NULLBENCH_TRUST_PLUGINS=1` |
| IC-10 | Weak ingest/publish trust | Cache provenance JSONL; OIDC publish workflow + CI SBOM |
| IC-11 | Retrospective work mislabeled as pre-registered | Freeze v3 binds `registration_mode`; known outcomes require explicit backtest |
| IC-12 | History inserted, truncated, or rewritten around a freeze | Freeze v3 binds an `ordered_prefix_v1` anchor plus full-contract history hash |
| IC-13 | Registration relabeled across arms or settlement | All arms share one class/anchor; settle v2 binds class plus sorted freeze hashes; mixed-mode experiments are refused |

## Freeze v3 registration anchor (0.9.0)

A new freeze is schema v3. Its content hash includes `registration_mode`, `frozen_at`, and `history_anchor` in addition to the tickets and existing seals. The anchor has this shape:

```json
{
  "algorithm": "ordered_prefix_v1",
  "count": 120,
  "through": {"date": null, "period": "P0120"}
}
```

The anchor commits to the exact ordered history prefix available at freeze time. Verification checks both the boundary and the complete Draw content, including metadata.

| Mode | Target outcome at freeze | Evidence | Claim ceiling |
|------|--------------------------|----------|---------------|
| `pre_outcome` | Absent | `outcome_hash=null`, `late=false` | May be formal-eligible if every formal gate also passes |
| `backtest` | Present | Non-null `outcome_hash`, `late=true` | Always descriptive-only |

Default `freeze PERIOD` is `pre_outcome` and refuses a known target. Historical work must use `--backtest`; `--latest` and `--last` are also rejected unless paired with `--backtest`.

Normal study writers (`init`, strategy/formal changes, ingest, freeze, settle, report, seal, and receipt-copy updates) coordinate through a per-study `.nullbench.lock`; vault key/receipt/archive operations use a separate vault lock. Owner records are fully written before acquisition is published, and failed owner writes remove their partial lock. Freeze generates its arms, then re-reads the draws, experiment, code fingerprint, and ledger while holding the study lock immediately before one batch append. A live lock is never reclaimed merely because it is old. Deliberately bypassing or deleting a lock remains part of the operator trust boundary, and `frozen_at` alone is not independent proof of real-world time.

`registration_mode` is authoritative; `late` is retained as a derived compatibility field. Settle schema v2 binds the evidence-derived class and the sorted freeze content hashes, preventing a settlement from being detached from its registration evidence.

An explicit settlement of an unrevealed target raises `OutcomePendingError`; batch settlement skips pending targets. Settlement evidence records its registration class and the contributing freeze hashes.

## Freeze v2 compatibility

Existing schema-v2 rows remain readable and verifiable with the exact v2 hash payload. nullbench does not rewrite or silently upgrade ledger history:

- v2 with a non-null outcome hash → `legacy_backtest`
- v2 without an outcome hash → `legacy_unknown`

Both legacy classes are always descriptive-only and formal-ineligible. Compatibility proves that the old row still matches its old seals; it does not prove that the row was created before the outcome.

`frozen_at` is bound into the v3 content hash so later edits are detectable, but the local clock is not an independent trust source. For evidence relative to an external time boundary, notarize the pre-outcome freeze before the result appears and trust the vault's key and clock.

Hardening (0.6.1+):

- **R-01:** missing tip with non-empty ledger → `verify_chain` fails
- **R-02:** empty/missing `experiment_hash` / `history_hash` / `code_fingerprint` → settle/semantic refuse

## Plugin allowlist (M3)

Trust a plugin without global `NULLBENCH_TRUST_PLUGINS=1`:

1. `NULLBENCH_PLUGIN_ALLOWLIST=/path/to/file`, or
2. `~/.config/nullbench/plugins.allowlist`

Format: one id per line (`strategy:foo`, `domain:bar`, or bare `foo`). Prefixes are scoped: `strategy:foo` never authorizes a domain plugin with the same name; a deliberately bare id authorizes both groups. See `examples/plugins.allowlist`.

**Not trusted:** `<study>/plugins.allowlist` (A2 can write the study tree).  
Entry-point modules are **not imported** until a trusted `get_strategy` / `get_domain` call (IC-09).

Hardening (0.8.1+):

- **R-03:** settle.draw must match `draws.jsonl`; `null_results` recomputed vs null bank
- Doctor fail-closed if vault has receipts for the experiment but tip/receipt missing
- HTTP notary requires `NULLBENCH_NOTARY_TOKEN` (Bearer); exact retries reuse the signed receipt, while conflicting duplicate tips are refused
- Formal experiments require one declared primary, and every arm must declare and actually return the same ticket count so the null comparison remains equal-cost

## Commands

```bash
nullbench doctor --study ./my-study   # chain + semantic
```

## Residual risk (without M4)

An adversary with full write access who rewrites ledger **and** tip **and**
draws **and** experiment consistently can still forge a **local-only** study.
Use M4 vault notarize/verify for A5 detection relative to an external vault.

## M4 vault notary

Commands:

```bash
nullbench vault init
nullbench seal export --study ./my-study --out ./bundle
nullbench seal notarize --study ./my-study
nullbench seal verify --study ./my-study
nullbench vault serve --port 8765   # optional HTTP notary
```

Vault default: `~/.config/nullbench/vault` (override with `NULLBENCH_VAULT_DIR`).
Receipts are HMAC-SHA256 signed; the study copy at `study/vault/latest_receipt.json`
is a convenience pointer — **trust root is the vault**, not the study tree.

Receipt schema v2 makes `receipt_id`, `vault_id`, and `notarized_at` vault-owned fields. Before the receipt is appended, local notarization stores the exact manifest and canonical files at `vault/bundles/<bundle_id>/`. Verification has two distinct success modes:

- **Exact:** the current canonical bundle hashes and tip equal the signed receipt.
- **Ancestor:** the archived bundle exactly equals the signed evidence, passes chain and semantic audit, contains no target outcome for any archived v3 `pre_outcome` freeze, and is an unchanged strict prefix of the current valid ledger. The current tail is explicitly **not** described as notarized.

Any same-tip file drift fails; ancestor mode requires at least one later ledger row. Legacy receipt-v1 remains HMAC/content-verifiable only for an exact bundle. Its receipt id, vault id, and time were client-overridable, so v1 does not establish a vault-owned clock boundary and cannot authorize descendant verification.

The built-in HTTP server binds loopback only. Put a TLS reverse proxy or secure tunnel in front of it for remote use; the client refuses plaintext non-loopback URLs, never follows redirects carrying the bearer token, and requires a type-exact receipt-v2 echo with canonical server metadata. The remote endpoint receives signed manifest evidence, not the bundle bytes, so independently retain/export the referenced snapshot. Standard `seal verify` uses the local vault key; a remote authority verifies its own receipt with its own key.

Default verification uses the newest applicable current-epoch receipt, even when the study has been restored to an older exact tip. If that archive/evidence fails, nullbench fails closed instead of silently downgrading to an older valid ancestor. It also fails closed when a correctly signed study-local receipt for this experiment is missing from the current external receipt log: an older surviving log entry cannot hide possible receipt deletion. A stale local pointer is harmless when its receipt is still present in the complete log. An operator may explicitly select an older receipt file only to investigate its narrower historical claim:

```bash
nullbench seal verify --study ./my-study --receipt ./receipts/older-receipt.json
```

Notarizing a backtest or legacy bundle protects that label and content against later drift; it does not promote the bundle to pre-registration.
