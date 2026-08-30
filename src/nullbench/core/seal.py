"""M4 sealed study export + notarize/verify against an external vault."""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

from nullbench import __version__
from nullbench.core.hashing import content_hash
from nullbench.core.integrity import experiment_hash, file_sha256, verify_study_semantic
from nullbench.core.locking import study_lock
from nullbench.core.study import Study
from nullbench.core.vault import LEGACY_VAULT_SCHEMA, VAULT_SCHEMA, Vault
from nullbench.errors import IntegrityError, StudyNotFoundError, VaultError

# Relative paths included in a sealed bundle (deterministic set)
BUNDLE_FILES = (
    "experiment.json",
    "data/draws.jsonl",
    "ledger/events.jsonl",
    "ledger/events.jsonl.tip",
)
MANIFEST_SCHEMA = "nullbench.seal.manifest.v1"


def _external_vault_issue(root: Path, vault: Vault) -> str | None:
    try:
        vault.root.resolve().relative_to(root.resolve())
    except ValueError:
        return None
    return (
        f"vault must be outside the study tree: vault={vault.root} study={root}; "
        "an in-study key does not provide an external M4 boundary"
    )


def _write_receipt_copy(path: Path, receipt: dict[str, Any]) -> None:
    """Atomically replace a convenience receipt copy inside a study."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temp_path.open("w", encoding="utf-8") as fh:
            fh.write(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp_path, path)
    except OSError as exc:
        raise VaultError(f"could not write receipt copy: {path}") from exc
    finally:
        with contextlib.suppress(FileNotFoundError):
            temp_path.unlink()


def study_file_hashes(root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for rel in BUNDLE_FILES:
        p = root / rel
        if not p.is_file():
            raise VaultError(
                f"missing sealed file: {rel}",
                hint="study must have experiment, draws, ledger + tip",
            )
        hashes[rel] = file_sha256(p)
    return hashes


def load_tip(root: Path, *, allow_empty: bool = False) -> dict[str, Any]:
    tip_path = root / "ledger" / "events.jsonl.tip"
    if not tip_path.is_file():
        raise VaultError("missing ledger tip", hint="run freeze/settle or doctor")
    try:
        tip = json.loads(tip_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise VaultError("ledger tip is unreadable") from exc
    if type(tip.get("n_lines")) is not int or tip["n_lines"] < 0:
        raise VaultError("ledger tip n_lines is invalid")
    if tip["n_lines"] == 0 and not allow_empty:
        raise VaultError(
            "ledger has no events to seal",
            hint="freeze at least one period before export or notarization",
        )
    if (
        not isinstance(tip.get("line_hash"), str)
        or re.fullmatch(r"[0-9a-f]{64}", tip["line_hash"]) is None
    ):
        raise VaultError("ledger tip line_hash is invalid")
    return tip


def build_manifest(root: Path) -> dict[str, Any]:
    """Build one writer-consistent manifest; refuse failed semantic audits."""
    root = root.resolve()
    if not Study(root).exists():
        raise StudyNotFoundError(f"no study at {root}")
    with study_lock(root):
        return _build_manifest(root)


def _build_manifest(root: Path, *, allow_empty: bool = False) -> dict[str, Any]:
    study = Study(root)
    if not study.exists():
        raise StudyNotFoundError(f"no study at {root}")
    ok, issues = verify_study_semantic(root)
    if not ok:
        raise IntegrityError(
            "refuse seal export: semantic audit failed",
            hint="; ".join(issues[:5]),
        )
    chain_ok, chain_msg = study.ledger().verify_chain()
    if not chain_ok:
        raise IntegrityError(f"refuse seal export: ledger chain invalid: {chain_msg}")

    tip = load_tip(root, allow_empty=allow_empty)
    spec = study.load_experiment()
    file_hashes = study_file_hashes(root)
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "nullbench_version": __version__,
        "experiment_id": spec.experiment_id,
        "experiment_hash": experiment_hash(spec),
        "domain": spec.domain,
        "tip_line_hash": tip.get("line_hash"),
        "tip_n_lines": tip.get("n_lines"),
        "file_hashes": file_hashes,
        "semantic_ok": True,
    }
    manifest["bundle_id"] = content_hash(manifest)
    return manifest


def export_bundle(root: Path, out_dir: Path) -> dict[str, Any]:
    """Write a sealed bundle directory + manifest.json. Returns manifest."""
    root = root.resolve()
    if not Study(root).exists():
        raise StudyNotFoundError(f"no study at {root}")
    out_dir = out_dir.resolve()
    with study_lock(root):
        manifest = _build_manifest(root)
        if out_dir.exists():
            raise VaultError(f"export path exists: {out_dir}", hint="choose a new --out path")
        try:
            out_dir.mkdir(parents=True)
        except FileExistsError as exc:
            raise VaultError(
                f"export path exists: {out_dir}",
                hint="choose a new --out path",
            ) from exc
        for rel in BUNDLE_FILES:
            dest = out_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / rel, dest)
        (out_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return manifest


def notarize_study(
    root: Path,
    *,
    vault: Vault | None = None,
    write_study_copy: bool = True,
    reuse_existing: bool = True,
) -> dict[str, Any]:
    """Notarize current study tip into the vault. Returns signed receipt."""
    root = root.resolve()
    if not Study(root).exists():
        raise StudyNotFoundError(f"no study at {root}")
    vault = vault or Vault()
    external_issue = _external_vault_issue(root, vault)
    if external_issue:
        raise VaultError(external_issue)
    if not vault.exists():
        raise VaultError(
            f"no vault at {vault.root}",
            hint="run: nullbench vault init",
        )
    with study_lock(root):
        manifest = _build_manifest(root)
        vault.store_bundle(root, manifest, BUNDLE_FILES)
        payload = {
            "bundle_id": manifest["bundle_id"],
            "experiment_id": manifest["experiment_id"],
            "experiment_hash": manifest["experiment_hash"],
            "domain": manifest["domain"],
            "tip_line_hash": manifest["tip_line_hash"],
            "tip_n_lines": manifest["tip_n_lines"],
            "file_hashes": manifest["file_hashes"],
            "nullbench_version": manifest["nullbench_version"],
        }
        if reuse_existing:
            receipt = vault.append_receipt_idempotent(payload)
        else:
            receipt = vault.append_receipt(payload)
        if write_study_copy:
            try:
                _write_receipt_copy(root / "vault" / "latest_receipt.json", receipt)
            except VaultError as exc:
                raise VaultError(
                    f"vault receipt {receipt.get('receipt_id')} was committed, but its "
                    "study-local convenience copy could not be written",
                    hint="the external vault is authoritative; retry notarize safely",
                ) from exc
    return receipt


def verify_against_receipt(
    root: Path,
    receipt: dict[str, Any],
    *,
    vault: Vault | None = None,
) -> tuple[bool, list[str]]:
    """Verify an exact bundle or an archived ledger ancestor relative to a vault."""
    root = root.resolve()
    if not Study(root).exists():
        return False, [f"no study at {root}"]
    with study_lock(root):
        return _verify_against_receipt(root, receipt, vault=vault)


def _verify_against_receipt(
    root: Path,
    receipt: dict[str, Any],
    *,
    vault: Vault | None = None,
) -> tuple[bool, list[str]]:
    issues: list[str] = []
    warnings: list[str] = []
    vault = vault or Vault()
    external_issue = _external_vault_issue(root, vault)
    if external_issue:
        return False, [external_issue]
    if not isinstance(receipt, dict):
        return False, ["vault receipt must be a JSON object"]
    try:
        vault.verify_signature(receipt)
    except VaultError as exc:
        return False, [exc.message]

    receipt_schema = receipt.get("schema")
    if receipt_schema == LEGACY_VAULT_SCHEMA:
        warnings.append(
            "WARNING: legacy receipt-v1 signature/content verified, but receipt_id, "
            "vault_id, and notarized_at are client-overridable and are not treated as "
            "vault-owned metadata"
        )
    elif receipt_schema != VAULT_SCHEMA:
        issues.append(f"unsupported vault receipt schema: {receipt_schema!r}")

    try:
        receipt_manifest = _manifest_from_receipt(receipt)
    except VaultError as exc:
        issues.append(exc.message)
        return False, warnings + issues
    if content_hash(receipt_manifest) != receipt.get("bundle_id"):
        issues.append("signed bundle_id does not match receipt evidence")

    semantic_ok, semantic_issues = verify_study_semantic(root)
    if not semantic_ok:
        issues.extend(semantic_issues)

    try:
        tip = load_tip(root, allow_empty=True)
        current_hashes = study_file_hashes(root)
        spec = Study(root).load_experiment()
    except (OSError, ValueError, VaultError) as exc:
        issues.append(str(getattr(exc, "message", exc)))
        return False, warnings + issues

    current_identity = {
        "experiment_id": spec.experiment_id,
        "experiment_hash": experiment_hash(spec),
        "domain": spec.domain,
    }
    for field, value in current_identity.items():
        if value != receipt.get(field):
            issues.append(f"{field} drift vs receipt")
    if issues:
        return False, warnings + issues

    drift: list[str] = []
    if tip.get("line_hash") != receipt.get("tip_line_hash"):
        drift.append(
            f"tip_line_hash mismatch study={tip.get('line_hash')} "
            f"receipt={receipt.get('tip_line_hash')} (possible A5 rewrite)"
        )
    if tip.get("n_lines") != receipt.get("tip_n_lines"):
        drift.append(
            f"tip_n_lines mismatch study={tip.get('n_lines')} receipt={receipt.get('tip_n_lines')}"
        )
    expected_hashes = receipt_manifest["file_hashes"]
    if expected_hashes != current_hashes:
        for rel in BUNDLE_FILES:
            if expected_hashes.get(rel) != current_hashes.get(rel):
                drift.append(f"file hash drift: {rel} (possible A5 rewrite)")

    if not drift:
        return True, warnings

    if receipt_schema == VAULT_SCHEMA:
        ancestor_ok, ancestor_issues = _verify_archived_descendant(
            root,
            receipt,
            receipt_manifest,
            vault=vault,
        )
        if ancestor_ok:
            return True, warnings + ancestor_issues
        return False, warnings + drift + ancestor_issues

    drift.append(
        "legacy receipt-v1 requires an exact current bundle; it cannot establish a "
        "vault-clock boundary for later study evolution"
    )
    return False, warnings + drift


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _manifest_from_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    """Reconstruct and validate the exact manifest evidence covered by a receipt."""
    schema = receipt.get("schema")
    n_lines = receipt.get("tip_n_lines")
    minimum = 0 if schema == LEGACY_VAULT_SCHEMA else 1
    if type(n_lines) is not int or n_lines < minimum:
        raise VaultError(f"receipt tip_n_lines must be an integer >= {minimum}")
    for field in ("bundle_id", "experiment_hash", "tip_line_hash"):
        if not _is_sha256(receipt.get(field)):
            raise VaultError(f"receipt {field} is not a SHA-256 digest")
    for field in ("experiment_id", "domain", "nullbench_version"):
        if not isinstance(receipt.get(field), str) or not receipt[field]:
            raise VaultError(f"receipt {field} is missing or invalid")
    file_hashes = receipt.get("file_hashes")
    if not isinstance(file_hashes, dict) or set(file_hashes) != set(BUNDLE_FILES):
        raise VaultError(
            "receipt file_hashes must contain exactly the canonical sealed bundle files"
        )
    if any(not _is_sha256(digest) for digest in file_hashes.values()):
        raise VaultError("receipt file_hashes contain a non-SHA-256 digest")
    return {
        "schema": MANIFEST_SCHEMA,
        "nullbench_version": receipt["nullbench_version"],
        "experiment_id": receipt["experiment_id"],
        "experiment_hash": receipt["experiment_hash"],
        "domain": receipt["domain"],
        "tip_line_hash": receipt["tip_line_hash"],
        "tip_n_lines": n_lines,
        "file_hashes": file_hashes,
        "semantic_ok": True,
    }


def _verify_archived_descendant(
    root: Path,
    receipt: dict[str, Any],
    receipt_manifest: dict[str, Any],
    *,
    vault: Vault,
) -> tuple[bool, list[str]]:
    """Prove current state extends the vault's exact receipt-time snapshot."""
    try:
        archived_manifest = {**receipt_manifest, "bundle_id": receipt["bundle_id"]}
        archive = vault.verify_bundle(
            str(receipt["bundle_id"]),
            archived_manifest,
            BUNDLE_FILES,
        )
        archive_chain_ok, archive_chain_msg = Study(archive).ledger().verify_chain()
        if not archive_chain_ok:
            raise VaultError(f"notarized bundle ledger invalid: {archive_chain_msg}")
        archive_semantic_ok, archive_semantic_issues = verify_study_semantic(archive)
        if not archive_semantic_ok:
            raise VaultError(
                "notarized bundle semantic audit failed: " + "; ".join(archive_semantic_issues[:3])
            )
        archive_tip = load_tip(archive, allow_empty=True)
        if archive_tip.get("line_hash") != receipt.get("tip_line_hash") or archive_tip.get(
            "n_lines"
        ) != receipt.get("tip_n_lines"):
            raise VaultError("notarized bundle tip does not match signed receipt")
        archive_spec = Study(archive).load_experiment()
        if (
            archive_spec.experiment_id != receipt.get("experiment_id")
            or archive_spec.domain != receipt.get("domain")
            or experiment_hash(archive_spec) != receipt.get("experiment_hash")
        ):
            raise VaultError("notarized bundle experiment evidence does not match receipt")

        archived_rows = list(Study(archive).ledger())
        current_rows = list(Study(root).ledger())
        n_lines = receipt["tip_n_lines"]
        if len(archived_rows) != n_lines:
            raise VaultError("notarized bundle ledger length does not match receipt")
        if len(current_rows) <= n_lines or current_rows[:n_lines] != archived_rows:
            raise VaultError(
                "current ledger is not a strict append-only descendant of the notarized bundle"
            )
        if n_lines and current_rows[n_lines - 1].get("line_hash") != receipt.get("tip_line_hash"):
            raise VaultError("current ledger prefix does not end at the notarized tip")

        from nullbench.core.pipeline import load_draws

        archived_periods = {draw.period for draw in load_draws(Study(archive).draws_path)}
        pre_outcome = [
            row
            for row in archived_rows
            if row.get("type") == "freeze"
            and str(row.get("schema_version")) == "3"
            and row.get("registration_mode") == "pre_outcome"
        ]
        revealed = sorted(
            {str(row.get("period")) for row in pre_outcome if row.get("period") in archived_periods}
        )
        if revealed:
            raise VaultError(
                "notarized snapshot already contained pre_outcome target(s): " + ", ".join(revealed)
            )
    except (IntegrityError, OSError, ValueError, VaultError) as exc:
        return False, [f"notarized ancestor verification failed: {getattr(exc, 'message', exc)}"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        return False, [f"notarized ancestor evidence is unreadable: {exc}"]

    return (
        True,
        [
            "ANCESTOR VERIFIED: the current ledger has the notarized snapshot as an "
            "unchanged prefix; receipt-time pre_outcome targets were absent from archived "
            "draws. CURRENT BUNDLE HAS EVOLVED AND IS NOT ITSELF NOTARIZED."
        ],
    )


def verify_study_vault(
    root: Path,
    *,
    receipt_path: Path | None = None,
    vault: Vault | None = None,
) -> tuple[bool, list[str], dict[str, Any] | None]:
    """Load exact/current or prior receipt evidence and verify fail-closed."""
    root = root.resolve()
    if not Study(root).exists():
        return False, [f"no study at {root}"], None
    with study_lock(root):
        return _verify_study_vault(root, receipt_path=receipt_path, vault=vault)


def _verify_study_vault(
    root: Path,
    *,
    receipt_path: Path | None = None,
    vault: Vault | None = None,
) -> tuple[bool, list[str], dict[str, Any] | None]:
    vault = vault or Vault()
    receipt: dict[str, Any] | None = None
    local_receipt: dict[str, Any] | None = None
    experiment_id: str | None = None
    prior: list[dict[str, Any]] = []
    default_uses_newest = False
    lookup_warnings: list[str] = []
    try:
        experiment_id = Study(root).load_experiment().experiment_id
    except Exception:
        experiment_id = None

    if receipt_path is not None:
        try:
            loaded = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeError) as exc:
            return False, [f"receipt file is unreadable: {exc}"], None
        if not isinstance(loaded, dict):
            return False, ["receipt file must contain one JSON object"], None
        receipt = loaded
    else:
        try:
            current_tip = load_tip(root, allow_empty=True)
        except VaultError as e:
            return False, [e.message], None
        local = root / "vault" / "latest_receipt.json"
        if local.is_file():
            try:
                loaded = json.loads(local.read_text(encoding="utf-8"))
                if not isinstance(loaded, dict):
                    raise ValueError("receipt copy is not an object")
                local_receipt = loaded
            except (json.JSONDecodeError, OSError, UnicodeError, ValueError):
                lookup_warnings.append(
                    "WARNING: local receipt copy is unreadable; checking the external vault"
                )
        if local_receipt is not None and local_receipt.get("tip_line_hash") != current_tip.get(
            "line_hash"
        ):
            lookup_warnings.append(
                "WARNING: local receipt copy is stale; checking the external vault"
            )
        if vault.exists() and experiment_id:
            prior = vault.receipts_for_experiment(experiment_id)
        local_missing_from_log = (
            local_receipt is not None
            and local_receipt.get("experiment_id") == experiment_id
            and all(row.get("receipt_id") != local_receipt.get("receipt_id") for row in prior)
        )
        if local_missing_from_log and local_receipt is not None:
            try:
                vault.verify_signature(local_receipt)
            except VaultError:
                lookup_warnings.append(
                    "WARNING: ignored a study-local receipt with an invalid vault signature"
                )
            else:
                return (
                    False,
                    lookup_warnings
                    + [
                        "signed study-local receipt is missing from the authoritative "
                        "external receipt log (possible receipt deletion)"
                    ],
                    local_receipt,
                )
        if prior:
            # Default verification is monotonic within a vault epoch.  An exact
            # older tip must not bypass a newer receipt for the same study.
            receipt = prior[-1]
            default_uses_newest = True
        elif vault.exists():
            receipt = vault.find_by_tip(
                str(current_tip.get("line_hash")),
                experiment_id=experiment_id,
            )
        if (
            receipt is not None
            and local_receipt is not None
            and local_receipt.get("receipt_id") != receipt.get("receipt_id")
        ):
            lookup_warnings.append(
                "WARNING: ignored a study-local receipt pointer that differs from the "
                "authoritative external-vault receipt"
            )

    if receipt is None:
        return False, lookup_warnings + ["no vault receipt found for this study tip"], None

    ok, issues = _verify_against_receipt(root, receipt, vault=vault)
    if not ok and default_uses_newest:
        return (
            False,
            lookup_warnings
            + [
                f"vault has {len(prior)} current-epoch receipt(s); newest receipt "
                f"{receipt.get('receipt_id')!r} failed; "
                "refusing to downgrade silently to older receipt evidence"
            ]
            + issues[:3],
            receipt,
        )
    return ok, lookup_warnings + issues, receipt
