"""精確枚舉 selector 稽核測試。"""
import json
from pathlib import Path

import pytest

from engine.games import LOTTO649, SUPER
from research.exact_selector_audit import (
    audit_exact_candidate_pool,
    disjoint_reference_tickets,
)
from research.portfolio_coverage import portfolio_structure


BASE = Path(__file__).parent.parent


@pytest.fixture(scope="module")
def manifest():
    return json.loads(
        (BASE / "simulation" / "results" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )


@pytest.mark.parametrize(
    ("game", "any_prize", "three_main"),
    [
        (SUPER, 0.5429629500836931, 0.1920413839918484),
        (LOTTO649, 0.15296613117321764, 0.09290168005643094),
    ],
)
def test_disjoint_reference_has_known_exact_probabilities(
    game,
    any_prize,
    three_main,
):
    structure = portfolio_structure(
        game, disjoint_reference_tickets(game)
    )

    assert structure["main_union_size"] == 30
    assert structure["mean_pairwise_main_overlap"] == 0
    assert structure["exact_any_prize"] == pytest.approx(any_prize)
    assert structure["exact_at_least_three_main"] == pytest.approx(
        three_main
    )


@pytest.mark.parametrize("game", [SUPER, LOTTO649])
def test_limited_exact_audit_is_reveal_free_and_never_negative_regret(
    game,
    manifest,
):
    result = audit_exact_candidate_pool(
        game,
        manifest["games"][game]["next_decision"],
        limit=5,
    )

    assert result["combinations_evaluated"] == 5
    assert result["complete_enumeration"] is False
    assert result["heuristic_any_prize_regret"] >= 0
    assert (
        result["exact_best_safe"]["exact_any_prize"]
        >= result["heuristic_selected"]["exact_any_prize"]
    )
    assert (
        "reveal"
        not in audit_exact_candidate_pool.__code__.co_varnames
    )
