"""M4 local vault — append-only notarized receipts outside the study tree.

The study directory alone cannot resist adversary A5 (consistent full rewrite).
A vault lives outside the study (default ~/.config/nullbench/vault) and stores
HMAC-signed tip receipts plus receipt-time bundles. Verification distinguishes
an exact current bundle from a strict ledger descendant of an intact archive.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import tempfile
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from nullbench.core.hashing import canonical_json, content_hash
from nullbench.core.locking import vault_lock
from nullbench.errors import IntegrityError, VaultError

VAULT_SCHEMA = "nullbench.vault.receipt.v2"
LEGACY_VAULT_SCHEMA = "nullbench.vault.receipt.v1"
VAULT_META_SCHEMA = "nullbench.vault.v1"
RECEIPT_RESERVED_FIELDS = {
    "schema",
    "receipt_id",
    "vault_id",
    "notarized_at",
    "signature",
}


def default_vault_dir() -> Path:
    env = os.environ.get("NULLBENCH_VAULT_DIR", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return (Path.home() / ".config" / "nullbench" / "vault").resolve()


class Vault:
    """Filesystem vault with HMAC-SHA256 signed append-only receipts."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or default_vault_dir()).resolve()
        self.meta_path = self.root / "vault.json"
        self.key_path = self.root / "vault.key"
        self.receipts_path = self.root / "receipts.jsonl"
        self.bundles_dir = self.root / "bundles"

    def exists(self) -> bool:
        return self.meta_path.is_file() and self.key_path.is_file()

    def init(self, *, force: bool = False) -> dict[str, Any]:
        with self._locked():
            return self._init(force=force)

    @contextlib.contextmanager
    def _locked(self) -> Iterator[None]:
        try:
            with vault_lock(self.root):
                yield
        except IntegrityError as exc:
            raise VaultError(exc.message, hint=exc.hint) from exc

    def _init(self, *, force: bool = False) -> dict[str, Any]:
        self.root.mkdir(parents=True, exist_ok=True)
        if self.exists() and not force:
            raise VaultError(
                f"vault already exists: {self.root}",
                hint=(
                    "pass --force to start a new vault epoch; back up the old key first "
                    "if its receipts must remain verifiable"
                ),
            )
        key = secrets.token_hex(32)
        vault_id = content_hash({"vault": "nullbench", "nonce": secrets.token_hex(8)})[:16]
        meta = {
            "schema": VAULT_META_SCHEMA,
            "vault_id": vault_id,
            "created_at": datetime.now(UTC).isoformat(),
            "alg": "HMAC-SHA256",
        }
        try:
            self.key_path.write_text(key, encoding="utf-8")
            with contextlib.suppress(OSError):
                os.chmod(self.key_path, 0o600)
            self.meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
            if not self.receipts_path.exists():
                self.receipts_path.write_text("", encoding="utf-8")
        except OSError as exc:
            raise VaultError(
                "could not initialize vault files",
                hint="check filesystem permissions and restore a force-rotated vault from backup",
            ) from exc
        return meta

    def _require(self) -> dict[str, Any]:
        if not self.exists():
            raise VaultError(
                f"no vault at {self.root}",
                hint="run: nullbench vault init",
            )
        try:
            meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeError) as exc:
            raise VaultError(
                "vault metadata is unreadable",
                hint="restore vault.json and vault.key together from the same backup",
            ) from exc
        if not isinstance(meta, dict):
            raise VaultError("vault metadata must be a JSON object")
        vault_id = meta.get("vault_id")
        if (
            meta.get("schema") != VAULT_META_SCHEMA
            or meta.get("alg") != "HMAC-SHA256"
            or not isinstance(vault_id, str)
            or re.fullmatch(r"[0-9a-f]{16}", vault_id) is None
        ):
            raise VaultError(
                "vault metadata is invalid",
                hint="restore the complete vault trust root from backup",
            )
        return meta

    def _key(self) -> bytes:
        self._require()
        try:
            key = self.key_path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError) as exc:
            raise VaultError("vault key is unreadable") from exc
        if re.fullmatch(r"[0-9a-f]{64}", key) is None:
            raise VaultError(
                "vault key is invalid",
                hint="expected exactly 64 hexadecimal characters; restore it from backup",
            )
        # Preserve receipt-v1 compatibility: historic nullbench uses the
        # 64-character token_hex representation as the HMAC key material.
        return key.encode("ascii")

    def sign(self, body: dict[str, Any]) -> str:
        with self._locked():
            return self._sign(body)

    def _sign(self, body: dict[str, Any]) -> str:
        material = canonical_json(body)
        return hmac.new(self._key(), material.encode("utf-8"), "sha256").hexdigest()

    def verify_signature(self, receipt: dict[str, Any]) -> None:
        with self._locked():
            self._verify_signature(receipt)

    def _verify_signature(self, receipt: dict[str, Any]) -> None:
        meta = self._require()
        if receipt.get("schema") == VAULT_SCHEMA and receipt.get("vault_id") != meta.get(
            "vault_id"
        ):
            raise VaultError(
                "receipt belongs to a different vault epoch",
                hint="restore the matching key/metadata or use a receipt from the current epoch",
            )
        sig = receipt.get("signature")
        if not isinstance(sig, str) or re.fullmatch(r"[0-9a-f]{64}", sig) is None:
            raise VaultError("receipt missing signature")
        body = {k: v for k, v in receipt.items() if k != "signature"}
        expected = self._sign(body)
        if not hmac.compare_digest(str(sig), expected):
            raise VaultError(
                "receipt signature invalid",
                hint="wrong vault key, or receipt was forged/altered",
            )

    def append_receipt(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Append a new receipt, refusing every duplicate tip."""
        with self._locked():
            return self._append_receipt(payload, reuse_exact=False)

    def append_receipt_idempotent(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Return an existing exact receipt on retry; reject conflicting duplicates."""
        with self._locked():
            return self._append_receipt(payload, reuse_exact=True)

    def _append_receipt(
        self,
        payload: dict[str, Any],
        *,
        reuse_exact: bool,
    ) -> dict[str, Any]:
        meta = self._require()
        forbidden = sorted(RECEIPT_RESERVED_FIELDS.intersection(payload))
        if forbidden:
            raise VaultError(
                f"receipt payload contains reserved field(s): {forbidden}",
                hint="vault identity, clock, receipt id, schema, and signature are server-owned",
            )
        tip = payload.get("tip_line_hash")
        receipts = self._iter_receipts()
        matches = [
            receipt
            for receipt in receipts
            if receipt.get("tip_line_hash") == tip
            and self._receipt_in_current_epoch(receipt, str(meta.get("vault_id")))
        ]
        existing = matches[-1] if tip and matches else None
        if existing is not None:
            existing_payload = {
                key: value for key, value in existing.items() if key not in RECEIPT_RESERVED_FIELDS
            }
            if reuse_exact and canonical_json(existing_payload) == canonical_json(payload):
                self._verify_signature(existing)
                return existing
            raise VaultError(
                "tip already notarized with different or non-retry content",
                hint="refuse conflicting duplicate tip_line_hash (poison / replay)",
            )
        body = {
            **payload,
            "schema": VAULT_SCHEMA,
            "receipt_id": str(uuid4()),
            "vault_id": meta["vault_id"],
            "notarized_at": datetime.now(UTC).isoformat(),
        }
        # stable order for signing
        body = json.loads(canonical_json(body))
        row = {**body, "signature": self._sign(body)}
        serialized = json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
        temp_path = self.receipts_path.with_name(self.receipts_path.name + ".tmp")
        try:
            prior = self.receipts_path.read_text(encoding="utf-8")
            with temp_path.open("w", encoding="utf-8") as fh:
                fh.write(prior + serialized)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(temp_path, self.receipts_path)
        except (OSError, UnicodeError) as exc:
            with contextlib.suppress(OSError):
                temp_path.unlink()
            raise VaultError(
                "could not append the vault receipt atomically",
                hint="check filesystem health; the existing receipt log was not replaced",
            ) from exc
        return row

    def iter_receipts(self) -> list[dict[str, Any]]:
        with self._locked():
            return self._iter_receipts()

    def _iter_receipts(self) -> list[dict[str, Any]]:
        if not self.receipts_path.exists():
            return []
        out: list[dict[str, Any]] = []
        try:
            lines = self.receipts_path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError) as exc:
            raise VaultError("vault receipt log is unreadable") from exc
        for line_number, line in enumerate(lines, 1):
            line = line.strip()
            if line:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise VaultError(
                        f"vault receipt log is malformed at line {line_number}",
                        hint="restore the vault from backup; never discard a partial receipt",
                    ) from exc
                if not isinstance(row, dict):
                    raise VaultError(f"vault receipt line {line_number} is not an object")
                out.append(row)
        return out

    def find_by_tip(
        self,
        tip_line_hash: str,
        *,
        experiment_id: str | None = None,
    ) -> dict[str, Any] | None:
        with self._locked():
            return self._find_by_tip(tip_line_hash, experiment_id=experiment_id)

    def _find_by_tip(
        self,
        tip_line_hash: str,
        *,
        experiment_id: str | None = None,
    ) -> dict[str, Any] | None:
        vault_id = self._require().get("vault_id")
        matches = [
            receipt
            for receipt in self._iter_receipts()
            if receipt.get("tip_line_hash") == tip_line_hash
            and self._receipt_in_current_epoch(receipt, str(vault_id))
            and (experiment_id is None or receipt.get("experiment_id") == experiment_id)
        ]
        return matches[-1] if matches else None

    def find_by_bundle(self, bundle_id: str) -> dict[str, Any] | None:
        with self._locked():
            vault_id = self._require().get("vault_id")
            matches = [
                receipt
                for receipt in self._iter_receipts()
                if receipt.get("bundle_id") == bundle_id
                and self._receipt_in_current_epoch(receipt, str(vault_id))
            ]
            return matches[-1] if matches else None

    def receipts_for_experiment(self, experiment_id: str) -> list[dict[str, Any]]:
        """Return receipts for one experiment in the current vault epoch."""
        with self._locked():
            vault_id = self._require().get("vault_id")
            return [
                receipt
                for receipt in self._iter_receipts()
                if receipt.get("experiment_id") == experiment_id
                and self._receipt_in_current_epoch(receipt, str(vault_id))
            ]

    def _receipt_in_current_epoch(self, receipt: dict[str, Any], vault_id: str) -> bool:
        """Use v2 vault identity; legacy v1 can only be scoped by its signing key."""
        if receipt.get("schema") == VAULT_SCHEMA:
            return receipt.get("vault_id") == vault_id
        if receipt.get("schema") == LEGACY_VAULT_SCHEMA:
            try:
                self._verify_signature(receipt)
            except VaultError:
                return False
            return True
        return False

    def bundle_path(self, bundle_id: str) -> Path:
        """Resolve a content-addressed archive path without permitting traversal."""
        if not isinstance(bundle_id, str) or re.fullmatch(r"[0-9a-f]{64}", bundle_id) is None:
            raise VaultError("invalid bundle_id for vault archive")
        return self.bundles_dir / bundle_id

    def store_bundle(
        self,
        study_root: Path,
        manifest: dict[str, Any],
        files: tuple[str, ...],
    ) -> Path:
        """Persist an immutable receipt-time snapshot before appending its receipt."""
        with self._locked():
            self._require()
            bundle_id = manifest.get("bundle_id")
            if not isinstance(bundle_id, str):
                raise VaultError("manifest missing bundle_id")
            expected = manifest.get("file_hashes")
            if not isinstance(expected, dict) or set(expected) != set(files):
                raise VaultError("manifest file_hashes do not match canonical bundle files")
            unsigned_manifest = {
                key: value for key, value in manifest.items() if key != "bundle_id"
            }
            if content_hash(unsigned_manifest) != bundle_id:
                raise VaultError("manifest bundle_id does not match its evidence")

            destination = self.bundle_path(bundle_id)
            if destination.exists():
                self._verify_stored_bundle(destination, manifest, files)
                return destination

            self.bundles_dir.mkdir(parents=True, exist_ok=True)
            temporary = Path(
                tempfile.mkdtemp(prefix=f".{bundle_id}.", suffix=".tmp", dir=self.bundles_dir)
            )
            try:
                for rel in files:
                    source = study_root / rel
                    if not source.is_file():
                        raise VaultError(f"missing sealed file while archiving: {rel}")
                    target = temporary / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with source.open("rb") as src, target.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
                        dst.flush()
                        os.fsync(dst.fileno())
                manifest_path = temporary / "manifest.json"
                with manifest_path.open("w", encoding="utf-8") as fh:
                    fh.write(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
                    fh.flush()
                    os.fsync(fh.fileno())
                self._verify_stored_bundle(temporary, manifest, files)
                os.replace(temporary, destination)
            except VaultError:
                shutil.rmtree(temporary, ignore_errors=True)
                raise
            except OSError as exc:
                shutil.rmtree(temporary, ignore_errors=True)
                raise VaultError(
                    "could not persist the notarized bundle archive",
                    hint="check vault filesystem health and retry notarization",
                ) from exc
            except BaseException:
                shutil.rmtree(temporary, ignore_errors=True)
                raise
            return destination

    def verify_bundle(
        self,
        bundle_id: str,
        manifest: dict[str, Any],
        files: tuple[str, ...],
    ) -> Path:
        """Verify and return a receipt-time snapshot from this vault."""
        with self._locked():
            self._require()
            path = self.bundle_path(bundle_id)
            self._verify_stored_bundle(path, manifest, files)
            return path

    def _verify_stored_bundle(
        self,
        path: Path,
        manifest: dict[str, Any],
        files: tuple[str, ...],
    ) -> None:
        if not path.is_dir():
            raise VaultError(
                f"notarized bundle archive missing: {manifest.get('bundle_id')}",
                hint="restore the vault bundles directory from backup",
            )
        try:
            archived_manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeError) as exc:
            raise VaultError("notarized bundle manifest is unreadable") from exc
        if archived_manifest != manifest:
            raise VaultError("notarized bundle manifest drifted from signed receipt evidence")
        expected = manifest.get("file_hashes")
        if not isinstance(expected, dict) or set(expected) != set(files):
            raise VaultError("notarized bundle manifest has incomplete file evidence")
        for rel in files:
            candidate = path / rel
            if not candidate.is_file():
                raise VaultError(f"notarized bundle file missing: {rel}")
            digest = hashlib.sha256()
            try:
                with candidate.open("rb") as fh:
                    for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                        digest.update(chunk)
            except OSError as exc:
                raise VaultError(f"notarized bundle file unreadable: {rel}") from exc
            if digest.hexdigest() != expected.get(rel):
                raise VaultError(f"notarized bundle file hash drift: {rel}")
