# Publishing nullbench

See also the full maintainer playbook: **[docs/RUNBOOK.md](docs/RUNBOOK.md)**.

## Build

```bash
pip install -e ".[dev]"
python -m build
```

Produces `dist/nullbench-<version>-*.whl` and `.tar.gz`.

## Production PyPI — Trusted Publisher (required)

OIDC is the supported path. Long-lived tokens are bootstrap-only.

### One-time PyPI configuration

1. Open: https://pypi.org/manage/project/nullbench/settings/publishing/
2. Add GitHub publisher with **exact** values:

| Field | Value |
|-------|-------|
| Owner | `taipei49314` |
| Repository name | `nullbench` |
| Workflow name | `publish-pypi.yml` |
| Environment name | `pypi` |

3. Confirm GitHub → Settings → Environments → `pypi` exists.
4. Publish a GitHub Release (or run **Publish PyPI** via `workflow_dispatch`).

If you see `invalid-publisher`, the table above does not match what PyPI has stored (most often wrong **Environment** or workflow filename).

### Fallback token (bootstrap)

```powershell
gh secret set PYPI_API_TOKEN --env pypi
# then re-run the Publish PyPI workflow
```

Or local:

```powershell
$env:TWINE_USERNAME = "__token__"
$env:TWINE_PASSWORD = "pypi-..."   # project-scoped; revoke after
python -m twine upload dist/*
```

## TestPyPI

```powershell
$env:TWINE_USERNAME = "__token__"
$env:TWINE_PASSWORD = "pypi-..."   # TestPyPI token
python -m twine upload --repository testpypi dist/*
pip install -i https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ nullbench
```

Secrets: `TEST_PYPI_API_TOKEN` (env `testpypi`). Workflow: `.github/workflows/publish-testpypi.yml`.

## SBOM

CI uploads CycloneDX `sbom.cdx.json` on every push/PR (artifact `nullbench-sbom`).

## Ingest provenance (IC-10)

Taiwan domain ingest writes `data/cache/provenance/<game>.jsonl` with SHA-256 of each raw monthly cache file.

## Optional extras

```bash
pip install "nullbench[coverage]"   # OR-Tools combinatorial coverage
pip install "nullbench[stats]"      # properscoring (+ comparecast on non-Windows)
```
