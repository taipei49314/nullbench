# Changelog

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
