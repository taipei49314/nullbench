"""M4 vault notary — A5 rewrite after notarize must fail verify."""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

import pytest
from typer.testing import CliRunner

from nullbench.cli import app
from nullbench.core import notary_http, pipeline, seal
from nullbench.core.hashing import content_hash, sha256_hex
from nullbench.core.notary_http import post_receipt, serve_notary
from nullbench.core.seal import (
    BUNDLE_FILES,
    MANIFEST_SCHEMA,
    build_manifest,
    export_bundle,
    notarize_study,
    verify_against_receipt,
    verify_study_vault,
)
from nullbench.core.study import Study
from nullbench.core.vault import LEGACY_VAULT_SCHEMA, VAULT_SCHEMA, Vault
from nullbench.core.workspace import doctor
from nullbench.errors import IntegrityError, VaultError

pytestmark = pytest.mark.m4


def _canonical_payload(label: str) -> dict:
    file_hashes = {rel: sha256_hex(f"{label}:{rel}") for rel in BUNDLE_FILES}
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "nullbench_version": "0.9.0",
        "experiment_id": f"experiment-{label}",
        "experiment_hash": sha256_hex(f"experiment:{label}"),
        "domain": "demo649",
        "tip_line_hash": sha256_hex(f"tip:{label}"),
        "tip_n_lines": 1,
        "file_hashes": file_hashes,
        "semantic_ok": True,
    }
    return {
        "bundle_id": content_hash(manifest),
        "experiment_id": manifest["experiment_id"],
        "experiment_hash": manifest["experiment_hash"],
        "domain": manifest["domain"],
        "tip_line_hash": manifest["tip_line_hash"],
        "tip_n_lines": manifest["tip_n_lines"],
        "file_hashes": file_hashes,
        "nullbench_version": manifest["nullbench_version"],
    }


def _settled_study(tmp_path: Path) -> Path:
    root = tmp_path / "study"
    pipeline.init_study(root, experiment_id="m4", domain="demo649", demo_draws=20)
    pipeline.add_strategy(root, strategy_id="random", kind="random", tickets=2, seed=1)
    pipeline.freeze_latest(root, backtest=True)
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
    assert any(
        "draws.jsonl" in i
        or "hash drift" in i
        or "semantic" in i.lower()
        or "payout" in i
        or "bundle" in i
        for i in issues
    )


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
        retried = post_receipt(payload, url=f"http://{host}:{port}")
        assert retried["receipt_id"] == receipt["receipt_id"]
        assert len(vault.iter_receipts()) == 1
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
        with pytest.raises(VaultError):
            post_receipt({"note": "incomplete"}, url=f"http://{host}:{port}")
        receipt = post_receipt(_canonical_payload("auth-ok"), url=f"http://{host}:{port}")
        assert receipt.get("signature")
    finally:
        server.shutdown()


def test_m4_vault_init_required(tmp_path: Path) -> None:
    root = _settled_study(tmp_path)
    vault = Vault(tmp_path / "missing")
    with pytest.raises(VaultError):
        notarize_study(root, vault=vault)


def test_m4_notarize_holds_one_consistent_study_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _settled_study(tmp_path)
    vault = Vault(tmp_path / "vault")
    vault.init()
    original_hashes = seal.study_file_hashes

    def attempt_normal_write(locked_root: Path) -> dict[str, str]:
        with pytest.raises(IntegrityError, match="already held"):
            pipeline.freeze_period(root, "P0019", backtest=True)
        return original_hashes(locked_root)

    monkeypatch.setattr(seal, "study_file_hashes", attempt_normal_write)
    receipt = notarize_study(root, vault=vault)

    assert verify_against_receipt(root, receipt, vault=vault)[0] is True
    assert all(row.get("period") != "P0019" for row in Study(root).ledger().events_of("freeze"))


def test_m4_vault_serializes_exact_retries_and_rejects_reserved_fields(tmp_path: Path) -> None:
    vault = Vault(tmp_path / "vault")
    vault.init()
    payload = {"tip_line_hash": "same-tip", "bundle_id": "same-bundle", "tip_n_lines": 1}

    with ThreadPoolExecutor(max_workers=8) as executor:
        receipts = list(executor.map(vault.append_receipt_idempotent, [payload] * 8))

    assert len({receipt["receipt_id"] for receipt in receipts}) == 1
    assert len(vault.iter_receipts()) == 1
    with pytest.raises(VaultError, match="different or non-retry"):
        vault.append_receipt_idempotent({**payload, "bundle_id": "conflict"})
    with pytest.raises(VaultError, match="different or non-retry"):
        vault.append_receipt_idempotent({"tip_line_hash": "same-tip"})
    with pytest.raises(VaultError, match="different or non-retry"):
        vault.append_receipt_idempotent({**payload, "unseen": None})
    with pytest.raises(VaultError, match="different or non-retry"):
        vault.append_receipt_idempotent({**payload, "tip_n_lines": True})
    with pytest.raises(VaultError, match="different or non-retry"):
        vault.append_receipt_idempotent({**payload, "tip_n_lines": 1.0})
    with pytest.raises(VaultError, match="reserved field"):
        vault.append_receipt({"tip_line_hash": "other", "notarized_at": "1900-01-01"})


def test_m4_remote_retry_reuses_local_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _settled_study(tmp_path)
    vault = Vault(tmp_path / "vault")
    vault.init()
    monkeypatch.setenv("NULLBENCH_NOTARY_URL", "https://notary.invalid")
    calls = 0

    def offline(_payload: dict, *, url: str | None = None) -> dict:
        nonlocal calls
        assert url == "https://notary.invalid"
        calls += 1
        raise VaultError("notary request failed: offline")

    monkeypatch.setattr(notary_http, "post_receipt", offline)
    args = [
        "seal",
        "notarize",
        "--study",
        str(root),
        "--vault",
        str(vault.root),
        "--remote",
    ]

    first = CliRunner().invoke(app, args)
    second = CliRunner().invoke(app, args)

    assert first.exit_code == 1
    assert second.exit_code == 1
    assert "notary request failed" in first.output
    assert "notary request failed" in second.output
    assert "local vault receipt" in first.output
    assert "was committed" in first.output
    assert "retry --remote" in first.output
    assert "tip already notarized" not in second.output
    assert calls == 2
    assert len(vault.iter_receipts()) == 1


def test_m4_rejects_in_study_vault_and_incomplete_file_evidence(tmp_path: Path) -> None:
    root = _settled_study(tmp_path)
    inside = Vault(root / "private-vault")
    inside.init()
    with pytest.raises(VaultError, match="outside the study tree"):
        notarize_study(root, vault=inside)

    external = Vault(tmp_path / "external-vault")
    external.init()
    manifest = build_manifest(root)
    partial_hashes = {"experiment.json": manifest["file_hashes"]["experiment.json"]}
    partial_manifest = {
        "schema": MANIFEST_SCHEMA,
        "nullbench_version": manifest["nullbench_version"],
        "experiment_id": manifest["experiment_id"],
        "experiment_hash": manifest["experiment_hash"],
        "domain": manifest["domain"],
        "tip_line_hash": manifest["tip_line_hash"],
        "tip_n_lines": manifest["tip_n_lines"],
        "file_hashes": partial_hashes,
        "semantic_ok": True,
    }
    receipt = external.append_receipt(
        {
            "bundle_id": content_hash(partial_manifest),
            "experiment_id": manifest["experiment_id"],
            "experiment_hash": manifest["experiment_hash"],
            "domain": manifest["domain"],
            "tip_line_hash": manifest["tip_line_hash"],
            "tip_n_lines": manifest["tip_n_lines"],
            "file_hashes": partial_hashes,
            "nullbench_version": manifest["nullbench_version"],
        }
    )
    ok, issues = verify_against_receipt(root, receipt, vault=external)
    assert ok is False
    assert any("canonical sealed bundle files" in issue for issue in issues)


def test_m4_vault_log_torn_tail_fails_closed_without_overwrite(tmp_path: Path) -> None:
    vault = Vault(tmp_path / "vault")
    vault.init()
    vault.append_receipt(_canonical_payload("first"))
    vault.receipts_path.write_text(
        vault.receipts_path.read_text(encoding="utf-8") + '{"torn":',
        encoding="utf-8",
    )
    before = vault.receipts_path.read_bytes()

    with pytest.raises(VaultError, match="malformed"):
        vault.append_receipt(_canonical_payload("second"))

    assert vault.receipts_path.read_bytes() == before


def test_m4_force_rotation_starts_new_receipt_epoch(tmp_path: Path) -> None:
    root = _settled_study(tmp_path)
    vault = Vault(tmp_path / "vault")
    first_meta = vault.init()
    first = notarize_study(root, vault=vault)

    second_meta = vault.init(force=True)
    second = notarize_study(root, vault=vault)

    assert first_meta["vault_id"] != second_meta["vault_id"]
    assert first["vault_id"] != second["vault_id"]
    assert len(vault.iter_receipts()) == 2
    assert verify_against_receipt(root, second, vault=vault)[0] is True
    assert verify_against_receipt(root, first, vault=vault)[0] is False


def test_m4_torn_local_copy_recovers_from_external_vault(tmp_path: Path) -> None:
    root = _settled_study(tmp_path)
    vault = Vault(tmp_path / "vault")
    vault.init()
    receipt = notarize_study(root, vault=vault, write_study_copy=False)
    local = root / "vault" / "latest_receipt.json"
    local.parent.mkdir(parents=True)
    local.write_text('{"partial":', encoding="utf-8")

    ok, issues, recovered = verify_study_vault(root, vault=vault)

    assert ok is True
    assert recovered and recovered["receipt_id"] == receipt["receipt_id"]
    assert any("local receipt copy is unreadable" in issue for issue in issues)
    retried = notarize_study(root, vault=vault)
    assert retried["receipt_id"] == receipt["receipt_id"]
    assert json.loads(local.read_text(encoding="utf-8"))["receipt_id"] == receipt["receipt_id"]


def test_m4_empty_ledger_cannot_be_notarized(tmp_path: Path) -> None:
    root = tmp_path / "empty-study"
    pipeline.init_study(root, experiment_id="empty", domain="demo649", demo_draws=5)
    vault = Vault(tmp_path / "vault")
    vault.init()

    with pytest.raises(VaultError, match="no events"):
        notarize_study(root, vault=vault)


def test_m4_legacy_v1_receipt_survives_upgrade_with_clock_warning(tmp_path: Path) -> None:
    root = _settled_study(tmp_path)
    vault = Vault(tmp_path / "vault")
    vault.init()
    current = build_manifest(root)
    old_manifest = {
        **{key: value for key, value in current.items() if key != "bundle_id"},
        "nullbench_version": "0.8.2",
    }
    body = {
        "schema": LEGACY_VAULT_SCHEMA,
        "receipt_id": "legacy-receipt",
        "vault_id": "client-controlled-v1-vault-id",
        "notarized_at": "2026-08-12T00:00:00+00:00",
        "bundle_id": content_hash(old_manifest),
        "experiment_id": current["experiment_id"],
        "experiment_hash": current["experiment_hash"],
        "domain": current["domain"],
        "tip_line_hash": current["tip_line_hash"],
        "tip_n_lines": current["tip_n_lines"],
        "file_hashes": current["file_hashes"],
        "nullbench_version": "0.8.2",
    }
    receipt = {**body, "signature": vault.sign(body)}

    ok, issues = verify_against_receipt(root, receipt, vault=vault)

    assert ok is True
    assert any("legacy receipt-v1" in issue for issue in issues)

    vault.receipts_path.write_text(json.dumps(receipt) + "\n", encoding="utf-8")
    auto_ok, auto_issues, auto_receipt = verify_study_vault(root, vault=vault)
    assert auto_ok is True, auto_issues
    assert auto_receipt and auto_receipt["receipt_id"] == "legacy-receipt"


def test_m4_prospective_snapshot_verifies_after_append_only_settlement(tmp_path: Path) -> None:
    root = tmp_path / "prospective"
    pipeline.init_study(root, experiment_id="prospective", domain="demo649", demo_draws=20)
    pipeline.add_strategy(root, strategy_id="random", kind="random", tickets=2, seed=1)
    pipeline.freeze_period(root, "P0021")
    vault = Vault(tmp_path / "vault")
    vault.init()
    receipt = notarize_study(root, vault=vault)

    archived = vault.bundle_path(receipt["bundle_id"])
    assert (archived / "manifest.json").is_file()
    assert all((archived / rel).is_file() for rel in BUNDLE_FILES)
    with Study(root).draws_path.open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "period": "P0021",
                    "numbers": [1, 2, 3, 4, 5, 6],
                    "special": None,
                    "date": None,
                    "meta": {"source": "prospective-test"},
                }
            )
            + "\n"
        )
    pipeline.settle_period(root, "P0021")

    ok, issues, recovered = verify_study_vault(root, vault=vault)

    assert ok is True, issues
    assert recovered and recovered["receipt_id"] == receipt["receipt_id"]
    assert any(issue.startswith("ANCESTOR VERIFIED:") for issue in issues)
    cli = CliRunner().invoke(
        app,
        ["seal", "verify", "--study", str(root), "--vault", str(vault.root)],
    )
    assert cli.exit_code == 0
    assert "ANCESTOR VERIFIED" in cli.output
    assert "CURRENT BUNDLE NOT NOTARIZED" in cli.output


def test_m4_descendant_requires_intact_archived_snapshot(tmp_path: Path) -> None:
    root = tmp_path / "prospective"
    pipeline.init_study(root, experiment_id="archive-tamper", demo_draws=3)
    pipeline.add_strategy(root, strategy_id="random", kind="random", tickets=1)
    pipeline.freeze_period(root, "P0004")
    vault = Vault(tmp_path / "vault")
    vault.init()
    receipt = notarize_study(root, vault=vault)
    with Study(root).draws_path.open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "period": "P0004",
                    "numbers": [1, 2, 3, 4, 5, 6],
                    "special": None,
                    "date": None,
                    "meta": {},
                }
            )
            + "\n"
        )
    pipeline.settle_period(root, "P0004")
    archived_draws = vault.bundle_path(receipt["bundle_id"]) / "data" / "draws.jsonl"
    archived_draws.write_text(
        archived_draws.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )

    ok, issues = verify_against_receipt(root, receipt, vault=vault)

    assert ok is False
    assert any("archive" in issue or "bundle file hash drift" in issue for issue in issues)


def test_m4_default_verify_never_hides_newest_archive_failure_by_downgrading(
    tmp_path: Path,
) -> None:
    root = tmp_path / "prospective"
    pipeline.init_study(root, experiment_id="no-downgrade", demo_draws=3)
    pipeline.add_strategy(root, strategy_id="random", kind="random", tickets=1)
    pipeline.freeze_period(root, "P0004")
    vault = Vault(tmp_path / "vault")
    vault.init()
    first = notarize_study(root, vault=vault)
    with Study(root).draws_path.open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "period": "P0004",
                    "numbers": [1, 2, 3, 4, 5, 6],
                    "special": None,
                    "date": None,
                    "meta": {},
                }
            )
            + "\n"
        )
    pipeline.settle_period(root, "P0004")
    newest = notarize_study(root, vault=vault)
    pipeline.freeze_period(root, "P0005")
    newest_experiment = vault.bundle_path(newest["bundle_id"]) / "experiment.json"
    newest_experiment.write_text(
        newest_experiment.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )

    ok, issues, chosen = verify_study_vault(root, vault=vault)

    assert ok is False
    assert chosen and chosen["receipt_id"] == newest["receipt_id"]
    assert any("refusing to downgrade" in issue for issue in issues)
    older_ok, older_issues = verify_against_receipt(root, first, vault=vault)
    assert older_ok is True, older_issues


def test_m4_default_verify_rejects_exact_tip_rollback_to_older_receipt(
    tmp_path: Path,
) -> None:
    root = tmp_path / "prospective"
    pipeline.init_study(root, experiment_id="exact-tip-rollback", demo_draws=3)
    pipeline.add_strategy(root, strategy_id="random", kind="random", tickets=1)
    pipeline.freeze_period(root, "P0004")
    vault = Vault(tmp_path / "vault")
    vault.init()
    first = notarize_study(root, vault=vault)

    with Study(root).draws_path.open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "period": "P0004",
                    "numbers": [1, 2, 3, 4, 5, 6],
                    "special": None,
                    "date": None,
                    "meta": {},
                }
            )
            + "\n"
        )
    pipeline.settle_period(root, "P0004")
    newest = notarize_study(root, vault=vault)

    first_bundle = vault.bundle_path(first["bundle_id"])
    for relative in BUNDLE_FILES:
        source = first_bundle / relative
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())

    ok, issues, chosen = verify_study_vault(root, vault=vault)

    assert ok is False
    assert chosen and chosen["receipt_id"] == newest["receipt_id"]
    assert any("refusing to downgrade" in issue for issue in issues)

    first_receipt = tmp_path / "first-receipt.json"
    first_receipt.write_text(json.dumps(first), encoding="utf-8")
    older_ok, older_issues, older = verify_study_vault(
        root,
        receipt_path=first_receipt,
        vault=vault,
    )
    assert older_ok is True, older_issues
    assert older and older["receipt_id"] == first["receipt_id"]


def test_m4_default_verify_rejects_newest_receipt_deleted_from_external_log(
    tmp_path: Path,
) -> None:
    root = tmp_path / "prospective"
    pipeline.init_study(root, experiment_id="external-log-truncation", demo_draws=3)
    pipeline.add_strategy(root, strategy_id="random", kind="random", tickets=1)
    pipeline.freeze_period(root, "P0004")
    vault = Vault(tmp_path / "vault")
    vault.init()
    first = notarize_study(root, vault=vault)

    with Study(root).draws_path.open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "period": "P0004",
                    "numbers": [1, 2, 3, 4, 5, 6],
                    "special": None,
                    "date": None,
                    "meta": {},
                }
            )
            + "\n"
        )
    pipeline.settle_period(root, "P0004")
    newest = notarize_study(root, vault=vault)

    first_bundle = vault.bundle_path(first["bundle_id"])
    for relative in BUNDLE_FILES:
        source = first_bundle / relative
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    receipt_lines = vault.receipts_path.read_text(encoding="utf-8").splitlines()
    assert len(receipt_lines) == 2
    vault.receipts_path.write_text(receipt_lines[0] + "\n", encoding="utf-8")

    ok, issues, chosen = verify_study_vault(root, vault=vault)

    assert ok is False
    assert chosen and chosen["receipt_id"] == newest["receipt_id"]
    assert any("possible receipt deletion" in issue for issue in issues)


def test_m4_default_verify_allows_stale_local_pointer_when_log_is_complete(
    tmp_path: Path,
) -> None:
    root = tmp_path / "prospective"
    pipeline.init_study(root, experiment_id="complete-log-stale-local", demo_draws=3)
    pipeline.add_strategy(root, strategy_id="random", kind="random", tickets=1)
    pipeline.freeze_period(root, "P0004")
    vault = Vault(tmp_path / "vault")
    vault.init()
    first = notarize_study(root, vault=vault)

    with Study(root).draws_path.open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "period": "P0004",
                    "numbers": [1, 2, 3, 4, 5, 6],
                    "special": None,
                    "date": None,
                    "meta": {},
                }
            )
            + "\n"
        )
    pipeline.settle_period(root, "P0004")
    newest = notarize_study(root, vault=vault, write_study_copy=False)

    ok, issues, chosen = verify_study_vault(root, vault=vault)

    assert ok is True, issues
    assert chosen and chosen["receipt_id"] == newest["receipt_id"]
    assert first["receipt_id"] != newest["receipt_id"]
    assert any("local receipt copy is stale" in issue for issue in issues)


def test_m4_rotation_does_not_report_old_epoch_receipts_as_current(tmp_path: Path) -> None:
    root = _settled_study(tmp_path)
    vault = Vault(tmp_path / "vault")
    vault.init()
    notarize_study(root, vault=vault)
    (root / "vault" / "latest_receipt.json").unlink()
    vault.init(force=True)

    ok, issues, receipt = verify_study_vault(root, vault=vault)

    assert ok is False
    assert receipt is None
    assert not any("vault has" in issue for issue in issues)


def test_m4_remote_response_and_transport_are_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = _canonical_payload("remote-response")

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps({"ok": True}).encode("utf-8")

    monkeypatch.setattr(notary_http, "_open_notary_request", lambda *_args, **_kwargs: _Response())
    with pytest.raises(VaultError, match="canonical receipt-v2"):
        post_receipt(payload, url="https://notary.example")
    with pytest.raises(VaultError, match="plaintext HTTP"):
        post_receipt(payload, url="http://notary.example")
    with pytest.raises(VaultError, match="non-loopback"):
        serve_notary("0.0.0.0", 0, vault=Vault(tmp_path / "remote-vault"), token="secret")
    with pytest.raises(VaultError, match="integer"):
        post_receipt({**payload, "tip_n_lines": True}, url="https://notary.example")


def test_m4_remote_notary_never_follows_token_bearing_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[str | None] = []

    class CaptureHandler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: object) -> None:
            return

        def do_GET(self) -> None:  # noqa: N802
            captured.append(self.headers.get("Authorization"))
            self.send_response(200)
            self.end_headers()

        do_POST = do_GET

    capture_server = ThreadingHTTPServer(("127.0.0.1", 0), CaptureHandler)
    capture_port = capture_server.server_address[1]

    class RedirectHandler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: object) -> None:
            return

        def do_POST(self) -> None:  # noqa: N802
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{capture_port}/steal")
            self.end_headers()

    redirect_server = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
    redirect_port = redirect_server.server_address[1]
    threads = [
        threading.Thread(target=capture_server.serve_forever, daemon=True),
        threading.Thread(target=redirect_server.serve_forever, daemon=True),
    ]
    for thread in threads:
        thread.start()
    monkeypatch.setenv("NULLBENCH_NOTARY_TOKEN", "must-not-leak")
    try:
        with pytest.raises(VaultError, match="notary request failed"):
            post_receipt(
                _canonical_payload("redirect"),
                url=f"http://127.0.0.1:{redirect_port}",
            )
    finally:
        redirect_server.shutdown()
        capture_server.shutdown()

    assert captured == []


def test_m4_remote_response_requires_exact_types_and_server_metadata() -> None:
    payload = _canonical_payload("strict-response")
    receipt = {
        **payload,
        "schema": VAULT_SCHEMA,
        "receipt_id": str(uuid4()),
        "vault_id": "0123456789abcdef",
        "notarized_at": "2026-08-30T00:00:00+00:00",
        "signature": "0" * 64,
    }
    notary_http._validate_notary_response(payload, receipt)

    with pytest.raises(VaultError, match="integer"):
        notary_http._validate_notary_response(payload, {**receipt, "tip_n_lines": True})
    with pytest.raises(VaultError, match="ISO-8601"):
        notary_http._validate_notary_response(payload, {**receipt, "notarized_at": "not-a-time"})
    with pytest.raises(VaultError, match="canonical UUID"):
        notary_http._validate_notary_response(payload, {**receipt, "receipt_id": "client-id"})


def test_m4_corrupt_trust_root_fails_doctor_and_invalid_receipt_is_clean_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _settled_study(tmp_path)
    vault = Vault(tmp_path / "vault")
    vault.init()
    notarize_study(root, vault=vault)
    monkeypatch.setenv("NULLBENCH_VAULT_DIR", str(vault.root))
    vault.meta_path.write_text("{", encoding="utf-8")

    result = doctor(root)

    assert result["ok"] is False
    vault_check = next(check for check in result["checks"] if check["name"] == "vault_receipt")
    assert vault_check["ok"] is False
    assert vault_check.get("optional") is not True

    malformed = tmp_path / "malformed-receipt.json"
    malformed.write_text("{", encoding="utf-8")
    ok, issues, receipt = verify_study_vault(root, receipt_path=malformed, vault=vault)
    assert ok is False
    assert receipt is None
    assert any("unreadable" in issue for issue in issues)


def test_m4_empty_or_truncated_key_cannot_sign(tmp_path: Path) -> None:
    vault = Vault(tmp_path / "vault")
    vault.init()
    vault.key_path.write_text("", encoding="utf-8")

    with pytest.raises(VaultError, match="vault key is invalid"):
        vault.append_receipt(_canonical_payload("empty-key"))
