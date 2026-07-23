"""辯論主號排名稽核的時間界線、精確零模型與唯讀測試。"""
from __future__ import annotations

from itertools import islice
import json
import math
from pathlib import Path

import pytest

from engine.games import LOTTO649, PICK_N, POOL, SUPER
from research.debate_rank_calibration import (
    CUTOFFS,
    DebateRankCalibrationConfig,
    _single_hypergeometric,
    _total_hit_distribution,
    build_debate_ranking,
    ranking_metrics,
    run_debate_rank_calibration,
    write_results,
)
from research.gates import tree_sha256


BASE = Path(__file__).parent.parent
SOURCES = {
    SUPER: BASE / "simulation" / "results" / "super.jsonl",
    LOTTO649: BASE / "simulation" / "results" / "lotto649.jsonl",
}


def _first_event(game: str) -> dict:
    with SOURCES[game].open(encoding="utf-8") as handle:
        return json.loads(next(handle))


@pytest.mark.parametrize("game", [SUPER, LOTTO649])
def test_pre_reveal_builder_returns_complete_deterministic_ranking(game):
    event = _first_event(game)
    first, quality = build_debate_ranking(
        game, event["decision"]
    )
    second, _ = build_debate_ranking(game, event["decision"])

    assert first == second
    assert sorted(first) == list(range(1, POOL[game] + 1))
    assert quality["ranking_size"] == POOL[game]
    assert quality["unique_numbers"] == POOL[game]
    assert quality["proposal_appearances_total"] == 15 * PICK_N


@pytest.mark.parametrize("game", [SUPER, LOTTO649])
def test_future_actual_numbers_cannot_change_pre_reveal_ranking(game):
    event = _first_event(game)
    ranking_before, _ = build_debate_ranking(
        game, event["decision"]
    )
    event["reveal"]["numbers"] = list(
        range(POOL[game] - PICK_N + 1, POOL[game] + 1)
    )
    ranking_after, _ = build_debate_ranking(
        game, event["decision"]
    )

    assert ranking_after == ranking_before


def test_builder_rejects_incomplete_or_duplicated_debate_contract():
    event = _first_event(SUPER)
    event["decision"]["adjudication"]["candidate_scores"].append(
        dict(
            event["decision"]["adjudication"][
                "candidate_scores"
            ][0]
        )
    )

    with pytest.raises(ValueError, match="15 個唯一提案"):
        build_debate_ranking(SUPER, event["decision"])


def test_ranking_metrics_rejects_malformed_actual_numbers():
    event = _first_event(SUPER)
    ranking, _ = build_debate_ranking(
        SUPER, event["decision"]
    )

    with pytest.raises(ValueError, match="六個唯一合法"):
        ranking_metrics(SUPER, ranking, [1, 1, 2, 3, 4, 5])


@pytest.mark.parametrize(
    ("game", "selected"),
    [
        (SUPER, 10),
        (SUPER, 20),
        (SUPER, 30),
        (LOTTO649, 10),
        (LOTTO649, 20),
        (LOTTO649, 30),
    ],
)
def test_exact_hypergeometric_distribution_is_normalized_and_centered(
    game, selected
):
    single = _single_hypergeometric(POOL[game], selected)

    assert math.fsum(single) == pytest.approx(1.0)
    assert sum(
        hits * probability
        for hits, probability in enumerate(single)
    ) == pytest.approx(PICK_N * selected / POOL[game])

    periods = 4
    total = _total_hit_distribution(
        pool=POOL[game],
        selected=selected,
        periods=periods,
    )
    assert math.fsum(total) == pytest.approx(1.0)
    assert sum(
        hits * probability
        for hits, probability in enumerate(total)
    ) == pytest.approx(
        periods * PICK_N * selected / POOL[game]
    )


def test_smoke_study_profiles_splits_and_preserves_records(tmp_path):
    ledgers = {}
    for game, source_path in SOURCES.items():
        ledger = tmp_path / f"{game}.jsonl"
        with source_path.open(encoding="utf-8") as source:
            ledger.write_text(
                "".join(islice(source, 82)),
                encoding="utf-8",
            )
        ledgers[game] = ledger

    before = tree_sha256(BASE / "records")
    result = run_debate_rank_calibration(
        ledgers,
        base=BASE,
        config=DebateRankCalibrationConfig(
            bootstrap_samples=100,
            bootstrap_block=3,
        ),
        verify_ledgers=False,
    )
    output = write_results(result, tmp_path / "results")

    assert output.exists()
    assert set(result["games"]) == {SUPER, LOTTO649}
    assert result["protocol"]["cutoffs"] == list(CUTOFFS)
    for game in (SUPER, LOTTO649):
        quality = result["games"][game]["data_quality"]
        assert quality["status"] == "pass"
        assert quality["profile"]["draws"] == 82
        assert quality["split_profile"][
            "development_draws"
        ] == 15
        assert quality["split_profile"]["holdout_draws"] == 7
        assert quality["ranking_rows"] == 22
        assert quality["ranking_size_min"] == POOL[game]
        assert quality["ranking_size_max"] == POOL[game]
        assert quality["unique_numbers_min"] == POOL[game]
        assert quality["proposal_appearances_total_min"] == 90
        assert quality["proposal_appearances_total_max"] == 90
        assert set(result["games"][game]["holdout"]) == {
            "top_10_hits",
            "top_20_hits",
            "top_30_hits",
            "top_10_minus_next_10_hits",
        }
    assert result["records_integrity"] == {
        "before_sha256": before,
        "after_sha256": before,
        "unchanged": True,
    }
    assert json.loads(output.read_text(encoding="utf-8")) == result


def test_formal_result_passes_exact_acceptance_contract():
    from debate_rank_calibration_verify import verify_formal_result

    result = json.loads(
        (
            BASE
            / "research"
            / "results"
            / "debate_rank_calibration.json"
        ).read_text(encoding="utf-8")
    )

    verify_formal_result(result)
