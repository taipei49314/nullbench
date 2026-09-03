"""NORTH_STAR prospective streak — trailing after-freeze settles."""

from __future__ import annotations

import json
from pathlib import Path

from nullbench import (
    add_strategy,
    build_report,
    freeze_period,
    freeze_prospective,
    init_study,
    settle_period,
)
from nullbench.core.pipeline import load_draws, status, trailing_prospective_streak
from nullbench.core.study import Study


def _demo(root: Path) -> Path:
    init_study(root, experiment_id="m5-streak", domain="demo649")
    add_strategy(root, strategy_id="random", kind="random", tickets=5, seed=1)
    return root


def _append_draw(root: Path, period: str, numbers: list[int]) -> None:
    study = Study(root)
    draws = load_draws(study.draws_path)
    rows = [json.loads(d.model_dump_json()) for d in draws]
    rows.append({"period": period, "numbers": numbers, "special": None, "date": None})
    study.draws_path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def test_trailing_streak_helper() -> None:
    assert trailing_prospective_streak([]) == 0
    assert trailing_prospective_streak([{"draw_entered_after_freeze": True}]) == 1
    assert (
        trailing_prospective_streak(
            [
                {"draw_entered_after_freeze": True},
                {"draw_entered_after_freeze": False},
                {"draw_entered_after_freeze": True},
            ]
        )
        == 1
    )
    assert (
        trailing_prospective_streak(
            [{"draw_entered_after_freeze": True}, {"draw_entered_after_freeze": True}]
        )
        == 2
    )


def test_one_prospective_settle_streak_is_one(tmp_path: Path) -> None:
    study = _demo(tmp_path)
    freeze_prospective(study)
    _append_draw(study, "P0121", [3, 11, 19, 28, 37, 44])
    settle_period(study, "P0121")
    summary = build_report(study)
    assert summary.prospective_streak == 1
    assert any(w.startswith("PROSPECTIVE STREAK: 1") for w in summary.warnings)
    assert "not a completed prospective experiment" in summary.warnings[0].lower()
    md = (Study(study).reports_dir / "latest.md").read_text(encoding="utf-8")
    assert "Prospective streak: **1**" in md
    assert status(study)["prospective_streak"] == 1


def test_replay_breaks_trailing_streak(tmp_path: Path) -> None:
    study = _demo(tmp_path)
    freeze_period(study, "P0120")
    settle_period(study, "P0120")
    freeze_prospective(study)  # P0121
    _append_draw(study, "P0121", [3, 11, 19, 28, 37, 44])
    settle_period(study, "P0121")
    summary = build_report(study)
    # Causal order: P0120 replay, then P0121 after-freeze → trailing streak 1
    assert summary.prospective_streak == 1
    assert summary.periods_settled == 2
