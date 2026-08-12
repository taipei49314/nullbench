# Publishing nullbench

## Build

```bash
pip install -e ".[dev]"
python -m build
```

Produces `dist/nullbench-<version>-*.whl` and `.tar.gz`.

## TestPyPI

```powershell
# 1) Create account + token: https://test.pypi.org/manage/account/token/
# 2) Upload
$env:TWINE_USERNAME = "__token__"
$env:TWINE_PASSWORD = "pypi-..."   # TestPyPI token
python -m twine upload --repository testpypi dist/*

# 3) Install from TestPyPI (deps still from real PyPI)
pip install -i https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ nullbench
```

This environment has **no** TestPyPI / PyPI token stored. Upload must be run on a machine
with credentials, or via GitHub Actions secrets:

- `TEST_PYPI_API_TOKEN` — for TestPyPI
- `PYPI_API_TOKEN` — for production PyPI

See `.github/workflows/publish-testpypi.yml`.

## Production PyPI

### Preferred: OIDC trusted publishing (IC-10)

Long-lived API tokens in chat/CI secrets are a weak trust chain.
Configure **Trusted Publisher** on PyPI for this repo, then use
`.github/workflows/publish-pypi.yml` (no long-lived token).

1. PyPI → Project nullbench → Publishing → Add GitHub publisher  
2. owner=`taipei49314`, repo=`nullbench`, workflow=`publish-pypi.yml`  
3. Create a GitHub Release → workflow uploads with OIDC  

### Fallback: API token (short-lived, project-scoped, revoke after use)

```powershell
$env:TWINE_USERNAME = "__token__"
$env:TWINE_PASSWORD = "pypi-..."
python -m twine upload dist/*
```

### Ingest provenance (IC-10)

Taiwan domain ingest writes `data/cache/provenance/<game>.jsonl` with
SHA-256 of each raw monthly cache file. Past months are treated as immutable
caches; provenance lets you detect silent cache rewrites.

## Optional extras

```bash
pip install "nullbench[coverage]"   # OR-Tools
pip install "nullbench[stats]"      # properscoring (+ comparecast on non-Windows)
```
