"""M4 vault notary — A5 rewrite after notarize must fail verify."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from nullbench.core import pipeline
from nullbench.core.hashing import sha256_hex
from nullbench.core.notary_http import post_receipt, serve_notary
from nullbench.core.seal import (
    export_bundle,
    notarize_study,
    verify_against_receipt,
    verify_study_vault,
)
from nullbench.core.vault import Vault
from nullbench.errors import VaultError

pytestmark = pytest.mark.m4


def _settled_study(tmp_path: Path) -> Path:
    root = tmp_path / "study"
    pipeline.init_study(root, experiment_id="m4", domain="demo649", demo_draws=20)
    pipeline.add_strategy(root, strategy_id="random", kind="random", tickets=2, seed=1)
    pipeline.freeze_latest(root)
    pipeline.settle_period(root)
    return root


def _rebuild_ledger(path: Path, rows: list[dict]) -> None:
    prev = "0" * 64
    rebuilt = []
    for row in rows:
        body = {k: v for k, v in row.items() if k not in ("prev_line_hash", "line_hash")}
        material = {"prev_line_hash": prev, **body}
        digest = sha256_hex(
            json.dumps(material, sort_keys=True, separators=(",", ":"), default=str)
        )
        material["line_hash"] = digest
        prev = digest
        rebuilt.append(material)
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False, default=str) for r in rebuilt) + "\n",
        encoding="utf-8",
    )
    tip = {
        "line_hash": prev if rebuilt else "0" * 64,
        "n_lines": len(rebuilt),
        "path": path.name,
    }
    path.with_suffix(path.suffix + ".tip").write_text(json.dumps(tip), encoding="utf-8")


def test_m4_export_and_notarize_verify(tmp_path: Path) -> None:
    root = _settled_study(tmp_path)
    vault = Vault(tmp_path / "vault")
    vault.init()
    out = tmp_path / "bundle"
    manifest = export_bundle(root, out)
    assert (out / "manifest.json").is_file()
    assert manifest["bundle_id"]
    receipt = notarize_study(root, vault=vault)
    ok, issues, rec = verify_study_vault(root, vault=vault)
    assert ok, issues
    assert rec and rec["receipt_id"] == receipt["receipt_id"]


def test_m4_a5_rewrite_after_notarize_fails(tmp_path: Path) -> None:
    """Consistent local rewrite after notarize must fail vault verify."""
    root = _settled_study(tmp_path)
    vault = Vault(tmp_path / "vault")
    vault.init()
    receipt = notarize_study(root, vault=vault)
    assert verify_against_receipt(root, receipt, vault=vault)[0] is True

    # A5: rewrite settle payouts + relink chain + tip
    led = root / "ledger" / "events.jsonl"
    rows = [json.loads(x) for x in led.read_text(encoding="utf-8").splitlines() if x.strip()]
    for r in rows:
        for s in r.get("strategy_results", []):
            s["payout"] = 999999.0
    _rebuild_ledger(led, rows)

    ok, issues = verify_against_receipt(root, receipt, vault=vault)
    assert ok is False
    assert any("tip_line_hash" in i or "hash drift" in i or "payout" in i for i in issues)


def test_m4_file_hash_drift_detected(tmp_path: Path) -> None:
    root = _settled_study(tmp_path)
    vault = Vault(tmp_path / "vault")
    vault.init()
    receipt = notarize_study(root, vault=vault)
    # Mutate draws without touching tip (inconsistent) — still caught by file_hashes
    draws = root / "data" / "draws.jsonl"
    draws.write_text(draws.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    ok, issues = verify_against_receipt(root, receipt, vault=vault)
    assert ok is False
    assert any("draws.jsonl" in i or "hash drift" in i or "semantic" in i.lower() or "payout" in i or "bundle" in i for i in issues)


def test_m4_http_notary_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _settled_study(tmp_path)
    vault = Vault(tmp_path / "http-vault")
    vault.init()
    token = "test-notary-token"
    monkeypatch.setenv("NULLBENCH_NOTARY_TOKEN", token)
    server, served_token = serve_notary("127.0.0.1", 0, vault=vault, token=token)
    assert served_token == token
    host, port = server.server_address[:2]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        from nullbench.core.seal import build_manifest

        manifest = build_manifest(root)
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
        receipt = post_receipt(payload, url=f"http://{host}:{port}")
        assert receipt.get("signature")
        vault.verify_signature(receipt)
        ok, issues = verify_against_receipt(root, receipt, vault=vault)
        assert ok, issues
    finally:
        server.shutdown()


def test_m4_http_notary_rejects_unauthorized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = Vault(tmp_path / "http-vault")
    vault.init()
    monkeypatch.delenv("NULLBENCH_NOTARY_TOKEN", raising=False)
    server, token = serve_notary("127.0.0.1", 0, vault=vault, token="secret")
    host, port = server.server_address[:2]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.delenv("NULLBENCH_NOTARY_TOKEN", raising=False)
        with pytest.raises(VaultError):
            post_receipt({"tip_line_hash": "abc"}, url=f"http://{host}:{port}")
        monkeypatch.setenv("NULLBENCH_NOTARY_TOKEN", token)
        # wrong tip empty still appends once authorized — use minimal payload
        receipt = post_receipt({"note": "auth-ok"}, url=f"http://{host}:{port}")
        assert receipt.get("signature")
    finally:
        server.shutdown()


def test_m4_vault_init_required(tmp_path: Path) -> None:
    root = _settled_study(tmp_path)
    vault = Vault(tmp_path / "missing")
    with pytest.raises(VaultError):
        notarize_study(root, vault=vault)
