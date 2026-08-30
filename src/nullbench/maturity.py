"""Maturity ladder M0–M4 and product gates."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

LEVELS = (
    ("M0", "Lab CLI / demo / PyPI", "done"),
    ("M1", "Sealed local study (must-pass gate)", "done"),
    ("M2", "PRD + Threat Model + Public API + Claim Policy frozen", "frozen"),
    ("M3", "Trusted Publishing / SBOM / plugin allowlist", "done"),
    ("M4", "External vault notary (A5 control)", "done"),
)

M1_CHECKLIST = (
    ("M1.1", "Seal ExperimentSpec (experiment_hash)"),
    ("M1.2", "Pin freeze content_hash (tickets + seals)"),
    ("M1.3", "Pin history_hash / outcome_hash"),
    ("M1.4", "Settle forced verification"),
    ("M1.5", "Semantic payout recompute (IC-01)"),
    ("M1.6", "Claim lint on reports"),
    ("M1.7", "Stable history order (date, period)"),
    ("M1.8", "Code fingerprint includes sources"),
    ("M1.9", "Adversarial tests IC-01..08 + R-01/R-02 (pytest -m m1)"),
    ("M1.10", "Known outcomes require explicit backtest classification (IC-11)"),
    ("M1.11", "Freeze-v3 ordered-prefix history anchors (IC-12)"),
    ("M1.12", "Settle-v2 binds registration mode + freeze hashes (IC-13)"),
    ("M1.13", "Only v3 pre-outcome settlements are formal-eligible"),
)

M4_CHECKLIST = (
    ("M4.1", "Sealed bundle export (manifest + tip-bound files)"),
    ("M4.2", "Vault outside study (HMAC key + append-only receipts)"),
    ("M4.3", "Notarize study tip into vault"),
    ("M4.4", "Verify study against receipt (A5 rewrite fails)"),
    ("M4.5", "Optional HTTP notary serve/client"),
    ("M4.6", "Doctor reports vault_receipt when present"),
    ("M4.7", "Archive exact receipt-time bundle before signing receipt-v2"),
    ("M4.8", "Verify strict ledger descendants without notarizing their current tail"),
)

PRODUCT_GATE = (
    "Never claim absolute 'auditable' / 'never backfill'; state the exact M1/M4 boundary. "
    "Pre-outcome classification is relative to the study data present at freeze time. "
    "M4 vault verify enables notarized claims relative to that vault only "
    "(compromised vault key is out of scope). See CLAIM_POLICY.md."
)


@dataclass
class MaturityStatus:
    levels: list[dict]
    m1_checklist: list[dict]
    m4_checklist: list[dict]
    m1_tests_ok: bool | None
    product_gate: str
    allowed_claims: list[str]
    forbidden_until_m1: list[str]


def describe() -> MaturityStatus:
    return MaturityStatus(
        levels=[
            {
                "id": i,
                "name": n,
                "role": r,
                "note": {
                    "done": "Shipped",
                    "frozen": "Normative docs frozen at M2",
                    "partial": "In-repo controls shipped; maintainer action may remain",
                    "planned": "Not started as exit criteria",
                }.get(r, r),
            }
            for i, n, r in LEVELS
        ],
        m1_checklist=[{"id": i, "item": t} for i, t in M1_CHECKLIST],
        m4_checklist=[{"id": i, "item": t} for i, t in M4_CHECKLIST],
        m1_tests_ok=None,
        product_gate=PRODUCT_GATE,
        allowed_claims=[
            "Open-source null-first decision lab",
            "M1 local seals (inconsistent-edit detection)",
            "Freeze-v3 pre-outcome enforcement relative to current study data",
            "M2 frozen PRD / threat model / public API / claim policy",
            "M3: OIDC publish workflow + CI SBOM + plugin allowlist",
            "M4: external vault receipt-time archive; exact or bounded ancestor verification",
        ],
        forbidden_until_m1=[
            "可稽核 as absolute guarantee without vault+verify context",
            "永不 backfill as absolute guarantee without vault",
            "tamper-proof",
            "prediction / winning numbers (always forbidden in reports)",
        ],
    )


def _repo_tests_dir() -> Path | None:
    candidates = [
        Path.cwd() / "tests",
        Path(__file__).resolve().parents[2] / "tests",
    ]
    return next((p for p in candidates if p.is_dir()), None)


def run_m1_gate(*, verbose: bool = False) -> tuple[bool, str]:
    """Run adversarial M1 suite. Returns (ok, log_tail)."""
    test_dir = _repo_tests_dir()
    if test_dir is None:
        return False, "tests/ directory not found (install from source to run M1 gate)"

    cmd = [
        sys.executable,
        "-m",
        "pytest",
        str(test_dir),
        "-m",
        "m1",
        "-q",
        "--tb=line",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(test_dir.parent))
    log = (proc.stdout or "") + (proc.stderr or "")
    ok = proc.returncode == 0
    if verbose:
        return ok, log
    lines = [ln for ln in log.strip().splitlines() if ln.strip()]
    tail = "\n".join(lines[-12:]) if lines else f"exit={proc.returncode}"
    return ok, tail


def run_m4_gate(*, verbose: bool = False) -> tuple[bool, str]:
    """Run M4 vault adversarial suite."""
    test_dir = _repo_tests_dir()
    if test_dir is None:
        return False, "tests/ directory not found"
    target = test_dir / "test_m4_vault.py"
    if not target.exists():
        return False, "tests/test_m4_vault.py missing"
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        str(target),
        "-m",
        "m4",
        "-q",
        "--tb=line",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(test_dir.parent))
    log = (proc.stdout or "") + (proc.stderr or "")
    ok = proc.returncode == 0
    if verbose:
        return ok, log
    lines = [ln for ln in log.strip().splitlines() if ln.strip()]
    return ok, "\n".join(lines[-12:]) if lines else f"exit={proc.returncode}"
