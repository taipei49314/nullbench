"""共同第二區自適應稽核的時間界線、選模與唯讀測試。"""
from __future__ import annotations

from itertools import islice
import json
from pathlib import Path

from engine.games import SUPER
from research.adaptive_special_signal import (
    METHODS,
    AdaptiveSpecialConfig,
    _select_inner_candidate,
    build_prequential_predictions,
    predict_special,
    run_adaptive_special_study,
    write_results,
)
from research.gates import tree_sha256
from research.profit_portfolio_forward import PORTFOLIO_IDS


BASE = Path(__file__).parent.parent
SOURCE = BASE / "simulation" / "results" / "super.jsonl"


def _event(index: int, special: int, *, weekday_date: str) -> dict:
    return {
        "reveal": {
            "date": weekday_date,
            "period": index,
            "numbers": [1, 2, 3, 4, 5, 6],
            "special": special,
        }
    }


def test_predictors_are_deterministic_and_use_only_supplied_history():
    history = [
        _event(1, 3, weekday_date="2026-01-05"),
        _event(2, 3, weekday_date="2026-01-08"),
        _event(3, 2, weekday_date="2026-01-12"),
    ]
    for method in METHODS:
        first = predict_special(method, history, "2026-01-15")
        second = predict_special(method, history, "2026-01-15")
        with_future = predict_special(
            method,
            history,
            "2026-01-15",
        )
        assert first == second == with_future
        assert 1 <= first <= 8

    assert predict_special(
        "expanding_global", history, "2026-01-15"
    ) == 3


def test_prequential_predictions_do_not_change_when_future_is_tampered():
    events = [
        _event(
            index,
            1 if index < 6 else 8,
            weekday_date=f"2026-01-{index:02d}",
        )
        for index in range(1, 10)
    ]
    original = build_prequential_predictions(
        events, warmup_draws=5
    )
    events[-1]["reveal"]["special"] = 4
    tampered = build_prequential_predictions(
        events, warmup_draws=5
    )

    for method in METHODS:
        assert original[method][8] == tampered[method][8]
        assert original[method][7] == tampered[method][7]


def test_inner_selection_requires_both_profit_structures_positive():
    def row(guarded, unconstrained, special_delta):
        return {
            "delta_vs_exact_null": special_delta,
            "portfolios": {
                PORTFOLIO_IDS[0]: {
                    "strict_profit_delta": guarded,
                    "mean_net_delta_ntd": guarded * 100,
                },
                PORTFOLIO_IDS[1]: {
                    "strict_profit_delta": unconstrained,
                    "mean_net_delta_ntd": unconstrained * 100,
                },
            },
        }

    results = {
        method: row(-0.1, 0.2, 0.1) for method in METHODS
    }
    assert _select_inner_candidate(results) == (None, [])
    results["rolling_52"] = row(0.01, 0.02, 0.03)
    results["rolling_104"] = row(0.02, 0.005, 0.03)

    selected, eligible = _select_inner_candidate(results)
    assert selected == "rolling_52"
    assert eligible == ["rolling_52", "rolling_104"]


def test_smoke_study_profiles_splits_and_preserves_records(tmp_path):
    ledger = tmp_path / "super.jsonl"
    with SOURCE.open(encoding="utf-8") as source:
        ledger.write_text(
            "".join(islice(source, 82)),
            encoding="utf-8",
        )
    before = tree_sha256(BASE / "records")
    result = run_adaptive_special_study(
        ledger,
        base=BASE,
        config=AdaptiveSpecialConfig(
            bootstrap_samples=100,
            bootstrap_block=3,
        ),
        verify_ledger=False,
    )
    output = write_results(result, tmp_path / "results")

    assert output.exists()
    assert result["data_quality"]["status"] == "pass"
    assert result["data_quality"]["profile"]["draws"] == 82
    assert result["data_quality"]["split_profile"][
        "inner_validation_draws"
    ] == 5
    assert result["data_quality"]["split_profile"][
        "holdout_draws"
    ] == 7
    assert set(
        result["inner_validation"]["results"]
    ) == set(METHODS)
    assert result["records_integrity"] == {
        "before_sha256": before,
        "after_sha256": before,
        "unchanged": True,
    }
    assert json.loads(output.read_text(encoding="utf-8")) == result


def test_formal_result_passes_exact_acceptance_contract():
    from adaptive_special_signal_verify import verify_formal_result

    result = json.loads(
        (
            BASE
            / "research"
            / "results"
            / "adaptive_special_signal.json"
        ).read_text(encoding="utf-8")
    )

    verify_formal_result(result)
