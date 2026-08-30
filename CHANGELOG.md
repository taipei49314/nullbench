# Changelog

## 0.9.0 — 2026-08-30

### Breaking — fail-closed pre-outcome classification

- `freeze PERIOD` now fails closed unless the target outcome is absent; known outcomes require explicit `--backtest`.
- `--latest` and `--last` are backtest-only, and `demo` is labeled as a descriptive backtest tutorial.
- Freeze schema v3 binds registration mode, ordered history anchor, full-history hash, frozen time, and outcome presence.
- Settle schema v2 binds registration mode and sorted freeze content hashes.
- Existing freeze-v2 evidence remains byte-compatible and is classified as `legacy_backtest` or `legacy_unknown`; neither is formal-eligible.
- Pending pre-outcome freezes are valid and bulk settle skips them until outcomes arrive.
- Only settled v3 `pre_outcome` periods advance formal checkpoints; mixed-mode experiments are refused.
- Windows CLI output safely escapes characters unsupported by the active terminal encoding.
- `maturity --check-m1` collects the complete marked test suite, including registration attacks.
- Formal mode now requires one pre-specified primary, and freezes require equal declared/actual ticket counts across arms so the shared null bank is truly equal-cost.
- Study status runs both chain and semantic verification; relinked semantic tampering is fail-closed.
- Normal writers, seal operations, and vault receipt/key operations are serialized with crash-safe owner records and atomic receipt copies/log replacement.
- Receipt-v2 reserves vault-owned id/epoch/time fields, archives the exact bundle before signing, and verifies later study evolution only as a strict append-only descendant with an explicit unnotarized-tail label.
- Receipt-v1 exact content verification remains compatible, while its client-overridable metadata is never treated as a vault clock.
- The built-in HTTP notary is loopback-only; clients require TLS for non-loopback URLs, refuse bearer-token redirects, and validate type-exact receipt-v2 responses/server metadata.
- Verification refuses to hide a broken or rolled-back newest archive by silently downgrading to an older valid receipt. A valid signed study-local receipt missing from the current external log is treated as possible receipt deletion, even when an older receipt remains. Explicit older-receipt investigation remains available through `seal verify --receipt PATH`.

## 0.8.2 — 2026-08-12

### Engineering department gates

- CI: `ruff` + `mypy` lint job; pytest `--cov-fail-under=70`
- Dependabot (Actions + pip), `CODEOWNERS`, maintainer [RUNBOOK](docs/RUNBOOK.md)
- Trusted Publisher setup documented in PUBLISH.md / RUNBOOK (one-time PyPI UI)

## 0.8.1 — 2026-08-12

### Red-team hardening (R-03 / IC-09 / M4 UX)

- Semantic audit recomputes **null_results** and requires **settle.draw ≡ draws.jsonl**
- Doctor fail-closed when vault has experiment receipts but tip/receipt missing
- Plugins: list entry-point names without `ep.load()`; load only after trust gate
- Study-local `plugins.allowlist` no longer a trust root (env / `~/.config` only)
- HTTP notary: Bearer `NULLBENCH_NOTARY_TOKEN`; reject duplicate `tip_line_hash`

## 0.8.0 — 2026-08-12

### M4 external vault notary

- `nullbench vault init|list|serve` — HMAC vault outside the study tree
- `nullbench seal export|notarize|verify` — tip-bound bundle + A5 rewrite detection
- Optional HTTP notary (`NULLBENCH_NOTARY_URL` / `vault serve`)
- Doctor reports `vault_receipt` when a receipt is present
- `pytest -m m4` / `maturity --check-m4`
- Maturity ladder: M3/M4 marked done; CLAIM_POLICY/THREAT_MODEL amended for vault claims

## 0.7.0 — 2026-08-12

### Public open-source product

- **M2 frozen:** PRD, THREAT_MODEL, CLAIM_POLICY, PUBLIC_API
- **M3 partial:** plugin allowlist files, CI CycloneDX SBOM artifact, OIDC publish workflow (Trusted Publisher still maintainer-configured)
- OSS surface: SECURITY.md, CONTRIBUTING.md, CODE_OF_CONDUCT.md, issue/PR templates
- README rewritten for public adopters; CI badge + public API import smoke
- `build_report` exported from top-level `nullbench` package

## 0.6.1 — 2026-08-12

### Integrity hardening (R-01 / R-02)

- **R-01:** `verify_chain` fails if tip seal is missing when the ledger has events
- **R-02:** freeze seals `experiment_hash` / `history_hash` / `code_fingerprint` must be non-empty; settle no longer skips drift checks on falsy hashes
- M1 tests: `test_r01_missing_tip_fails_verify`, `test_r02_empty_experiment_hash_blocked`

## 0.6.0 — 2026-08-12

### Maturity gate (M0–M4)

- **Product gate:** no absolute「可稽核 / 永不 backfill」claims without M1 green
- `nullbench maturity` / `maturity --check-m1`
- `pytest -m m1` adversarial suite (IC-01…08) — CI enforced
- Docs: MATURITY, PRD (draft), THREAT_MODEL (draft), CLAIM_POLICY (draft)
- README / PyPI description toned to lab-alpha + M1 residual risk

### Integrity (carried from 0.5.2)

M1 checklist: experiment/freeze/draw seals, settle verify, claim lint, tip+semantic audit.

## 0.5.2 — 2026-08-12

### Security / integrity (IC-01 … IC-10)

- **IC-01/02:** settle recomputes payouts; freeze `content_hash` verified; tip seal on ledger; semantic audit
- **IC-03/04:** `history_hash` + `outcome_hash`; history ordered by (date, period) not file order
- **IC-05:** `experiment_hash` sealed at freeze (blocks null_seed / formal α edits)
- **IC-06:** claim language scan on report markdown
- **IC-07:** HTML chart JSON via `application/json` + `\u003c` escapes
- **IC-08:** code fingerprint includes strategy/domain source
- **IC-09:** entry-point plugins require `NULLBENCH_TRUST_PLUGINS=1`
- **IC-10:** cache provenance JSONL; OIDC publish workflow docs

See [docs/INTEGRITY.md](docs/INTEGRITY.md).

## 0.5.1 — 2026-08-12

### Product
- `nullbench report --open` opens `latest.html` in the default browser
- Docs: architecture/product maps formal + HTML report layers

### Release
- PyPI-ready build for 0.5.1 (upload with project-scoped token)

## 0.5.0 — 2026-08-12

### Product
- **Single-file static HTML report** (`reports/latest.html`) with embedded CSS/SVG sparkline — no SPA, no CDN
- `nullbench formal --study … --primary …` to enable alpha-spending before freezes
- `init --formal --formal-primary` flags
- Report CLI prints paths to md / html / json

### Skeleton
- **Domain entry points** group `nullbench.domains` (symmetric to `nullbench.strategies`)
- `register_domain()` for tests/notebooks
- **Formal endpoint module** (`nullbench.formal`): checkpoints **26 → α=0.005**, **52 → α=0.020**
- Two-sided empirical p vs null cum-P&L cloud; claim status `formal_endpoint` only at looks
- `ExperimentSpec.formal` / `ReportSummary.formal_endpoint`

### Docs
- This changelog; domain plugin example

## 0.4.0 — 2026-08-12

### Product
- `doctor`, `next`, `periods`
- `freeze --latest` / `--last N`
- Per-command next-step hints; auto `STUDY.md`
- `NullbenchError` hierarchy with hints

### Skeleton
- `protocols.py`, `errors.py`, `core/workspace.py`
- Domain/strategy metadata; docs ARCHITECTURE + PRODUCT

## 0.3.0 — 2026-08-12

- Taiwan domains + official API ingest
- comparecast-compatible CS / e-process (pure Python port)
- OR-Tools coverage extra
- TestPyPI + PyPI first releases (0.3.0)

## 0.2.0 — 2026-08-12

- Initial public product: freeze / null bank / ledger / demo649
- CLI golden path and library API
