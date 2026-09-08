"""demo-draw lab clock — local prospective round-trip without Taiwan ingest."""

from __future__ import annotations

from pathlib import Path

import pytest

from nullbench import (
    add_strategy,
    demo_draw,
    freeze_prospective,
    init_study,
    settle_period,
)
from nullbench.core.integrity import verify_study_semantic
from nullbench.core.study import Study
from nullbench.core.workspace import next_actions
from nullbench.domains.demo649 import generate_synthetic_draws
from nullbench.errors import DataError


def _demo_study(root: Path, *, n: int = 120) -> Path:
    init_study(root, experiment_id="lab-clock", domain="demo649", demo_draws=n)
    add_strategy(root, strategy_id="random", kind="random", tickets=5, seed=1)
    return root


def test_demo_draw_roundtrip_is_prospective(tmp_path: Path) -> None:
    study = _demo_study(tmp_path)
    raw_before = Study(study).draws_path.read_bytes()
    freeze_prospective(study)
    draw = demo_draw(study)
    assert draw.period == "P0121"
    expected = generate_synthetic_draws(n=121, seed=2026)[-1]
    assert draw.numbers == expected.numbers
    raw_after = Study(study).draws_path.read_bytes()
    assert raw_after.startswith(raw_before)
    assert raw_after != raw_before

    ok, issues = verify_study_semantic(study)
    assert ok, issues
    recs = settle_period(study, "P0121")
    assert len(recs) == 1
    rec = recs[0]
    assert rec.draw_entered_after_freeze is True
    assert rec.known_draws_at_freeze == 120
    assert rec.known_draws_at_settle == 121
    ok, issues = verify_study_semantic(study)
    assert ok, issues


def test_demo_draw_refuses_redraw(tmp_path: Path) -> None:
    study = _demo_study(tmp_path)
    with pytest.raises(DataError, match="immediate next"):
        demo_draw(study, "P0120")
    demo_draw(study)
    with pytest.raises(DataError, match="immediate next"):
        demo_draw(study, "P0121")


def test_demo_draw_refuses_skip(tmp_path: Path) -> None:
    study = _demo_study(tmp_path)
    with pytest.raises(DataError, match="immediate next"):
        demo_draw(study, "P0130")


def test_demo_draw_refuses_taiwan(tmp_path: Path) -> None:
    root = tmp_path / "tw"
    init_study(root, experiment_id="tw", domain="taiwan_super")
    add_strategy(root, strategy_id="random", kind="random", tickets=2, seed=1)
    with pytest.raises(DataError, match="lab clock"):
        demo_draw(root)


def test_coach_points_at_demo_draw(tmp_path: Path) -> None:
    study = _demo_study(tmp_path)
    freeze_prospective(study)
    actions = next_actions(study)
    assert any("demo-draw" in a for a in actions)
    assert any("waiting for draw" not in a or "demo-draw" in a for a in actions)


def test_demo_draw_n40_uses_matching_generator(tmp_path: Path) -> None:
    study = _demo_study(tmp_path, n=40)
    freeze_prospective(study)
    draw = demo_draw(study)
    assert draw.period == "P0041"
    assert draw.numbers == generate_synthetic_draws(n=41, seed=2026)[-1].numbers
    recs = settle_period(study)
    assert recs[0].draw_entered_after_freeze is True
    assert recs[0].known_draws_at_freeze == 40
    assert recs[0].known_draws_at_settle == 41
