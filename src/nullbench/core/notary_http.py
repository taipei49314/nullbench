"""Optional HTTP notary client + tiny stdlib server for M4 remote vault."""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib import error, request

from nullbench.core.vault import Vault
from nullbench.errors import VaultError


def notary_url() -> str | None:
    url = os.environ.get("NULLBENCH_NOTARY_URL", "").strip()
    return url or None


def post_receipt(payload: dict[str, Any], *, url: str | None = None) -> dict[str, Any]:
    """POST notarize payload to a remote notary; returns signed receipt JSON."""
    endpoint = (url or notary_url() or "").rstrip("/")
    if not endpoint:
        raise VaultError(
            "NULLBENCH_NOTARY_URL not set",
            hint="set URL or use local vault notarize",
        )
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        endpoint + "/v1/notarize",
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "nullbench-m4"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except error.URLError as e:
        raise VaultError(f"notary request failed: {e}") from e


def make_handler(vault: Vault):
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
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("body must be object")
                receipt = vault.append_receipt(payload)
                self._json(200, receipt)
            except Exception as e:  # noqa: BLE001
                self._json(400, {"ok": False, "error": str(e)})

    return Handler


def serve_notary(host: str, port: int, *, vault: Vault | None = None) -> ThreadingHTTPServer:
    vault = vault or Vault()
    if not vault.exists():
        vault.init()
    server = ThreadingHTTPServer((host, port), make_handler(vault))
    return server
