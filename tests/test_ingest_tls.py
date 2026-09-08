from __future__ import annotations

import ssl
from pathlib import Path

import pytest

from nullbench.core import pipeline
from nullbench.core.ingest_tls import (
    CERTIFI_HINT,
    certifi_where,
    doctor_certifi_check,
    ssl_verify_failed,
)
from nullbench.core.workspace import doctor
from nullbench.errors import DataError


def test_ssl_verify_failed_detects_cert_error() -> None:
    err = ssl.SSLCertVerificationError("certificate verify failed: CERTIFICATE_VERIFY_FAILED")
    wrapped = RuntimeError("fetch failed after 3")
    wrapped.__cause__ = err
    assert ssl_verify_failed(err) is True
    assert ssl_verify_failed(wrapped) is True
    assert ssl_verify_failed(RuntimeError("rtCode=1")) is False


def test_doctor_reports_certifi() -> None:
    info = doctor(None)
    row = next(c for c in info["checks"] if c["name"] == "certifi")
    path = certifi_where()
    if path:
        assert row["ok"] is True
        assert path in str(row["detail"])
    else:
        assert "certifi" in str(row["detail"]).lower()


def test_doctor_certifi_missing_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("nullbench.core.ingest_tls.certifi_where", lambda: None)
    monkeypatch.setattr("nullbench.core.ingest_tls.sys.platform", "win32")
    row = doctor_certifi_check()
    assert row["ok"] is False
    assert row["optional"] is False
    assert "pip install certifi" in str(row["detail"])


def test_doctor_taiwan_study_names_ingest_hint(tmp_path: Path) -> None:
    root = tmp_path / "tw"
    pipeline.init_study(root, experiment_id="tw1", domain="taiwan_super")
    info = doctor(root)
    ingest = next(c for c in info["checks"] if c["name"] == "ingest")
    assert ingest["optional"] is True
    assert "CERTIFICATE_VERIFY_FAILED" in str(ingest["detail"])
    assert "pip install certifi" in str(ingest["detail"])


def test_ingest_wraps_tls_verify_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "tw"
    pipeline.init_study(root, experiment_id="tw2", domain="taiwan_super")

    def boom(*_a, **_k):
        raise ssl.SSLCertVerificationError("CERTIFICATE_VERIFY_FAILED")

    monkeypatch.setattr(
        "nullbench.domains.taiwan_fetch._fetch_month_raw",
        boom,
    )
    with pytest.raises(DataError) as ei:
        pipeline.ingest_data(root, max_months=1)
    assert "ingest TLS failed" in ei.value.message
    assert ei.value.hint == CERTIFI_HINT


def test_ingest_other_failure_points_at_doctor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "tw"
    pipeline.init_study(root, experiment_id="tw3", domain="taiwan_super")
    monkeypatch.setattr(
        "nullbench.domains.taiwan_fetch._fetch_month_raw",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("rtCode=9")),
    )
    with pytest.raises(DataError) as ei:
        pipeline.ingest_data(root, max_months=1)
    assert "ingest failed" in ei.value.message
    assert "nullbench doctor" in (ei.value.hint or "")
