# Publishing nullbench

See also the full maintainer playbook: **[docs/RUNBOOK.md](docs/RUNBOOK.md)**.

## Build

```bash
pip install -e ".[dev]"
test -z "$(git status --porcelain)" || { echo "build from a clean tracked tree"; exit 1; }
version=$(python -c "import nullbench; print(nullbench.__version__)")
build_dir="dist/$version"
test ! -e "$build_dir" || { echo "$build_dir already exists"; exit 1; }
mkdir -p "$build_dir"
python -m build --outdir "$build_dir"
test "$(find "$build_dir" -maxdepth 1 -name '*.whl' | wc -l)" -eq 1
test "$(find "$build_dir" -maxdepth 1 -name '*.tar.gz' | wc -l)" -eq 1
python -m twine check "$build_dir"/*
```

The clean-tree and empty-directory checks keep unrelated or stale artifacts out of the upload glob.

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
$version = python -c "import nullbench; print(nullbench.__version__)"
python -m twine upload "dist/$version/*"
```

## TestPyPI

```powershell
$env:TWINE_USERNAME = "__token__"
$env:TWINE_PASSWORD = "pypi-..."   # TestPyPI token
$version = python -c "import nullbench; print(nullbench.__version__)"
python -m twine upload --repository testpypi "dist/$version/*"
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
