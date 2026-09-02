"""M5.0 honesty pass — replay freezes are labeled and reports say so.

North-star rule (NORTH_STAR.md): a freeze whose outcome already existed in
draws.jsonl is a *replay* freeze. It must be marked ``late`` in the ledger and
the report must not read as prospective pre-registration evidence.
"""

from __future__ import annotations

from pathlib import Path

from nullbench import add_strategy, build_report, freeze_period, init_study, settle_period


def _demo_study(root: Path) -> Path:
    init_study(root, experiment_id="m5-honesty", domain="demo649")
    add_strategy(root, strategy_id="random", kind="random", tickets=5, seed=1)
    return root


def test_replay_freeze_is_marked_late(tmp_path: Path) -> None:
    study = _demo_study(tmp_path)
    # demo649 writes 120 draws up front; freezing any of them is replay.
    records = freeze_period(study, "P0120")
    assert records, "expected at least one freeze arm"
    for rec in records:
        assert rec.late is True
        assert rec.outcome_hash is not None, "replay freeze seals the known outcome"


def test_ledger_row_carries_late_true(tmp_path: Path) -> None:
    from nullbench.core.study import Study

    study = _demo_study(tmp_path)
    freeze_period(study, "P0120")
    rows = Study(study).ledger().events_of("freeze")
    assert rows
    assert all(r["late"] is True for r in rows)


def test_report_warns_all_replay(tmp_path: Path) -> None:
    study = _demo_study(tmp_path)
    freeze_period(study, "P0120")
    settle_period(study)
    summary = build_report(study)
    replay_warnings = [w for w in summary.warnings if w.startswith("REPLAY:")]
    assert replay_warnings, f"expected REPLAY warning, got: {summary.warnings}"
    assert "not prospective" in replay_warnings[0]


def test_markdown_report_carries_replay_warning(tmp_path: Path) -> None:
    from nullbench.core.study import Study

    study = _demo_study(tmp_path)
    freeze_period(study, "P0120")
    settle_period(study)
    build_report(study)
    md = (Study(study).reports_dir / "latest.md").read_text(encoding="utf-8")
    assert "REPLAY" in md
