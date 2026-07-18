"""階段 3：validation 選擇、holdout 封存與升級門檻測試。"""
from copy import deepcopy
from pathlib import Path

import pytest

from engine.games import LOTTO649, SUPER
from engine.store import DrawStore
from research.backtest import (
    CURRENT,
    UNIFORM,
    Policy,
    build_contexts,
    select_and_open_holdout,
    select_validation_policy,
)
from research.gates import (
    FINAL_POLICY_IDS,
    StageGateError,
    build_validation_holdout_gate,
    create_holdout_seal,
    edge_is_proven,
    require_gate,
    verify_holdout_seal,
)


DATA = Path(__file__).parent.parent / "data"


def _summary(game, split, policy_id, delta):
    return {
        "game": game,
        "game_name": "測試",
        "split": split,
        "policy_id": policy_id,
        "delta_robust_roi_mean": delta,
        "delta_fixed_roi_mean": 0.01 if policy_id != "random_5" else 0,
        "delta_ci_low": 0.01 if policy_id != "random_5" else 0,
        "delta_ci_high": 0.02 if policy_id != "random_5" else 0,
        "positive_replicate_rate": 0.75 if policy_id != "random_5" else 0,
        "active_week_win_rate": 0.51 if policy_id != "random_5" else 0.5,
    }


def _summaries():
    rows = []
    for game in (SUPER, LOTTO649):
        for split in ("train", "validation", "holdout"):
            for index, policy_id in enumerate(FINAL_POLICY_IDS):
                delta = 0 if policy_id == "random_5" else index / 100
                rows.append(_summary(game, split, policy_id, delta))
    return rows


def _contexts_policies_fingerprints():
    store = DrawStore(DATA)
    contexts = {
        game: build_contexts(game, store.draws(game)[:80])
        for game in (SUPER, LOTTO649)
    }
    policies = {
        game: [
            Policy("random_5", (UNIFORM,) * 5),
            Policy(
                "current_ensemble",
                (
                    UNIFORM,
                    CURRENT["antipop"],
                    CURRENT["balance"],
                    CURRENT["cold"],
                    CURRENT["hot"],
                ),
            ),
            Policy("trained_family_ensemble", (CURRENT["hot"],) * 5),
            Policy("trained_best_5", (CURRENT["cold"],) * 5),
            Policy("trained_blend", (CURRENT["balance"],) * 5),
        ]
        for game in (SUPER, LOTTO649)
    }
    fingerprints = {SUPER: "a" * 64, LOTTO649: "b" * 64}
    return contexts, policies, fingerprints


def test_validation_selection_ignores_train_and_holdout_values():
    rows = _summaries()
    original = select_validation_policy(rows, SUPER)["policy_id"]
    changed = deepcopy(rows)
    for row in changed:
        if row["game"] == SUPER and row["split"] != "validation":
            row["delta_robust_roi_mean"] = 999
    assert select_validation_policy(changed, SUPER)["policy_id"] == original


def test_validation_tie_break_is_policy_id_and_coverage_is_required():
    rows = _summaries()
    validation = [
        row for row in rows if row["game"] == SUPER and row["split"] == "validation"
    ]
    for row in validation:
        row["delta_robust_roi_mean"] = 0.1
    assert select_validation_policy(rows, SUPER)["policy_id"] == min(
        FINAL_POLICY_IDS
    )
    rows.remove(validation[0])
    with pytest.raises(ValueError, match="覆蓋不完整"):
        select_validation_policy(rows, SUPER)


def test_selected_policy_opens_exactly_one_holdout_row():
    rows = _summaries()
    decision = select_and_open_holdout(rows, SUPER)
    assert decision["policy_id"] == "trained_blend"
    assert decision["holdout"]["split"] == "holdout"
    assert decision["edge_proven"] is True
    assert decision["conditional_decision"] == "trained_blend"

    rows.append(deepcopy(decision["holdout"]))
    with pytest.raises(ValueError, match="恰有一列 holdout"):
        select_and_open_holdout(rows, SUPER)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("delta_ci_low", 0),
        ("delta_fixed_roi_mean", -0.0001),
        ("positive_replicate_rate", 0.7499),
        ("active_week_win_rate", 0.50),
    ],
)
def test_edge_gate_rejects_each_failed_boundary(field, value):
    holdout = _summary(SUPER, "holdout", "candidate", 0.1)
    assert edge_is_proven(holdout) is True
    holdout[field] = value
    assert edge_is_proven(holdout) is False


def test_holdout_seal_detects_data_policy_and_week_changes():
    contexts, policies, fingerprints = _contexts_policies_fingerprints()
    seal = create_holdout_seal(contexts, policies, fingerprints)
    assert verify_holdout_seal(seal, contexts, policies, fingerprints)
    assert len(seal["sha256"]) == 64

    changed_fingerprints = dict(fingerprints, super="c" * 64)
    assert not verify_holdout_seal(
        seal, contexts, policies, changed_fingerprints
    )
    changed_policies = {game: list(items) for game, items in policies.items()}
    changed_policies[SUPER] = list(reversed(changed_policies[SUPER]))
    # 政策順序不影響封存內容；政策本身改變才應失效。
    assert verify_holdout_seal(seal, contexts, changed_policies, fingerprints)
    changed_policies[SUPER][0] = Policy(
        "trained_blend", (CURRENT["hot"],) * 5
    )
    assert not verify_holdout_seal(
        seal, contexts, changed_policies, fingerprints
    )


def test_validation_holdout_gate_passes_and_rejects_tampering():
    rows = _summaries()
    selected = {
        game: select_and_open_holdout(rows, game)
        for game in (SUPER, LOTTO649)
    }
    contexts, policies, fingerprints = _contexts_policies_fingerprints()
    seal = create_holdout_seal(contexts, policies, fingerprints)
    gate = build_validation_holdout_gate(
        rows, selected, seal, contexts, policies, fingerprints
    )
    require_gate(gate)

    tampered = deepcopy(selected)
    tampered[SUPER]["policy_id"] = "random_5"
    failed = build_validation_holdout_gate(
        rows, tampered, seal, contexts, policies, fingerprints
    )
    with pytest.raises(StageGateError, match="super.validation_choice"):
        require_gate(failed)
