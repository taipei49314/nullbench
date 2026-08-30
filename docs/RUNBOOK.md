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
5. When a production release is approved, Actions → **Publish PyPI** → Run workflow (or publish a GitHub Release). This uploads to production PyPI; use the TestPyPI workflow or local `build` + `twine check` for a dry run.

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
| 0.8 → 0.9 | Existing freeze-v2 rows remain verifiable but are legacy/descriptive-only; use explicit `--backtest` for known outcomes |
| Broken tip | Restore `ledger/events.jsonl.tip` or re-export from last good backup; do not delete tip on non-empty ledger |

Public API contract: [docs/PUBLIC_API.md](PUBLIC_API.md). Breaking changes require minor/major bump.

### Registration-mode operations (0.9.0)

```bash
# Prospective study: P0121 must not yet exist in outcome data.
nullbench freeze P0121 --study ./prospective-study
nullbench vault init                                      # once per vault/machine
nullbench seal notarize --study ./prospective-study   # optional; before outcome
# Ingest or append the outcome once it is available.
nullbench settle --study ./prospective-study --period P0121
nullbench seal verify --study ./prospective-study
# Expected after settlement: ANCESTOR VERIFIED / CURRENT BUNDLE NOT NOTARIZED.
# Run seal notarize again only if you also want to anchor the new tail.

# Separate retrospective study: explicit and always descriptive-only.
nullbench freeze P0120 --study ./backtest-study --backtest
nullbench freeze --study ./backtest-study --latest --backtest
nullbench freeze --study ./backtest-study --last 10 --backtest
```

Do not relabel or rewrite v2 ledger rows. Rows with an old outcome hash classify as `legacy_backtest`; rows without one classify as `legacy_unknown`. Both remain formal-ineligible. Run `doctor --study` after upgrade to verify the original v2 hashes and any new v3 history anchors.

Operational failures are fail-closed:

- Known-outcome refusal: use `--backtest` for honest historical work; do not remove the outcome to bypass classification.
- Pending settlement: ingest or append the result, then settle again.
- Anchor mismatch or mixed-mode refusal: restore the committed data or start a new experiment; never edit or migrate ledger rows in place.
- Unequal declared or returned ticket counts: make every arm the same size in a new study; the shared formal/descriptive null cloud must remain equal-cost.
- Formal endpoint without a valid primary: select exactly one primary before the first freeze; nullbench will not spend α across an unspecified family.

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
# for another host, terminate HTTPS in a reverse proxy/tunnel to loopback;
# the built-in server refuses --host 0.0.0.0 and clients refuse remote plaintext HTTP.
```

**Backup:** copy the entire vault directory (`vault.json`, `vault.key`, `receipts.jsonl`, and `bundles/`). The receipt log without its content-addressed bundle archive can still verify an exact current bundle, but it cannot prove later append-only ancestry.
Losing `vault.key` means old signatures cannot be verified (rotate with `--force` only if intentional).

Receipt-v2 server fields are vault-owned and strict clients require both client and notary to be upgraded. Clients do not follow notary redirects, so configure the final HTTPS URL directly. Legacy receipt-v1 can verify an exact content snapshot with the matching key, but its id/vault/time metadata is not a trusted server clock. A remote notary signs manifest evidence only; separately retain `seal export` output if that authority needs the bundle itself.

Default verification never hides failure of the newest applicable receipt by falling back to an older archive. Investigate/restore the newest archive first; pass an explicit older receipt only when you intentionally need to verify that narrower prior snapshot.

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

If vault verify fails after a rewrite, treat it as an integrity incident: restore the study from `vault/bundles/<bundle_id>/` or a separately retained `seal export`, or accept a new experiment id. `ANCESTOR VERIFIED` is not a failure, but it says the current tail is not notarized; never present it as an exact-current receipt.

### Claim-language / marketing incident

See [CLAIM_POLICY.md](CLAIM_POLICY.md). Never advertise absolute never-backfill; describe M4 verification only relative to the named trusted receipt and vault.

## 7. Dependency updates

Dependabot opens weekly PRs for Actions + pip.  
Merge only when CI green (`lint` + `test` + `sbom`).

## 8. Contacts

- Security: [SECURITY.md](../SECURITY.md)
- Contributing: [CONTRIBUTING.md](../CONTRIBUTING.md)
- Owner: @taipei49314 (CODEOWNERS)
