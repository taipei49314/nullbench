from __future__ import annotations

from pathlib import Path

from nullbench.core import pipeline
from nullbench.core.workspace import doctor, next_actions, period_index
from nullbench.errors import StudyNotFoundError


def test_study_md_and_coach(tmp_path: Path) -> None:
    root = tmp_path / "s"
    pipeline.init_study(root, experiment_id="p1", domain="demo649", demo_draws=40)
    assert (root / "STUDY.md").exists()
    actions = next_actions(root)
    assert any("strategy" in a for a in actions)

    pipeline.add_strategy(root, strategy_id="random", kind="random", tickets=3, seed=1)
    actions = next_actions(root)
    assert any("freeze" in a for a in actions)

    rows = period_index(root)
    assert len(rows) == 40
    assert rows[-1]["settled"] is False

    recs = pipeline.freeze_latest(root)
    assert recs
    actions = next_actions(root)
    assert any("settle" in a for a in actions)

    pipeline.settle_period(root)
    pipeline.build_report(root)
    actions = next_actions(root)
    assert actions


def test_doctor_ok() -> None:
    info = doctor(None)
    assert info["ok"] is True


def test_doctor_reports_the_vault_path_it_inspected(tmp_path: Path) -> None:
    root = tmp_path / "s"
    pipeline.init_study(root, experiment_id="p-vault", domain="demo649", demo_draws=20)
    default = doctor(root)
    vault_row = next(c for c in default["checks"] if c["name"] == "vault_receipt")
    assert vault_row["ok"] is True
    assert "looked at" in str(vault_row["detail"])
    assert default["study"]["vault_path"]

    custom = tmp_path / "operator-vault"
    custom.mkdir()
    pointed = doctor(root, vault_root=custom)
    row = next(c for c in pointed["checks"] if c["name"] == "vault_receipt")
    assert str(custom.resolve()) in str(row["detail"])
    assert pointed["study"]["vault_path"] == str(custom.resolve())


def test_errors_study_missing(tmp_path: Path) -> None:
    try:
        next_actions(tmp_path / "nope")
        assert False
    except StudyNotFoundError:
        pass


def test_freeze_latest_idempotent_path(tmp_path: Path) -> None:
    root = tmp_path / "s2"
    pipeline.init_study(root, experiment_id="p2", domain="demo649", demo_draws=30)
    pipeline.add_strategy(root, strategy_id="random", kind="random", tickets=2, seed=1)
    pipeline.freeze_latest(root)
    # second freeze same period → empty list (idempotent)
    again = pipeline.freeze_period(
        root, pipeline.load_draws(root / "data" / "draws.jsonl")[-1].period
    )
    assert again == []
