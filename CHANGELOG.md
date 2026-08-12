# Changelog

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
