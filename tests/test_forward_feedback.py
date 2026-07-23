from copy import deepcopy

import pytest

from engine.agent_loop import canonical_hash
from engine.forward_feedback import (
    FEEDBACK_EXPERIMENT_ID,
    build_feedback_context,
    build_postmortem,
    verify_feedback_context,
    verify_postmortem,
)
from engine.ledger import Ledger


def _arm(best, total, union_size, union_hits, repeated=None):
    return {
        "best_main_hits": best,
        "total_main_hits": total,
        "union_size": union_size,
        "union_main_hits": union_hits,
        "missed_actual_numbers": [1, 2],
        "repeated_but_missed": repeated or [],
    }


def _postmortem(game="super", period=1):
    registration = {
        "game": game,
        "target": {"date": f"2099-01-{period:02d}", "period": period},
        "registration_hash": f"registration-{period}",
    }
    arms = {
        "qwen_five": _arm(
            1,
            3,
            20,
            2,
            repeated=[
                {"number": 8, "selected_count": 3},
                {"number": 18, "selected_count": 3},
            ],
        ),
        "rule_five": _arm(2, 5, 24, 4),
        "random_five": _arm(2, 4, 23, 3),
    }
    comparison = {
        "eligible": True,
        "qwen_minus_rule_best_main_hits": -1,
    }
    return build_postmortem(registration, arms, comparison)


def _profit_shadow_settlement(*, eligible=True, common=False):
    settlement = {
        "experiment_id": "profit-portfolio-forward-shadows-v1",
        "eligible": eligible,
        "coverage_result": {
            "five_ticket_cost_ntd": 500,
            "empirical_floor_stress_strict_profit": False,
            "empirical_floor_stress_net_ntd": -500,
        },
        "portfolios": {
            "guarded_profit": {
                "eligible": eligible,
                "result": {
                    "empirical_floor_stress_strict_profit": True,
                    "empirical_floor_stress_net_ntd": 40,
                },
            },
            "unconstrained_profit": {
                "eligible": eligible,
                "result": {
                    "empirical_floor_stress_strict_profit": False,
                    "empirical_floor_stress_net_ntd": -400,
                },
            },
        },
    }
    if common:
        settlement["common_special_shadow"] = {
            "experiment_id": (
                "profit-common-special-forward-shadow-v1"
            ),
            "eligible": eligible,
            "portfolios": {
                "guarded_profit": {
                    "eligible": eligible,
                    "result": {
                        "empirical_floor_stress_strict_profit": False,
                        "empirical_floor_stress_net_ntd": -400,
                    },
                },
                "unconstrained_profit": {
                    "eligible": eligible,
                    "result": {
                        "empirical_floor_stress_strict_profit": True,
                        "empirical_floor_stress_net_ntd": 200,
                    },
                },
            },
        }
    return settlement


def _profit_postmortem(period=1, *, eligible=True, common=False):
    base = _postmortem(period=period)
    registration = {
        "game": base["game"],
        "target": base["target"],
        "registration_hash": base["registration_hash"],
    }
    arms = {
        "qwen_five": _arm(
            1,
            3,
            20,
            2,
            repeated=[
                {"number": 8, "selected_count": 3},
                {"number": 18, "selected_count": 3},
            ],
        ),
        "rule_five": _arm(2, 5, 24, 4),
        "random_five": _arm(2, 4, 23, 3),
    }
    return build_postmortem(
        registration,
        arms,
        {
            "eligible": True,
            "qwen_minus_rule_best_main_hits": -1,
        },
        _profit_shadow_settlement(
            eligible=eligible,
            common=common,
        ),
    )


def _append_settlement(ledger, postmortem):
    content = {
        "schema_version": "1",
        "experiment_id": "final-judge-forward-v1",
        "phase": "settlement",
        "registration_hash": postmortem["registration_hash"],
        "game": postmortem["game"],
        "target": postmortem["target"],
        "postmortem": postmortem,
    }
    ledger.append(
        "forward_settlement",
        {
            "content": content,
            "content_hash": canonical_hash(content),
        },
    )


def test_postmortem_uses_only_aggregate_noncausal_diagnostics():
    postmortem = _postmortem()

    verify_postmortem(postmortem)
    assert postmortem["experiment_id"] == FEEDBACK_EXPERIMENT_ID
    assert "qwen_below_rule_best" in postmortem["diagnostic_flags"]
    assert "qwen_below_random_best" in postmortem["diagnostic_flags"]
    assert "qwen_lower_union_than_rule" in postmortem["diagnostic_flags"]
    assert "qwen_repetition_without_hit" in postmortem[
        "diagnostic_flags"
    ]
    assert "do_not_chase_missed_numbers" in postmortem["guardrails"]
    assert "actual" not in postmortem


def test_profit_postmortem_keeps_only_comparable_aggregate_results():
    postmortem = _profit_postmortem()
    review = postmortem["profit_portfolio_review"]

    verify_postmortem(postmortem)
    assert review["objective"] == (
        "empirical_floor_stress_strict_profit"
    )
    assert review["coverage"] == {
        "empirical_floor_stress_strict_profit": False,
        "empirical_floor_stress_net_ntd": -500,
    }
    assert review["portfolios"]["guarded_profit"][
        "strict_profit_delta_vs_coverage"
    ] == 1
    assert review["portfolios"]["guarded_profit"][
        "net_delta_vs_coverage_ntd"
    ] == 540
    assert review["portfolios"]["unconstrained_profit"][
        "verdict"
    ] == "tie"
    serialized = str(review)
    assert "ticket_results" not in serialized
    assert "actual" not in serialized
    assert "missed_actual_numbers" not in serialized


def test_profit_postmortem_rejects_rehashed_semantic_tampering():
    postmortem = _profit_postmortem()
    postmortem["profit_portfolio_review"]["portfolios"][
        "guarded_profit"
    ]["net_delta_vs_coverage_ntd"] = 999
    postmortem["postmortem_hash"] = canonical_hash(
        {
            key: value
            for key, value in postmortem.items()
            if key != "postmortem_hash"
        }
    )

    with pytest.raises(ValueError, match="比較值"):
        verify_postmortem(postmortem)


def test_profit_postmortem_rejects_inconsistent_profit_and_net():
    postmortem = _profit_postmortem()
    guarded = postmortem["profit_portfolio_review"]["portfolios"][
        "guarded_profit"
    ]
    guarded["empirical_floor_stress_strict_profit"] = False
    guarded["strict_profit_delta_vs_coverage"] = 0
    guarded["verdict"] = "tie"
    postmortem["postmortem_hash"] = canonical_hash(
        {
            key: value
            for key, value in postmortem.items()
            if key != "postmortem_hash"
        }
    )

    with pytest.raises(ValueError, match="策略結果"):
        verify_postmortem(postmortem)


def test_common_special_postmortem_and_feedback_are_aggregate_only(
    tmp_path,
):
    postmortem = _profit_postmortem(common=True)
    review = postmortem["profit_portfolio_review"]
    common = review["common_special_shadow"]

    verify_postmortem(postmortem)
    assert common["portfolios"]["guarded_profit"][
        "strict_profit_delta_vs_baseline"
    ] == -1
    assert common["portfolios"]["unconstrained_profit"][
        "strict_profit_delta_vs_baseline"
    ] == 1
    assert "selected_special" not in str(common)
    assert "ticket_results" not in str(common)

    ledger = Ledger(tmp_path / "forward.jsonl")
    _append_settlement(ledger, postmortem)
    context = build_feedback_context(
        ledger,
        "super",
        before_target={"date": "2099-01-02", "period": 2},
    )
    aggregate = context["profit_portfolio_aggregate"][
        "common_special_shadow"
    ]
    assert aggregate["settlement_count"] == 1
    assert aggregate["portfolios"]["guarded_profit"][
        "strict_profit_delta_sum"
    ] == -1
    assert aggregate["portfolios"]["unconstrained_profit"][
        "strict_profit_delta_sum"
    ] == 1
    assert "selected_special" not in str(context)
    assert "actual" not in str(context)
    verify_feedback_context(
        context,
        game="super",
        target={"date": "2099-01-02", "period": 2},
    )


def test_feedback_context_is_bounded_hashed_and_strictly_before_target(
    tmp_path,
):
    ledger = Ledger(tmp_path / "forward.jsonl")
    _append_settlement(ledger, _postmortem(period=1))
    _append_settlement(ledger, _postmortem(period=2))
    _append_settlement(ledger, _postmortem(period=3))

    context = build_feedback_context(
        ledger,
        "super",
        before_target={"date": "2099-01-03", "period": 3},
    )

    assert context["settlement_count"] == 2
    assert [row["target"]["period"] for row in context["rows"]] == [1, 2]
    assert context["as_of_target"]["period"] == 2
    assert len(context["source_postmortem_hashes"]) == 2
    assert context["aggregate"][
        "mean_qwen_minus_rule_best_main_hits"
    ] == -1
    assert "feedback_contains_no_raw_draw_numbers" in context["guardrails"]
    verify_feedback_context(
        context,
        game="super",
        target={"date": "2099-01-03", "period": 3},
    )


def test_feedback_aggregates_only_eligible_profit_reviews(tmp_path):
    ledger = Ledger(tmp_path / "forward.jsonl")
    _append_settlement(ledger, _postmortem(period=1))
    _append_settlement(ledger, _profit_postmortem(period=2))
    _append_settlement(
        ledger,
        _profit_postmortem(period=3, eligible=False),
    )

    context = build_feedback_context(
        ledger,
        "super",
        before_target={"date": "2099-01-04", "period": 4},
    )
    aggregate = context["profit_portfolio_aggregate"]
    guarded = aggregate["portfolios"]["guarded_profit"]
    unconstrained = aggregate["portfolios"]["unconstrained_profit"]

    assert aggregate["settlement_count"] == 2
    assert aggregate["eligible_settlement_count"] == 1
    assert guarded["registered_settlement_count"] == 2
    assert guarded["eligible_pair_count"] == 1
    assert guarded["shadow_strict_profit_count"] == 1
    assert guarded["coverage_strict_profit_count"] == 0
    assert guarded["strict_profit_delta_sum"] == 1
    assert guarded["mean_net_delta_vs_coverage_ntd"] == 540
    assert unconstrained["strict_profit_delta_sum"] == 0
    assert context["rows"][0].get("profit_portfolio_review") is None
    assert "profit_portfolio_review" in context["rows"][1]
    assert context["rows"][2]["profit_portfolio_review"][
        "eligible"
    ] is False
    verify_feedback_context(
        context,
        game="super",
        target={"date": "2099-01-04", "period": 4},
    )


def test_profit_feedback_rejects_rehashed_aggregate_tampering(tmp_path):
    ledger = Ledger(tmp_path / "forward.jsonl")
    _append_settlement(ledger, _profit_postmortem())
    target = {"date": "2099-01-02", "period": 2}
    context = build_feedback_context(
        ledger,
        "super",
        before_target=target,
    )
    context["profit_portfolio_aggregate"]["portfolios"][
        "guarded_profit"
    ]["strict_profit_delta_sum"] = 99
    context["feedback_hash"] = canonical_hash(
        {
            key: value
            for key, value in context.items()
            if key != "feedback_hash"
        }
    )

    with pytest.raises(ValueError, match="獲利回饋彙總"):
        verify_feedback_context(
            context,
            game="super",
            target=target,
        )


def test_feedback_context_never_exposes_raw_draw_or_missed_numbers(tmp_path):
    ledger = Ledger(tmp_path / "forward.jsonl")
    _append_settlement(ledger, _postmortem())

    context = build_feedback_context(
        ledger,
        "super",
        before_target={"date": "2099-01-02", "period": 2},
    )
    serialized = str(context)

    assert "missed_actual_numbers" not in serialized
    assert "'number': 8" not in serialized
    assert "actual" not in serialized


def test_feedback_hash_and_future_row_tampering_are_rejected(tmp_path):
    ledger = Ledger(tmp_path / "forward.jsonl")
    _append_settlement(ledger, _postmortem())
    target = {"date": "2099-01-02", "period": 2}
    context = build_feedback_context(
        ledger,
        "super",
        before_target=target,
    )

    bad_hash = deepcopy(context)
    bad_hash["aggregate"]["mean_qwen_union_size"] = 99
    with pytest.raises(ValueError, match="雜湊"):
        verify_feedback_context(bad_hash, game="super", target=target)

    future = deepcopy(context)
    future["rows"][0]["target"] = target
    future["feedback_hash"] = canonical_hash(
        {
            key: value
            for key, value in future.items()
            if key != "feedback_hash"
        }
    )
    with pytest.raises(ValueError, match="未來資料"):
        verify_feedback_context(future, game="super", target=target)

    raw_number_injection = deepcopy(context)
    raw_number_injection["rows"][0]["missed_actual_numbers"] = [8, 18]
    raw_number_injection["feedback_hash"] = canonical_hash(
        {
            key: value
            for key, value in raw_number_injection.items()
            if key != "feedback_hash"
        }
    )
    with pytest.raises(ValueError, match="row 欄位"):
        verify_feedback_context(
            raw_number_injection,
            game="super",
            target=target,
        )

    forged_aggregate = deepcopy(context)
    forged_aggregate["aggregate"][
        "mean_qwen_minus_rule_best_main_hits"
    ] = 99
    forged_aggregate["feedback_hash"] = canonical_hash(
        {
            key: value
            for key, value in forged_aggregate.items()
            if key != "feedback_hash"
        }
    )
    with pytest.raises(ValueError, match="彙總"):
        verify_feedback_context(
            forged_aggregate,
            game="super",
            target=target,
        )


def test_empty_feedback_context_is_valid_and_explicit(tmp_path):
    context = build_feedback_context(
        Ledger(tmp_path / "empty.jsonl"),
        "lotto649",
        before_target={"date": "2099-01-02", "period": 1},
    )

    assert context["settlement_count"] == 0
    assert context["as_of_target"] is None
    assert context["rows"] == []
    assert "profit_portfolio_aggregate" not in context

    with pytest.raises(ValueError, match="介於 1 與 13"):
        build_feedback_context(
            Ledger(tmp_path / "empty.jsonl"),
            "lotto649",
            before_target={"date": "2099-01-02", "period": 1},
            limit=14,
        )
