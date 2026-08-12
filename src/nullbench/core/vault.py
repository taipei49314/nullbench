"""M4 local vault — append-only notarized receipts outside the study tree.

The study directory alone cannot resist adversary A5 (consistent full rewrite).
A vault lives outside the study (default ~/.config/nullbench/vault) and stores
HMAC-signed tip receipts. Verify fails if the study tip/files diverge from the
receipt, even when local seals were rewritten consistently.
"""

from __future__ import annotations

import contextlib
import hmac
import json
import os
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from nullbench.core.hashing import canonical_json, content_hash
from nullbench.errors import VaultError

VAULT_SCHEMA = "nullbench.vault.receipt.v1"


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

    def exists(self) -> bool:
        return self.meta_path.is_file() and self.key_path.is_file()

    def init(self, *, force: bool = False) -> dict[str, Any]:
        self.root.mkdir(parents=True, exist_ok=True)
        if self.exists() and not force:
            raise VaultError(
                f"vault already exists: {self.root}",
                hint="pass --force to rotate key (invalidates old signature checks unless key kept)",
            )
        key = secrets.token_hex(32)
        vault_id = content_hash({"vault": "nullbench", "nonce": secrets.token_hex(8)})[:16]
        meta = {
            "schema": "nullbench.vault.v1",
            "vault_id": vault_id,
            "created_at": datetime.now(UTC).isoformat(),
            "alg": "HMAC-SHA256",
        }
        self.key_path.write_text(key, encoding="utf-8")
        with contextlib.suppress(OSError):
            os.chmod(self.key_path, 0o600)
        self.meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        if not self.receipts_path.exists():
            self.receipts_path.write_text("", encoding="utf-8")
        return meta

    def _require(self) -> dict[str, Any]:
        if not self.exists():
            raise VaultError(
                f"no vault at {self.root}",
                hint="run: nullbench vault init",
            )
        return json.loads(self.meta_path.read_text(encoding="utf-8"))

    def _key(self) -> bytes:
        self._require()
        return self.key_path.read_text(encoding="utf-8").strip().encode("utf-8")

    def sign(self, body: dict[str, Any]) -> str:
        material = canonical_json(body)
        return hmac.new(self._key(), material.encode("utf-8"), "sha256").hexdigest()

    def verify_signature(self, receipt: dict[str, Any]) -> None:
        sig = receipt.get("signature")
        if not sig:
            raise VaultError("receipt missing signature")
        body = {k: v for k, v in receipt.items() if k != "signature"}
        expected = self.sign(body)
        if not hmac.compare_digest(str(sig), expected):
            raise VaultError(
                "receipt signature invalid",
                hint="wrong vault key, or receipt was forged/altered",
            )

    def append_receipt(self, payload: dict[str, Any]) -> dict[str, Any]:
        meta = self._require()
        tip = payload.get("tip_line_hash")
        if tip and self.find_by_tip(str(tip)):
            raise VaultError(
                "tip already notarized",
                hint="refuse duplicate tip_line_hash (poison / replay)",
            )
        body = {
            "schema": VAULT_SCHEMA,
            "receipt_id": str(uuid4()),
            "vault_id": meta["vault_id"],
            "notarized_at": datetime.now(UTC).isoformat(),
            **payload,
        }
        # stable order for signing
        body = json.loads(canonical_json(body))
        row = {**body, "signature": self.sign(body)}
        with self.receipts_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        return row

    def iter_receipts(self) -> list[dict[str, Any]]:
        if not self.receipts_path.exists():
            return []
        out: list[dict[str, Any]] = []
        for line in self.receipts_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
        return out

    def find_by_tip(self, tip_line_hash: str) -> dict[str, Any] | None:
        matches = [r for r in self.iter_receipts() if r.get("tip_line_hash") == tip_line_hash]
        return matches[-1] if matches else None

    def find_by_bundle(self, bundle_id: str) -> dict[str, Any] | None:
        matches = [r for r in self.iter_receipts() if r.get("bundle_id") == bundle_id]
        return matches[-1] if matches else None
