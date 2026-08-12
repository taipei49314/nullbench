"""Maturity ladder M0–M4 and M1 product gate."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


LEVELS = (
    ("M0", "Lab CLI / demo / PyPI", "done"),
    ("M1", "Sealed local study (must-pass gate)", "done"),
    ("M2", "PRD + Threat Model + Public API + Claim Policy frozen", "frozen"),
    ("M3", "Trusted Publishing / SBOM / plugin allowlist", "partial"),
    ("M4", "Remote sealed study / vault", "planned"),
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
)

PRODUCT_GATE = (
    "Without M1 green, do not publicly claim "
    "'auditable' / 'never backfill' (or Chinese equivalents) as absolute "
    "product guarantees. See CLAIM_POLICY.md."
)


@dataclass
class MaturityStatus:
    levels: list[dict]
    m1_checklist: list[dict]
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
                    "partial": "In-repo controls shipped; maintainer must finish PyPI Trusted Publisher setup",
                    "planned": "Not started as exit criteria",
                    "gate": "Must pass before strong integrity marketing",
                    "draft": "Documents exist as draft; not frozen",
                    "shipping": "Current product class",
                }.get(r, r),
            }
            for i, n, r in LEVELS
        ],
        m1_checklist=[{"id": i, "item": t} for i, t in M1_CHECKLIST],
        m1_tests_ok=None,
        product_gate=PRODUCT_GATE,
        allowed_claims=[
            "Open-source null-first decision lab",
            "M1 local seals (inconsistent-edit detection)",
            "M2 frozen PRD / threat model / public API / claim policy",
            "M3: OIDC publish workflow + CI SBOM + plugin allowlist",
            "Residual risk: consistent full local rewrite until M4 (THREAT_MODEL)",
        ],
        forbidden_until_m1=[
            "可稽核 as absolute guarantee",
            "永不 backfill / never backfill as absolute guarantee",
            "tamper-proof",
            "prediction / winning numbers (always forbidden in reports)",
        ],
    )


def run_m1_gate(*, verbose: bool = False) -> tuple[bool, str]:
    """Run adversarial M1 suite. Returns (ok, log_tail)."""
    candidates = [
        Path.cwd() / "tests",
        Path(__file__).resolve().parents[2] / "tests",
    ]
    test_dir = next((p for p in candidates if p.is_dir()), None)
    if test_dir is None:
        return False, "tests/ directory not found (install from source to run M1 gate)"

    targets = [test_dir / "test_integrity_ic.py"]
    if (test_dir / "test_m1_gate.py").exists():
        targets.append(test_dir / "test_m1_gate.py")
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        *[str(t) for t in targets],
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
