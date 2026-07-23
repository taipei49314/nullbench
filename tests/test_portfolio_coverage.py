"""五注精確機率與 coverage selector 研究測試。"""
from __future__ import annotations

from itertools import combinations, islice
import json
import math
from pathlib import Path

import pytest

from engine.games import LOTTO649, SUPER
from research.portfolio_coverage import (
    CoverageConfig,
    _main_hit_distribution,
    _membership_counts,
    exact_any_prize_probability,
    exact_main_hit_probability,
    portfolio_structure,
    run_coverage_study,
    select_coverage_portfolio,
    uniform_random_five_any_prize_probability,
    uniform_random_five_probability,
    write_results,
)


BASE = Path(__file__).parent.parent
SIMULATION = BASE / "simulation" / "results"


def _ticket(numbers, special=None):
    return {"numbers": list(numbers), "special": special}


def _event(game: str, sequence: int) -> dict:
    with (SIMULATION / f"{game}.jsonl").open(encoding="utf-8") as handle:
        return json.loads(next(islice(handle, sequence - 1, sequence)))


def _copy_prefix(source: Path, target: Path, lines: int) -> None:
    with source.open(encoding="utf-8") as handle:
        target.write_text(
            "".join(islice(handle, lines)),
            encoding="utf-8",
        )


@pytest.mark.parametrize(
    ("game", "identical_expected", "disjoint_expected"),
    [
        (SUPER, 0.038698060369886995, 0.1920413839918484),
        (LOTTO649, 0.01863754500202234, 0.09290168005643094),
    ],
)
def test_exact_probability_matches_known_identical_and_disjoint_portfolios(
    game,
    identical_expected,
    disjoint_expected,
):
    specials = [1, 2, 3, 4, 5] if game == SUPER else [None] * 5
    identical = [
        _ticket(range(1, 7), special)
        for special in specials
    ]
    # Exact API requires five distinct tickets. Use the internal structural
    # equivalence by changing one number while preserving the expected single
    # ticket value through a direct one-ticket helper is intentionally avoided;
    # public portfolios model the production five-distinct-ticket contract.
    with pytest.raises(ValueError, match="不得重複"):
        exact_main_hit_probability(game, identical)

    disjoint = [
        _ticket(range(index * 6 + 1, index * 6 + 7), specials[index])
        for index in range(5)
    ]
    assert exact_main_hit_probability(game, disjoint) == pytest.approx(
        disjoint_expected
    )

    single_like = [
        _ticket([1, 2, 3, 4, 5, 6], specials[0]),
        _ticket([1, 2, 3, 4, 5, 7], specials[1]),
        _ticket([1, 2, 3, 4, 5, 8], specials[2]),
        _ticket([1, 2, 3, 4, 5, 9], specials[3]),
        _ticket([1, 2, 3, 4, 5, 10], specials[4]),
    ]
    assert exact_main_hit_probability(game, single_like) > identical_expected


@pytest.mark.parametrize(
    ("game", "expected"),
    [
        (SUPER, 0.1790834153329185),
        (LOTTO649, 0.08977829451460184),
    ],
)
def test_uniform_random_five_probability_is_exact(game, expected):
    assert uniform_random_five_probability(game) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("game", "special", "single_expected", "random_five_expected"),
    [
        (
            SUPER,
            1,
            0.11782962247358533,
            0.46572816257478966,
        ),
        (
            LOTTO649,
            None,
            0.030951780257978224,
            0.1454707552483958,
        ),
    ],
)
def test_exact_any_prize_probability_matches_single_ticket_formula(
    game,
    special,
    single_expected,
    random_five_expected,
):
    ticket = _ticket(range(1, 7), special)

    assert exact_any_prize_probability(
        game, [ticket]
    ) == pytest.approx(single_expected)
    assert uniform_random_five_any_prize_probability(
        game
    ) == pytest.approx(random_five_expected)


def test_lotto_overlap_moments_match_independent_small_pool_enumeration():
    pool = 12
    ticket_sets = [
        {1, 2, 3, 4, 5, 6},
        {4, 5, 6, 7, 8, 9},
    ]
    counts = _membership_counts(pool, ticket_sets)
    distribution = _main_hit_distribution(
        pool,
        counts,
        track_selected_unions=True,
    )
    dp_favorable = 0
    for hits, ways, selected_sums in distribution:
        if max(hits) >= 3:
            dp_favorable += ways * (pool - 6)
            continue
        eligible = sum(
            1 << index
            for index, value in enumerate(hits)
            if value == 2
        )
        if eligible:
            eligible_union = sum(
                size
                for mask, size in enumerate(counts)
                if mask & eligible
            )
            dp_favorable += (
                eligible_union * ways - selected_sums[eligible]
            )

    brute_favorable = 0
    for draw in combinations(range(1, pool + 1), 6):
        draw_set = set(draw)
        hits = [
            len(ticket & draw_set) for ticket in ticket_sets
        ]
        for bonus in set(range(1, pool + 1)) - draw_set:
            if max(hits) >= 3 or any(
                hit == 2 and bonus in ticket
                for hit, ticket in zip(hits, ticket_sets)
            ):
                brute_favorable += 1

    assert dp_favorable == brute_favorable
    assert dp_favorable <= math.comb(pool, 6) * (pool - 6)


@pytest.mark.parametrize("overlap", [0, 3, 5])
@pytest.mark.parametrize("same_special", [False, True])
def test_super_two_ticket_probability_matches_independent_category_count(
    overlap,
    same_special,
):
    left_special = 1
    right_special = 1 if same_special else 2
    tickets = [
        _ticket(range(1, 7), left_special),
        _ticket(
            list(range(1, overlap + 1))
            + list(range(7, 7 + 6 - overlap)),
            right_special,
        ),
    ]
    favorable = 0
    outside = 38 - (12 - overlap)
    for shared in range(overlap + 1):
        for left_only in range(6 - overlap + 1):
            for right_only in range(6 - overlap + 1):
                neither = 6 - shared - left_only - right_only
                if not 0 <= neither <= outside:
                    continue
                ways = (
                    math.comb(overlap, shared)
                    * math.comb(6 - overlap, left_only)
                    * math.comb(6 - overlap, right_only)
                    * math.comb(outside, neither)
                )
                hits = (
                    shared + left_only,
                    shared + right_only,
                )
                if max(hits) >= 3:
                    favorable_specials = 8
                else:
                    favorable_specials = len(
                        {
                            special
                            for special, hit in zip(
                                (left_special, right_special), hits
                            )
                            if hit in (1, 2)
                        }
                    )
                favorable += ways * favorable_specials

    expected = favorable / (math.comb(38, 6) * 8)
    assert exact_any_prize_probability(
        SUPER, tickets
    ) == pytest.approx(expected)


@pytest.mark.parametrize("game", [SUPER, LOTTO649])
def test_coverage_selector_is_deterministic_reveal_free_and_non_decreasing(
    game,
):
    decision = _event(game, 61)["decision"]

    first, first_meta = select_coverage_portfolio(game, decision)
    second, second_meta = select_coverage_portfolio(game, decision)

    assert first == second
    assert first_meta == second_meta
    assert len(first) == 5
    assert first_meta["combinations_evaluated"] == 3_003
    assert first_meta["exact_probability_delta"] >= -1e-15
    assert (
        first_meta["exact_any_prize_probability_delta"] >= -1e-15
    )
    assert (
        first_meta["selected"]["bonferroni_lower_bound"]
        >= first_meta["baseline"]["bonferroni_lower_bound"] - 1e-15
    )
    assert (
        first_meta["selected"]["any_prize_bonferroni_lower_bound"]
        >= first_meta["baseline"][
            "any_prize_bonferroni_lower_bound"
        ]
        - 1e-15
    )
    assert "reveal" not in select_coverage_portfolio.__code__.co_varnames
    proposal_ids = {
        proposal["proposal_id"] for proposal in decision["proposals"]
    }
    assert set(first_meta["selected_proposal_ids"]) <= proposal_ids


@pytest.mark.parametrize("game", [SUPER, LOTTO649])
def test_structure_reports_exact_probability_and_super_special_coverage(game):
    tickets, _ = select_coverage_portfolio(
        game, _event(game, 61)["decision"]
    )

    structure = portfolio_structure(game, tickets)

    assert 6 <= structure["main_union_size"] <= 30
    assert 0 < structure["bonferroni_lower_bound"] <= 1
    assert (
        structure["exact_at_least_three_main"]
        >= structure["bonferroni_lower_bound"]
    )
    assert (
        structure["exact_any_prize"]
        >= structure["exact_at_least_three_main"]
    )
    if game == SUPER:
        assert structure["special_coverage_probability"] in {
            0.125,
            0.25,
            0.375,
            0.5,
            0.625,
        }
    else:
        assert structure["special_coverage_probability"] is None


@pytest.fixture(scope="module")
def smoke_result(tmp_path_factory):
    temp = tmp_path_factory.mktemp("portfolio-coverage")
    ledgers = {}
    for game in (SUPER, LOTTO649):
        target = temp / f"{game}.jsonl"
        _copy_prefix(SIMULATION / f"{game}.jsonl", target, 82)
        ledgers[game] = target
    result = run_coverage_study(
        ledgers,
        base=BASE,
        config=CoverageConfig(
            warmup_draws=60,
            bootstrap_samples=100,
            bootstrap_block=3,
        ),
        verify_ledgers=False,
    )
    paths = write_results(result, temp / "results")
    return result, paths


def test_smoke_study_has_both_splits_and_preserves_records(smoke_result):
    result, paths = smoke_result

    assert result["data_quality"]["status"] == "pass"
    assert result["records_integrity"]["unchanged"] is True
    assert {
        (row["game"], row["split"]) for row in result["summary"]
    } == {
        (SUPER, "development"),
        (SUPER, "holdout"),
        (LOTTO649, "development"),
        (LOTTO649, "holdout"),
    }
    assert all(
        row["minimum_exact_probability_delta"] >= -1e-15
        and row["exact_probability_non_decrease_rate"] == 1.0
        and row["minimum_any_prize_probability_delta"] >= -1e-15
        and row["any_prize_probability_non_decrease_rate"] == 1.0
        and 0 < row["uniform_random_five_probability"] < 1
        and 0
        < row["uniform_random_five_any_prize_probability"]
        < 1
        for row in result["summary"]
    )
    assert all(path.exists() for path in paths.values())
    assert not list(paths["json"].parent.glob("*.tmp"))


def test_smoke_trace_contains_no_raw_draw_numbers(smoke_result):
    result, _ = smoke_result

    serialized = json.dumps(
        result["recent_holdout_trace"], ensure_ascii=False
    )
    assert '"numbers"' not in serialized
    assert '"special"' not in serialized
