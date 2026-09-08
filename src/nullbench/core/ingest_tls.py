"""TLS helper for official-feed ingest.

Windows CPython often has no system CA store, so urllib hits
``CERTIFICATE_VERIFY_FAILED`` until ``certifi`` is installed. Doctor
reports that; ingest failures carry the same hint.
"""

from __future__ import annotations

import ssl
import sys
from typing import Any

CERTIFI_HINT = (
    "pip install certifi  — Windows CPython often has no system CA store "
    "(CERTIFICATE_VERIFY_FAILED on ingest). Then retry ingest. "
    "Confirm with: nullbench doctor"
)


def certifi_where() -> str | None:
    try:
        import certifi

        return certifi.where()
    except ImportError:
        return None


def ssl_context() -> ssl.SSLContext:
    path = certifi_where()
    if path:
        return ssl.create_default_context(cafile=path)
    return ssl.create_default_context()


def ssl_verify_failed(exc: BaseException | None) -> bool:
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if isinstance(cur, ssl.SSLCertVerificationError):
            return True
        text = str(cur)
        if "CERTIFICATE_VERIFY_FAILED" in text or "certificate verify failed" in text.lower():
            return True
        cur = cur.__cause__ or cur.__context__
    return False


def doctor_certifi_check() -> dict[str, Any]:
    path = certifi_where()
    windows = sys.platform == "win32"
    if path:
        return {
            "name": "certifi",
            "ok": True,
            "detail": path,
            "optional": not windows,
        }
    if windows:
        return {
            "name": "certifi",
            "ok": False,
            "detail": "not installed — Taiwan ingest will fail TLS; " + CERTIFI_HINT,
            "optional": False,
        }
    return {
        "name": "certifi",
        "ok": True,
        "detail": "not installed (system CAs). Windows ingest needs: pip install certifi",
        "optional": True,
    }
