"""開獎機制訊號的統計校準、巢狀切分與唯讀測試。"""
from __future__ import annotations

from itertools import islice
import json
import math
from pathlib import Path

import pytest

from engine.games import LOTTO649, SUPER
from research.gates import tree_sha256
from research.mechanism_signal import (
    MAIN_CANDIDATES,
    MechanismSignalConfig,
    _chi_square_sf,
    fit_main_model,
    historical_special_portfolio,
    run_mechanism_signal_study,
    write_results,
)
from research.portfolio_coverage import portfolio_structure
from research.profit_portfolio_forward import PORTFOLIO_IDS


BASE = Path(__file__).parent.parent
SIMULATION = BASE / "simulation" / "results"


def _events(game: str, count: int) -> list[dict]:
    with (SIMULATION / f"{game}.jsonl").open(
        encoding="utf-8"
    ) as handle:
        return [
            json.loads(line) for line in islice(handle, count)
        ]


def test_chi_square_survival_matches_closed_forms():
    for statistic in (0.2, 2.0, 7.5):
        assert _chi_square_sf(statistic, 2) == pytest.approx(
            math.exp(-statistic / 2),
            rel=1e-12,
        )
        assert _chi_square_sf(statistic, 4) == pytest.approx(
            math.exp(-statistic / 2)
            * (1 + statistic / 2),
            rel=1e-12,
        )


@pytest.mark.parametrize("game", [SUPER, LOTTO649])
def test_main_models_are_deterministic_complete_and_training_only(game):
    training = _events(game, 60)
    for candidate in MAIN_CANDIDATES[game]:
        first = fit_main_model(game, candidate, training)
        second = fit_main_model(game, candidate, training)

        assert first == second
        assert "reveal" not in fit_main_model.__code__.co_varnames
        assert all(
            len(numbers) == len(set(numbers)) == 30
            for numbers in first["selected_by_weekday"].values()
        )


def test_historical_special_portfolio_preserves_global_optimum_structure():
    event = _events(SUPER, 1)[0]
    baseline = portfolio_structure(
        SUPER,
        historical_special_portfolio(
            event["decision"], (2, 5, 3, 4, 1)
        ),
    )

    assert baseline["main_union_size"] == 30
    assert baseline["maximum_pairwise_main_overlap"] == 0
    assert baseline["special_coverage_probability"] == 5 / 8
    assert baseline["exact_any_prize"] == pytest.approx(
        0.5429629500836931
    )


@pytest.fixture(scope="module")
def smoke_result(tmp_path_factory):
    temp = tmp_path_factory.mktemp("mechanism-signal")
    ledgers = {}
    for game in (SUPER, LOTTO649):
        target = temp / f"{game}.jsonl"
        with (SIMULATION / f"{game}.jsonl").open(
            encoding="utf-8"
        ) as source:
            target.write_text(
                "".join(islice(source, 82)),
                encoding="utf-8",
            )
        ledgers[game] = target
    result = run_mechanism_signal_study(
        ledgers,
        base=BASE,
        config=MechanismSignalConfig(
            warmup_draws=60,
            bootstrap_samples=100,
            bootstrap_block=3,
        ),
        verify_ledgers=False,
    )
    paths = write_results(result, temp / "results")
    return result, paths


def test_smoke_study_profiles_grain_splits_and_records(smoke_result):
    result, paths = smoke_result

    assert result["data_quality"]["status"] == "pass"
    assert result["records_integrity"]["unchanged"] is True
    assert {
        row["game"] for row in result["main_candidate_holdout"]
    } == {SUPER, LOTTO649}
    for game in (SUPER, LOTTO649):
        profile = result["data_quality"]["profiles"][game]
        split = result["data_quality"]["split_profiles"][game]
        assert profile["draws"] == 82
        assert profile["duplicate_dates"] == 0
        assert profile["duplicate_periods"] == 0
        assert profile["legal_draws"] is True
        assert split["holdout_draws"] == 7
    assert all(path.exists() for path in paths.values())


def test_smoke_study_freezes_holdout_and_corrects_all_candidates(
    smoke_result,
):
    result, _ = smoke_result
    expected = sum(len(rows) for rows in MAIN_CANDIDATES.values())

    assert len(result["main_candidate_holdout"]) == expected
    assert all(
        0 <= row["holdout_raw_one_sided_p_value"] <= 1
        and 0 <= row["holm_adjusted_one_sided_p_value"] <= 1
        for row in result["main_candidate_holdout"]
    )
    special = result["super_special_candidate"]
    assert special["holdout_draws"] == 7
    assert len(set(special["selected_specials"])) == 5
    assert 0 <= special[
        "holm_adjusted_special_coverage_p_value"
    ] <= 1
    common = special["profit_common_special_candidate"]
    assert 1 <= common["selected_special"] <= 8
    assert 1 <= common["inner_selected_special"] <= 8
    assert set(common["holdout_portfolios"]) == set(PORTFOLIO_IDS)
    assert set(common["inner_validation_portfolios"]) == set(
        PORTFOLIO_IDS
    )
    assert all(
        row["draws"] == 7
        and 0 <= row["candidate_strict_profit_rate"] <= 1
        and 0 <= row["control_strict_profit_rate"] <= 1
        and (
            row["candidate_wins"]
            + row["ties"]
            + row["control_wins"]
            == 7
        )
        for row in common["holdout_portfolios"].values()
    )


def test_smoke_future_candidate_is_tamper_evident_and_shadow_only(
    smoke_result,
):
    result, _ = smoke_result
    candidate = result["future_forward_shadow_candidate"]

    assert len(candidate["candidate_hash"]) == 64
    assert candidate["promotion_eligible"] is False
    assert candidate["use"] == "future_forward_shadow_only"
    assert len(set(candidate["selected_specials"])) == 5
    assert (
        result["future_profit_common_special_shadow_candidate"]
        is None
    )


def test_smoke_is_deterministic_and_read_only(smoke_result):
    result, _ = smoke_result
    before = tree_sha256(BASE / "records")
    assert result["records_integrity"] == {
        "before_sha256": before,
        "after_sha256": before,
        "unchanged": True,
    }


def test_formal_result_passes_exact_acceptance_contract():
    from mechanism_signal_verify import verify_formal_result

    result = json.loads(
        (
            BASE
            / "research"
            / "results"
            / "mechanism_signal.json"
        ).read_text(encoding="utf-8")
    )

    verify_formal_result(result)
