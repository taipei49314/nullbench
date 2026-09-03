# Integrity controls (IC-01 … IC-10)

**M1 gate:** `nullbench maturity --check-m1` or `pytest -m m1`.  
Product rule: without M1 green, no public「可稽核 / 永不 backfill」guarantee.

| ID | Threat | Mitigation |
|----|--------|------------|
| IC-01 | Full ledger rewrite; forged payout | Tip seal **required** when ledger has events + semantic recompute; `verify_study_semantic`; report refuses if broken |
| IC-02 | settle ignores content_hash | `verify_freeze_row` before settle; content_hash binds tickets + seals |
| IC-03 | draws.jsonl changed after freeze | `history_hash` + optional `outcome_hash` at freeze; settle checks |
| IC-04 | Reorder draws → look-ahead | History uses **stable order** (date, period), never file order |
| IC-05 | experiment.json edited after freeze | `experiment_hash` sealed and **must be non-empty**; settle/report detect drift |
| IC-06 | claims.py unused | Reports run `scan_forbidden` / `assert_clean` before write |
| IC-07 | HTML/JSON script injection | Strategy ids HTML-escaped; chart JSON in `application/json` + unicode escapes |
| IC-08 | code_fingerprint = version only | Fingerprint hashes strategy + domain **source** |
| IC-09 | Arbitrary entry-point plugins | Plugins **off** unless allowlisted or `NULLBENCH_TRUST_PLUGINS=1` |
| IC-10 | Weak ingest/publish trust | Cache provenance JSONL; OIDC publish workflow + CI SBOM |

Hardening (0.6.1+):

- **R-01:** missing tip with non-empty ledger → `verify_chain` fails
- **R-02:** empty/missing `experiment_hash` / `history_hash` / `code_fingerprint` → settle/semantic refuse

## Plugin allowlist (M3)

Trust a plugin without global `NULLBENCH_TRUST_PLUGINS=1`:

1. `NULLBENCH_PLUGIN_ALLOWLIST=/path/to/file`, or
2. `~/.config/nullbench/plugins.allowlist`

Format: one id per line (`strategy:foo`, `domain:bar`, or bare `foo`). See `examples/plugins.allowlist`.

**Not trusted:** `<study>/plugins.allowlist` (A2 can write the study tree).  
Entry-point modules are **not imported** until a trusted `get_strategy` / `get_domain` call (IC-09).

Hardening (0.8.1+):

- **R-03:** settle.draw must match `draws.jsonl`; `null_results` recomputed vs null bank
- Doctor fail-closed if vault has receipts for the experiment but tip/receipt missing
- HTTP notary requires `NULLBENCH_NOTARY_TOKEN` (Bearer); duplicate `tip_line_hash` refused

Hardening (0.9.0 — M5.1 prospective freezes):

- **R-04:** `freeze --next` refuses periods already present in `draws.jsonl`
  (replay masquerading as prospective); `outcome_hash` must stay null
- **R-05:** freeze schema v3 rows must satisfy `late ⇄ outcome_hash`
  (replay ⇒ `late=true`; prospective ⇒ `late=false`); semantic audit enforces
- **R-06:** a pending prospective freeze (draw not yet arrived) must seal
  *all* current draws; any earlier-draw change — or any new draw arriving
  before the target — fails the audit (fail-closed)
- Beyond-the-machine proof that a freeze preceded its draw still requires the
  M4 vault: notarize each prospective freeze (NORTH_STAR.md M5.4)

Hardening (M5.2 prospective settle — unreleased):

- **R-07:** settle of a prospective freeze must prove the draw entered
  `draws.jsonl` *after* the freeze. Evidence on the ledger row:
  `draw_entered_after_freeze=true`, freeze `line_hash`es,
  `known_draws_at_freeze` < `known_draws_at_settle`. Semantic audit
  recomputes this from freeze rows + current draws. Replay settles must not
  claim the opposite. In-tree only — A5 rewrite of freeze+draws+settle
  together still needs the M4 vault

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
