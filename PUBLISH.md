# Publishing nullbench to PyPI

Artifacts are already buildable:

```bash
pip install -e ".[dev]"
python -m build
# produces dist/nullbench-0.2.0-*.whl and .tar.gz
```

## Upload (needs your token)

1. Create an API token at https://pypi.org/manage/account/token/
2. Upload:

```bash
# Windows PowerShell
$env:TWINE_USERNAME = "__token__"
$env:TWINE_PASSWORD = "pypi-..."   # your token
python -m twine upload dist/*
```

Or TestPyPI first:

```bash
python -m twine upload --repository testpypi dist/*
pip install -i https://test.pypi.org/simple/ nullbench
```

This environment has no PyPI credentials; publish is left for you to run once.
