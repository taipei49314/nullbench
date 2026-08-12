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

```powershell
$env:TWINE_USERNAME = "__token__"
$env:TWINE_PASSWORD = "pypi-..."
python -m twine upload dist/*
```

## Optional extras

```bash
pip install "nullbench[coverage]"   # OR-Tools
pip install "nullbench[stats]"      # properscoring (+ comparecast on non-Windows)
```
