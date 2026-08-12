"""Regression tests for integrity findings IC-01 … IC-09 (M1 gate)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nullbench.core import pipeline
from nullbench.core.integrity import history_before, verify_study_semantic
from nullbench.core.models import Draw
from nullbench.core.study import Study
from nullbench.errors import IntegrityError, SettleError
from nullbench.report.html import _safe_script_json

pytestmark = pytest.mark.m1


def _study(tmp_path: Path) -> Path:
    root = tmp_path / "s"
    pipeline.init_study(root, experiment_id="ic", domain="demo649", demo_draws=30)
    pipeline.add_strategy(root, strategy_id="random", kind="random", tickets=2, seed=1)
    draws = pipeline.load_draws(root / "data" / "draws.jsonl")
    p = draws[-1].period
    pipeline.freeze_period(root, p)
    pipeline.settle_period(root, p)
    return root


def test_ic01_forged_payout_detected(tmp_path: Path) -> None:
    root = _study(tmp_path)
    led = Path(root) / "ledger" / "events.jsonl"
    lines = led.read_text(encoding="utf-8").splitlines()
    out = []
    for line in lines:
        row = json.loads(line)
        if row.get("type") == "settle":
            for r in row.get("strategy_results", []):
                r["payout"] = 999999.0
            # re-link chain so verify_chain alone might look OK if we rebuild hashes
            # For IC-01: even after rehash tip, semantic must fail
        out.append(row)
    # rebuild chain + tip properly (attacker who rewrites whole file)
    from nullbench.core.hashing import sha256_hex

    prev = "0" * 64
    rebuilt = []
    for row in out:
        body = {k: v for k, v in row.items() if k not in ("prev_line_hash", "line_hash")}
        material = {"prev_line_hash": prev, **body}
        digest = sha256_hex(
            json.dumps(material, sort_keys=True, separators=(",", ":"), default=str)
        )
        material["line_hash"] = digest
        prev = digest
        rebuilt.append(material)
    led.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False, default=str) for r in rebuilt) + "\n",
        encoding="utf-8",
    )
    tip = {
        "line_hash": rebuilt[-1]["line_hash"],
        "n_lines": len(rebuilt),
        "path": "events.jsonl",
    }
    (Path(root) / "ledger" / "events.jsonl.tip").write_text(
        json.dumps(tip), encoding="utf-8"
    )
    chain_ok, _ = Study(root).ledger().verify_chain()
    assert chain_ok  # chain alone insufficient
    sem_ok, issues = verify_study_semantic(root)
    assert sem_ok is False
    assert any("payout" in i or "IC-01" in i for i in issues)


def test_ic02_tampered_freeze_tickets_blocked(tmp_path: Path) -> None:
    root = tmp_path / "s2"
    pipeline.init_study(root, experiment_id="ic2", domain="demo649", demo_draws=20)
    pipeline.add_strategy(root, strategy_id="random", kind="random", tickets=2, seed=1)
    draws = pipeline.load_draws(root / "data" / "draws.jsonl")
    p = draws[-1].period
    pipeline.freeze_period(root, p)
    led = root / "ledger" / "events.jsonl"
    rows = [json.loads(x) for x in led.read_text(encoding="utf-8").splitlines() if x.strip()]
    for r in rows:
        if r.get("type") == "freeze":
            r["tickets"][0]["numbers"] = [1, 2, 3, 4, 5, 6]
    # rewrite without fixing content_hash
    prev = "0" * 64
    from nullbench.core.hashing import sha256_hex

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
    led.write_text("\n".join(json.dumps(r, default=str) for r in rebuilt) + "\n", encoding="utf-8")
    (root / "ledger" / "events.jsonl.tip").write_text(
        json.dumps({"line_hash": prev, "n_lines": len(rebuilt), "path": "events.jsonl"}),
        encoding="utf-8",
    )
    with pytest.raises(SettleError):
        pipeline.settle_period(root, p)


def test_ic03_draw_change_after_freeze(tmp_path: Path) -> None:
    root = tmp_path / "s3"
    pipeline.init_study(root, experiment_id="ic3", domain="demo649", demo_draws=20)
    pipeline.add_strategy(root, strategy_id="random", kind="random", tickets=2, seed=1)
    draws = pipeline.load_draws(root / "data" / "draws.jsonl")
    p = draws[-1].period
    pipeline.freeze_period(root, p)
    # rewrite last draw numbers
    path = root / "data" / "draws.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    last = json.loads(lines[-1])
    last["numbers"] = [1, 2, 3, 4, 5, 6]
    lines[-1] = json.dumps(last)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(SettleError):
        pipeline.settle_period(root, p)


def test_ic04_order_not_file_order() -> None:
    a = Draw(period="A", numbers=[1, 2, 3, 4, 5, 7], date="2020-01-01")
    b = Draw(period="B", numbers=[1, 2, 3, 4, 5, 6], date="2020-02-01")
    c = Draw(period="C", numbers=[1, 2, 3, 4, 5, 8], date="2020-03-01")
    # C first in file → naive scan would see zero history
    hist = history_before([c, b, a], "C")
    assert [d.period for d in hist] == ["A", "B"]
    assert len(hist) == 2


def test_ic05_experiment_change_after_freeze(tmp_path: Path) -> None:
    root = tmp_path / "s5"
    pipeline.init_study(root, experiment_id="ic5", domain="demo649", demo_draws=20)
    pipeline.add_strategy(root, strategy_id="random", kind="random", tickets=2, seed=1)
    draws = pipeline.load_draws(root / "data" / "draws.jsonl")
    p = draws[-1].period
    pipeline.freeze_period(root, p)
    exp = json.loads((root / "experiment.json").read_text(encoding="utf-8"))
    exp["null_seed"] = 999
    exp["formal"]["checkpoints"] = {"26": 0.99}
    (root / "experiment.json").write_text(json.dumps(exp, indent=2), encoding="utf-8")
    with pytest.raises(SettleError):
        pipeline.settle_period(root, p)


def test_ic06_claims_block_report_text() -> None:
    from nullbench.core.claims import scan_forbidden

    assert "winning numbers" in scan_forbidden("Here are the winning numbers")
    assert scan_forbidden("does not forecast outcomes") == []


def test_ic07_script_json_escape() -> None:
    evil = {"series": [{"id": "</script><script>alert(1)", "values": [1.0]}]}
    raw = _safe_script_json(evil)
    assert "<" not in raw
    assert "\\u003c" in raw


def test_ic08_code_fingerprint_changes_with_kind(tmp_path: Path) -> None:
    from nullbench.core.integrity import code_fingerprint

    a = code_fingerprint(strategy_kinds=["random"], domain_id="demo649")
    b = code_fingerprint(strategy_kinds=["frequency"], domain_id="demo649")
    assert a != b


def test_ic09_plugin_refused_without_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from nullbench.core.integrity import assert_plugins_trusted
    from nullbench.errors import IntegrityError

    monkeypatch.delenv("NULLBENCH_TRUST_PLUGINS", raising=False)
    monkeypatch.delenv("NULLBENCH_PLUGIN_ALLOWLIST", raising=False)
    with pytest.raises(IntegrityError):
        assert_plugins_trusted("evil_plugin", is_domain=False)
    monkeypatch.setenv("NULLBENCH_TRUST_PLUGINS", "1")
    assert_plugins_trusted("evil_plugin", is_domain=False)  # allowed when trusted


def test_ic09_plugin_allowlist_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from nullbench.core.integrity import assert_plugins_trusted
    from nullbench.errors import IntegrityError

    monkeypatch.delenv("NULLBENCH_TRUST_PLUGINS", raising=False)
    allow = tmp_path / "plugins.allowlist"
    allow.write_text("strategy:evil_plugin\n", encoding="utf-8")
    monkeypatch.setenv("NULLBENCH_PLUGIN_ALLOWLIST", str(allow))
    assert_plugins_trusted("evil_plugin", is_domain=False)
    with pytest.raises(IntegrityError):
        assert_plugins_trusted("other_evil", is_domain=False)

def test_tip_mismatch_on_truncation(tmp_path: Path) -> None:
    root = _study(tmp_path)
    led = root / "ledger" / "events.jsonl"
    text = led.read_text(encoding="utf-8")
    # drop last line without updating tip
    lines = [x for x in text.splitlines() if x.strip()]
    led.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    ok, msg = Study(root).ledger().verify_chain()
    assert ok is False
    assert "tip" in msg.lower() or "mismatch" in msg.lower()


def test_r01_missing_tip_fails_verify(tmp_path: Path) -> None:
    """Deleting the tip must not leave verify_chain green (R-01)."""
    root = _study(tmp_path)
    tip = root / "ledger" / "events.jsonl.tip"
    assert tip.exists()
    tip.unlink()
    ok, msg = Study(root).ledger().verify_chain()
    assert ok is False
    assert "tip" in msg.lower() and "missing" in msg.lower()


def _rebuild_ledger(path: Path, rows: list[dict]) -> None:
    from nullbench.core.hashing import sha256_hex

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


def test_r02_empty_experiment_hash_blocked(tmp_path: Path) -> None:
    """Clearing experiment_hash must not skip IC-05 drift checks (R-02)."""
    from nullbench.core.integrity import freeze_content_hash

    root = tmp_path / "r02"
    pipeline.init_study(root, experiment_id="r02", domain="demo649", demo_draws=20)
    pipeline.add_strategy(root, strategy_id="random", kind="random", tickets=2, seed=1)
    draws = pipeline.load_draws(root / "data" / "draws.jsonl")
    p = draws[-1].period
    pipeline.freeze_period(root, p)
    led = root / "ledger" / "events.jsonl"
    rows = [json.loads(x) for x in led.read_text(encoding="utf-8").splitlines() if x.strip()]
    for r in rows:
        if r.get("type") == "freeze":
            r["experiment_hash"] = ""
            if r.get("meta"):
                r["meta"]["null_seed"] = 999
            r["content_hash"] = freeze_content_hash(
                experiment_id=r["experiment_id"],
                period=r["period"],
                strategy_id=r["strategy_id"],
                tickets=r["tickets"],
                experiment_hash_="",
                history_hash_=r["history_hash"],
                code_fingerprint_=r["code_fingerprint"],
                outcome_hash=r.get("outcome_hash"),
            )
    _rebuild_ledger(led, rows)
    exp = json.loads((root / "experiment.json").read_text(encoding="utf-8"))
    exp["null_seed"] = 999
    (root / "experiment.json").write_text(json.dumps(exp, indent=2), encoding="utf-8")
    with pytest.raises(SettleError):
        pipeline.settle_period(root, p)
    sem_ok, issues = verify_study_semantic(root)
    assert sem_ok is False
    assert any("experiment_hash" in i for i in issues)