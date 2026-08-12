"""M4 sealed study export + notarize/verify against an external vault."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from nullbench import __version__
from nullbench.core.hashing import content_hash
from nullbench.core.integrity import experiment_hash, file_sha256, verify_study_semantic
from nullbench.core.study import Study
from nullbench.core.vault import Vault
from nullbench.errors import IntegrityError, StudyNotFoundError, VaultError

# Relative paths included in a sealed bundle (deterministic set)
BUNDLE_FILES = (
    "experiment.json",
    "data/draws.jsonl",
    "ledger/events.jsonl",
    "ledger/events.jsonl.tip",
)


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


def load_tip(root: Path) -> dict[str, Any]:
    tip_path = root / "ledger" / "events.jsonl.tip"
    if not tip_path.is_file():
        raise VaultError("missing ledger tip", hint="run freeze/settle or doctor")
    return json.loads(tip_path.read_text(encoding="utf-8"))


def build_manifest(root: Path) -> dict[str, Any]:
    """Build sealed manifest; refuse if M1 semantic audit fails."""
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

    tip = load_tip(root)
    spec = study.load_experiment()
    file_hashes = study_file_hashes(root)
    manifest = {
        "schema": "nullbench.seal.manifest.v1",
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
    manifest = build_manifest(root)
    out_dir = out_dir.resolve()
    if out_dir.exists():
        raise VaultError(f"export path exists: {out_dir}", hint="choose a new --out path")
    out_dir.mkdir(parents=True)
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
) -> dict[str, Any]:
    """Notarize current study tip into the vault. Returns signed receipt."""
    root = root.resolve()
    vault = vault or Vault()
    if not vault.exists():
        raise VaultError(
            f"no vault at {vault.root}",
            hint="run: nullbench vault init",
        )
    manifest = build_manifest(root)
    receipt = vault.append_receipt(
        {
            "bundle_id": manifest["bundle_id"],
            "experiment_id": manifest["experiment_id"],
            "experiment_hash": manifest["experiment_hash"],
            "domain": manifest["domain"],
            "tip_line_hash": manifest["tip_line_hash"],
            "tip_n_lines": manifest["tip_n_lines"],
            "file_hashes": manifest["file_hashes"],
            "nullbench_version": manifest["nullbench_version"],
        }
    )
    if write_study_copy:
        dest_dir = root / "vault"
        dest_dir.mkdir(parents=True, exist_ok=True)
        (dest_dir / "latest_receipt.json").write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return receipt


def verify_against_receipt(
    root: Path,
    receipt: dict[str, Any],
    *,
    vault: Vault | None = None,
) -> tuple[bool, list[str]]:
    """Verify study matches a vault receipt (A5 detection relative to vault)."""
    issues: list[str] = []
    root = root.resolve()
    vault = vault or Vault()
    try:
        vault.verify_signature(receipt)
    except VaultError as e:
        return False, [e.message]

    ok, sem_issues = verify_study_semantic(root)
    if not ok:
        issues.extend(sem_issues)

    try:
        tip = load_tip(root)
    except VaultError as e:
        return False, [e.message]

    if tip.get("line_hash") != receipt.get("tip_line_hash"):
        issues.append(
            f"tip_line_hash mismatch study={tip.get('line_hash')} "
            f"receipt={receipt.get('tip_line_hash')} (possible A5 rewrite)"
        )
    if tip.get("n_lines") != receipt.get("tip_n_lines"):
        issues.append(
            f"tip_n_lines mismatch study={tip.get('n_lines')} "
            f"receipt={receipt.get('tip_n_lines')}"
        )

    try:
        current = study_file_hashes(root)
    except VaultError as e:
        issues.append(e.message)
        return False, issues

    expected = receipt.get("file_hashes") or {}
    for rel, digest in expected.items():
        if current.get(rel) != digest:
            issues.append(f"file hash drift: {rel} (possible A5 rewrite)")

    # Recompute bundle id from current study and compare
    try:
        manifest = build_manifest(root)
        if manifest["bundle_id"] != receipt.get("bundle_id"):
            # tip/files already compared; still useful signal if experiment_hash drifted
            if manifest.get("experiment_hash") != receipt.get("experiment_hash"):
                issues.append("experiment_hash drift vs receipt")
            if manifest["bundle_id"] != receipt.get("bundle_id") and not any(
                "hash drift" in i or "tip_line_hash" in i for i in issues
            ):
                issues.append("bundle_id mismatch vs receipt")
    except (IntegrityError, VaultError, StudyNotFoundError) as e:
        issues.append(str(getattr(e, "message", e)))

    return (len(issues) == 0), issues


def verify_study_vault(
    root: Path,
    *,
    receipt_path: Path | None = None,
    vault: Vault | None = None,
) -> tuple[bool, list[str], dict[str, Any] | None]:
    """Load receipt (path, study copy, or vault-by-tip) and verify."""
    root = root.resolve()
    vault = vault or Vault()
    receipt: dict[str, Any] | None = None

    if receipt_path is not None:
        receipt = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    else:
        local = root / "vault" / "latest_receipt.json"
        if local.is_file():
            receipt = json.loads(local.read_text(encoding="utf-8"))
        else:
            tip = load_tip(root)
            receipt = vault.find_by_tip(str(tip.get("line_hash")))

    if receipt is None:
        return False, ["no vault receipt found for this study tip"], None

    ok, issues = verify_against_receipt(root, receipt, vault=vault)
    return ok, issues, receipt
