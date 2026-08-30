"""Optional HTTP notary client + tiny stdlib server for M4 remote vault.

Auth: ``NULLBENCH_NOTARY_TOKEN`` (Bearer). The built-in server is loopback-only
and may auto-mint an ephemeral token; remote exposure requires external TLS.
"""

from __future__ import annotations

import json
import os
import re
import secrets
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib import error, request
from urllib.parse import urlparse
from uuid import UUID

from nullbench.core.hashing import canonical_json, content_hash
from nullbench.core.seal import BUNDLE_FILES, MANIFEST_SCHEMA
from nullbench.core.vault import RECEIPT_RESERVED_FIELDS, VAULT_SCHEMA, Vault
from nullbench.errors import VaultError

TOKEN_ENV = "NULLBENCH_NOTARY_TOKEN"
NOTARY_PAYLOAD_FIELDS = {
    "bundle_id",
    "experiment_id",
    "experiment_hash",
    "domain",
    "tip_line_hash",
    "tip_n_lines",
    "file_hashes",
    "nullbench_version",
}


class _NoRedirectHandler(request.HTTPRedirectHandler):
    """Keep bearer credentials on the explicitly configured notary origin."""

    def redirect_request(
        self,
        req: Any,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        del req, fp, code, msg, headers, newurl
        return None


def _open_notary_request(req: request.Request):
    return request.build_opener(_NoRedirectHandler()).open(req, timeout=30)


def validate_notary_payload(payload: dict[str, Any]) -> None:
    """Require one complete canonical manifest payload before signing."""
    if set(payload) != NOTARY_PAYLOAD_FIELDS:
        missing = sorted(NOTARY_PAYLOAD_FIELDS - set(payload))
        extra = sorted(set(payload) - NOTARY_PAYLOAD_FIELDS)
        raise VaultError(f"invalid notary payload fields: missing={missing} extra={extra}")
    required_text = (
        "bundle_id",
        "experiment_id",
        "experiment_hash",
        "domain",
        "tip_line_hash",
        "nullbench_version",
    )
    if any(not isinstance(payload[field], str) or not payload[field] for field in required_text):
        raise VaultError("notary payload contains an empty or non-string identity/hash field")
    for field in ("bundle_id", "experiment_hash", "tip_line_hash"):
        if re.fullmatch(r"[0-9a-f]{64}", payload[field]) is None:
            raise VaultError(f"notary payload {field} must be a SHA-256 digest")
    if type(payload["tip_n_lines"]) is not int or payload["tip_n_lines"] < 1:
        raise VaultError("notary payload tip_n_lines must be an integer >= 1")
    file_hashes = payload["file_hashes"]
    if not isinstance(file_hashes, dict) or set(file_hashes) != set(BUNDLE_FILES):
        raise VaultError("notary payload must hash every canonical sealed bundle file")
    if any(
        not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        for digest in file_hashes.values()
    ):
        raise VaultError("notary payload contains an invalid file hash")
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "nullbench_version": payload["nullbench_version"],
        "experiment_id": payload["experiment_id"],
        "experiment_hash": payload["experiment_hash"],
        "domain": payload["domain"],
        "tip_line_hash": payload["tip_line_hash"],
        "tip_n_lines": payload["tip_n_lines"],
        "file_hashes": file_hashes,
        "semantic_ok": True,
    }
    if content_hash(manifest) != payload["bundle_id"]:
        raise VaultError("notary payload bundle_id does not match its manifest evidence")


def notary_url() -> str | None:
    url = os.environ.get("NULLBENCH_NOTARY_URL", "").strip()
    return url or None


def notary_token() -> str | None:
    tok = os.environ.get(TOKEN_ENV, "").strip()
    return tok or None


def post_receipt(payload: dict[str, Any], *, url: str | None = None) -> dict[str, Any]:
    """POST notarize payload to a remote notary; returns signed receipt JSON."""
    validate_notary_payload(payload)
    endpoint = (url or notary_url() or "").rstrip("/")
    if not endpoint:
        raise VaultError(
            "NULLBENCH_NOTARY_URL not set",
            hint="set URL or use local vault notarize",
        )
    parsed_endpoint = urlparse(endpoint)
    if parsed_endpoint.scheme not in {"http", "https"} or not parsed_endpoint.hostname:
        raise VaultError("notary URL must be an absolute http(s) URL")
    if parsed_endpoint.scheme == "http" and not _is_loopback(parsed_endpoint.hostname):
        raise VaultError(
            "refusing plaintext HTTP to a non-loopback notary",
            hint="use HTTPS, or tunnel the built-in loopback server through a TLS endpoint",
        )
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json", "User-Agent": "nullbench-m4"}
    tok = notary_token()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    req = request.Request(
        endpoint + "/v1/notarize",
        data=data,
        headers=headers,
        method="POST",
    )
    try:
        with _open_notary_request(req) as resp:
            decoded = json.loads(resp.read().decode("utf-8"))
    except error.URLError as e:
        raise VaultError(f"notary request failed: {e}") from e
    except (json.JSONDecodeError, UnicodeError) as e:
        raise VaultError("notary returned unreadable JSON") from e
    if not isinstance(decoded, dict):
        raise VaultError("notary response must be a JSON object")
    _validate_notary_response(payload, decoded)
    return decoded


def _validate_notary_response(payload: dict[str, Any], receipt: dict[str, Any]) -> None:
    """Reject successful-but-wrong or legacy remote responses client-side."""
    expected_fields = NOTARY_PAYLOAD_FIELDS | RECEIPT_RESERVED_FIELDS
    if set(receipt) != expected_fields:
        raise VaultError("notary response does not contain the canonical receipt-v2 fields")
    if receipt.get("schema") != VAULT_SCHEMA:
        raise VaultError("remote notary must return a receipt-v2 response")
    echoed = {field: receipt[field] for field in NOTARY_PAYLOAD_FIELDS}
    validate_notary_payload(echoed)
    if canonical_json(echoed) != canonical_json(payload):
        raise VaultError("notary response changed one or more submitted fields")
    receipt_id = receipt.get("receipt_id")
    try:
        if not isinstance(receipt_id, str) or str(UUID(receipt_id)) != receipt_id:
            raise ValueError
    except (ValueError, AttributeError, TypeError) as exc:
        raise VaultError("notary response receipt_id is not a canonical UUID") from exc
    vault_id = receipt.get("vault_id")
    if not isinstance(vault_id, str) or re.fullmatch(r"[0-9a-f]{16}", vault_id) is None:
        raise VaultError("notary response vault_id is invalid")
    notarized_at = receipt.get("notarized_at")
    try:
        parsed_time = datetime.fromisoformat(str(notarized_at))
    except ValueError as exc:
        raise VaultError("notary response notarized_at is not ISO-8601") from exc
    if parsed_time.tzinfo is None or parsed_time.utcoffset() != UTC.utcoffset(parsed_time):
        raise VaultError("notary response notarized_at must include a UTC offset")
    signature = receipt.get("signature")
    if not isinstance(signature, str) or re.fullmatch(r"[0-9a-f]{64}", signature) is None:
        raise VaultError("notary response signature is invalid")


def _is_loopback(host: str) -> bool:
    h = (host or "").strip().lower()
    return h in ("127.0.0.1", "localhost", "::1")


def make_handler(vault: Vault, *, token: str):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:  # quieter
            return

        def _json(self, code: int, body: dict[str, Any]) -> None:
            raw = json.dumps(body).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _authorized(self) -> bool:
            auth = self.headers.get("Authorization", "")
            if auth.startswith("Bearer "):
                got = auth[7:].strip()
                return bool(got) and secrets.compare_digest(got, token)
            return False

        def do_GET(self) -> None:  # noqa: N802
            if self.path in ("/health", "/v1/health"):
                meta = json.loads(vault.meta_path.read_text(encoding="utf-8"))
                self._json(200, {"ok": True, "vault_id": meta.get("vault_id")})
                return
            self._json(404, {"ok": False, "error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/v1/notarize":
                self._json(404, {"ok": False, "error": "not found"})
                return
            if not self._authorized():
                self._json(401, {"ok": False, "error": "unauthorized"})
                return
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("body must be object")
                validate_notary_payload(payload)
                receipt = vault.append_receipt_idempotent(payload)
                self._json(200, receipt)
            except VaultError as e:
                self._json(409, {"ok": False, "error": e.message})
            except Exception as e:  # noqa: BLE001
                self._json(400, {"ok": False, "error": str(e)})

    return Handler


def serve_notary(
    host: str,
    port: int,
    *,
    vault: Vault | None = None,
    token: str | None = None,
) -> tuple[ThreadingHTTPServer, str]:
    """Start notary HTTP server. Returns (server, bearer_token)."""
    vault = vault or Vault()
    if not _is_loopback(host):
        raise VaultError(
            f"built-in notary refuses non-loopback bind {host!r}",
            hint="bind to 127.0.0.1 and expose it only through a TLS reverse proxy or tunnel",
        )
    if not vault.exists():
        vault.init()
    resolved = (token if token is not None else notary_token()) or ""
    if not resolved:
        resolved = secrets.token_urlsafe(32)
    server = ThreadingHTTPServer((host, port), make_handler(vault, token=resolved))
    return server, resolved
