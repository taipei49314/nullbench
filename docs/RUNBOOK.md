# Operations & upgrade runbook

Maintainer playbook for shipping, verifying, and recovering nullbench.
Audience: people who own the GitHub repo / PyPI project.

## 1. Day-2 health checks

```bash
pip install -e ".[dev]"
pytest -q
pytest -m m1 -q
pytest -m m4 -q
ruff check src tests
ruff format --check src tests
mypy src/nullbench
nullbench maturity
nullbench maturity --check-m1
nullbench maturity --check-m4
```

CI enforces the same gates on every PR (`lint` + `test` + `sbom` jobs).

## 2. Trusted Publisher (PyPI) — one-time setup

OIDC publish fails with `invalid-publisher` until this is done.

1. Open https://pypi.org/manage/project/nullbench/settings/publishing/
2. **Add a new publisher** → GitHub
3. Exact fields (must match `.github/workflows/publish-pypi.yml`):

| Field | Value |
|-------|-------|
| Owner | `taipei49314` |
| Repository | `nullbench` |
| Workflow name | `publish-pypi.yml` |
| Environment name | `pypi` |

4. Save. Confirm GitHub Environment `pypi` exists on the repo (Settings → Environments).
5. Dry-run: Actions → **Publish PyPI** → Run workflow (or publish a GitHub Release).

Fallback only for bootstrap: `gh secret set PYPI_API_TOKEN --env pypi` (project-scoped, revoke after).

## 3. Release checklist (semver)

1. Update `CHANGELOG.md` + version in `pyproject.toml` and `src/nullbench/__init__.py`
2. `pytest -q && pytest -m m1 -q && pytest -m m4 -q`
3. Merge to `master` (CODEOWNERS review)
4. Tag + GitHub Release:

```bash
git tag vX.Y.Z
git push origin vX.Y.Z
gh release create vX.Y.Z --title "nullbench X.Y.Z" --notes-file CHANGELOG.md
```

5. Watch **Publish PyPI** workflow → confirm https://pypi.org/project/nullbench/
6. Verify: `pip install nullbench==X.Y.Z && nullbench version`

Do **not** force-push tags that already published to PyPI.

## 4. Upgrade path (operators)

```bash
pip install -U nullbench
nullbench doctor
nullbench maturity
```

### Study compatibility

| From → To | Action |
|-----------|--------|
| 0.5.x → 0.6+/0.7+ | Re-run `doctor --study`; tip seal required; empty experiment_hash rejected |
| 0.7 → 0.8 | Optional M4: `vault init` then `seal notarize --study …` |
| Broken tip | Restore `ledger/events.jsonl.tip` or re-export from last good backup; do not delete tip on non-empty ledger |

Public API contract: [docs/PUBLIC_API.md](PUBLIC_API.md). Breaking changes require minor/major bump.

## 5. Vault / notary ops (M4)

```bash
# init once per machine / team vault
nullbench vault init
# or: set NULLBENCH_VAULT_DIR=D:\secure\nullbench-vault

nullbench seal notarize --study ./my-study
nullbench seal verify --study ./my-study

# optional HTTP notary
nullbench vault serve --host 127.0.0.1 --port 8765
# clients: set NULLBENCH_NOTARY_URL=http://127.0.0.1:8765
```

**Backup:** copy the entire vault directory (`vault.json`, `vault.key`, `receipts.jsonl`).  
Losing `vault.key` means old signatures cannot be verified (rotate with `--force` only if intentional).

## 6. Incident playbooks

### Publish failed (`invalid-publisher`)

- Re-check Trusted Publisher fields (esp. **Environment = pypi** and workflow filename).
- Confirm release used tag on this repo, not a fork.
- Temporary: set `PYPI_API_TOKEN` env secret and re-run workflow.

### CI red (ruff / mypy / coverage)

```bash
ruff check src tests --fix
ruff format src tests
mypy src/nullbench
pytest --cov=nullbench --cov-fail-under=70
```

### Semantic / vault verify fail on a study

```bash
nullbench doctor --study ./my-study
nullbench seal verify --study ./my-study
```

If vault verify fails after a rewrite, treat as integrity incident: restore study from last notarized bundle (`seal export` output) or accept a new experiment id.

### Claim-language / marketing incident

See [CLAIM_POLICY.md](CLAIM_POLICY.md). Do not advertise absolute never-backfill without M4 vault context.

## 7. Dependency updates

Dependabot opens weekly PRs for Actions + pip.  
Merge only when CI green (`lint` + `test` + `sbom`).

## 8. Contacts

- Security: [SECURITY.md](../SECURITY.md)
- Contributing: [CONTRIBUTING.md](../CONTRIBUTING.md)
- Owner: @taipei49314 (CODEOWNERS)
