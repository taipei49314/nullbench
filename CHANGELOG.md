# Changelog

## Unreleased

### M5.4 first public study (NORTH_STAR.md)

- Two parallel Taiwan studies (`taiwan_super` + `taiwan_lotto649`), formal
  endpoint on (α at n=26/52), first prospective freeze notarized. Public
  registry: [docs/PUBLIC_STUDY.md](docs/PUBLIC_STUDY.md)
- **`ingest --max-months` is the most recent N months**, not the first N
  from 2004/2008 (that would freeze an already-drawn period)
- Optional `certifi` CAs for Windows ingest (`CERTIFICATE_VERIFY_FAILED`)
- No package version bump, tag, or PyPI publish (estate T-63)

### M5.3 cycle command (NORTH_STAR.md)

- **`cycle_study()` / `nullbench cycle`**: one fail-closed loop —
  ingest (skipped for offline domains) → settle frozen periods that now have
  a draw → `freeze --next` → notarize → report. Undrawn pending freezes are
  skipped, not errors. Report is skipped until a settle exists
- Notarize is required when no vault exists; `--allow-unnotarized` is a
  local dry-run only
- NORTH_STAR M5.2 row marked shipped (merged as #29)
- No package version bump, tag, or PyPI publish (estate T-62)

### M5.2 prospective settle (NORTH_STAR.md)

- **Settle records timing proof on the ledger row.** A prospective freeze
  (`outcome_hash` null) can only settle after the period appears in
  `draws.jsonl` *and* the file has grown since freeze. The settle row stores
  `draw_entered_after_freeze`, the freeze `line_hash`es, and
  `known_draws_at_freeze` / `known_draws_at_settle`. Replay settles record
  the negative (`draw_entered_after_freeze=false`)
- **Settle schema v2** (new rows): semantic audit enforces the proof
  (stripping it from a prospective settle, or claiming it on a replay settle,
  fails even with a relinked chain). Legacy v1 rows stay exempt unless they
  settle a prospective freeze (fail-closed)
- Reports surface `PROSPECTIVE SETTLE: n period(s) record that the draw
  entered draws.jsonl after the freeze`
- No package version bump, tag, or PyPI publish (estate T-61)

## 0.9.0 — 2026-09-02

> **Void (2026-09-03).** Tagged and released on GitHub, never published to
> PyPI: the Publish PyPI workflow failed because the PyPI Trusted Publisher
> was not configured (estate ledger T-49). This version number will not be
> reused; the next release gets a new one. The GitHub tag and Release stay
> as a record.

### M5.1 prospective freeze — the north-star mode exists (NORTH_STAR.md)

- **`freeze_prospective()` / `nullbench freeze --next`**: freeze a period whose
  draw does not exist yet. Hard contract: the period must be absent from
  `draws.jsonl` at freeze time, `outcome_hash` stays `null`, `late` stays
  `false`, and the history seal covers **every** draw known at freeze time.
  Period id is derived from the latest draw (`P0120` → `P0121`,
  `114000041` → `114000042`) or given explicitly
- **Freeze schema v3** (new rows): semantic audit enforces
  `late ⇄ outcome_hash` consistency (replay rows must be `late=true`,
  prospective rows `late=false`). Legacy v2 rows are exempt from this check
- **Pending prospective audits**: a prospective freeze whose draw has not
  arrived yet must still seal *all* current draws — anything changing or
  arriving before the draw fails the audit (fail-closed)
- **Reports surface the metric**: `PROSPECTIVE: n/m freeze(s) happened before
  their outcomes existed` (the north-star evidence line)
- **Coach**: `next` tells you to wait for the draw (`ingest` → `settle`)
  instead of suggesting a settle that cannot run yet
- `freeze_prospective` exported from the public API (PUBLIC_API.md M5 section)
- Public API import smoke in CI now covers `freeze_prospective`

## 0.8.3 — 2026-09-02

### M5.0 honesty pass (NORTH_STAR.md stage M5 adopted)

- **Adopted `NORTH_STAR.md`:** stage M5 — the first real prospective
  experiment (freeze before the draw exists, settle after, never backfill);
  north-star metric = prospective streak ≥ 26
- **Replay freezes now labeled:** `freeze_period` sets `late=true` whenever
  the outcome already existed at freeze time (it always did for demo/ingest
  paths — previously the flag was dead and always `false`)
- **Reports say replay:** `build_report` warns when every freeze sealed a
  known outcome ("descriptive demonstration, not prospective
  pre-registration evidence"); partial-replay counts also surfaced
- Demo panel and generated `STUDY.md` state replay mode explicitly
- CLAIM_POLICY amended: "frozen before the outcome / prospective evidence"
  language forbidden until M5.1 ships; "completed a real prospective
  experiment" forbidden until M5.5 exit

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
