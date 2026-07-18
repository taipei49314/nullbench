import json

import pytest

from engine.games import LOTTO649, SUPER
from engine.sync_service import compare_draw_counts, sync_latest


def test_compare_draw_counts_detects_only_new_draws():
    assert compare_draw_counts(
        {SUPER: 10, LOTTO649: 20},
        {SUPER: 11, LOTTO649: 20},
    ) == {SUPER: 1, LOTTO649: 0}


def test_compare_draw_counts_fails_closed_on_regression():
    with pytest.raises(ValueError, match="期數倒退"):
        compare_draw_counts(
            {SUPER: 10, LOTTO649: 20},
            {SUPER: 9, LOTTO649: 20},
        )


def _manifest(super_count=10, lotto_count=20):
    def game_payload(count):
        return {
            "draws_replayed": count,
            "last_target": {"date": "2026-07-17", "period": count},
            "next_decision": {
                "target": {"date": "2026-07-20", "period": count + 1},
                "adjudication": {
                    "judge": {
                        "feedback_provenance": {
                            "experiment_id": "settled-forward-feedback-v1",
                            "status": "verified_empty",
                            "feedback_hash": "feedback-sha",
                            "settlement_count": 0,
                            "as_of_target": None,
                            "source_postmortem_hashes": [],
                        }
                    }
                },
            },
        }

    return {
        "games": {
            SUPER: game_payload(super_count),
            LOTTO649: game_payload(lotto_count),
        },
        "manifest_hash": "verified-hash",
    }


def _forward_result():
    return {
        "settlements_created": 0,
        "registrations": {
            SUPER: {"status": "created", "registration_hash": "super-sha"},
            LOTTO649: {
                "status": "created",
                "registration_hash": "lotto-sha",
            },
        },
        "summary": {
            "evidence_status": "collecting_forward_data",
            "recommendation": "keep_rule_as_control",
            "verification": {
                "chain_valid": True,
                "events": 2,
                "registrations": 2,
                "settlements": 0,
                "pending": 2,
            },
            "feedback_memory": {
                SUPER: {"settlement_count": 1},
                LOTTO649: {"settlement_count": 0},
            },
            "operations": {
                "deployment_gate": {
                    "status": "collecting_joint_evidence",
                    "recommendation": "keep_rule_as_control",
                }
            },
        },
    }


def test_sync_rebuilds_only_when_new_draws_exist(tmp_path, monkeypatch):
    output = tmp_path / "simulation" / "results"
    output.mkdir(parents=True)
    (output / "manifest.json").write_text(
        json.dumps(_manifest()), encoding="utf-8"
    )

    class FakeStore:
        def draws(self, game):
            return [object()] * ({SUPER: 11, LOTTO649: 20}[game])

    class FakeEnv:
        def __init__(self, base):
            self.data_dir = base / "data"
            self.store = FakeStore()

    monkeypatch.setattr("engine.sync_service.Env", FakeEnv)
    phases = []
    runner_calls = []
    forward_calls = []
    feedback_calls = []
    order = []

    def pre_settler(base, store):
        order.append("settle")
        return {"settlements_created": 1}

    def feedback_loader(base, game, target):
        order.append("feedback")
        feedback_calls.append((base, game, target))
        return {
            "feedback_hash": f"{game}-feedback",
            "settlement_count": 1,
        }

    def runner(store, output_dir, feedback_provider):
        feedback = feedback_provider(
            SUPER,
            {"date": "2026-07-20", "period": 12},
        )
        order.append("runner")
        runner_calls.append((store, output_dir))
        assert feedback["feedback_hash"] == "super-feedback"
        return _manifest(11, 20)

    def forward_syncer(base, store, manifest):
        order.append("register")
        forward_calls.append((base, store, manifest))
        return _forward_result()

    result = sync_latest(
        tmp_path,
        fetcher=lambda game, data_dir: (1, 1),
        runner=runner,
        pre_settler=pre_settler,
        feedback_loader=feedback_loader,
        forward_syncer=forward_syncer,
        progress=lambda phase, message, details: phases.append(phase),
    )

    assert result["regenerated"] is True
    assert result["new_draws_total"] == 1
    assert result["games"][SUPER]["new_draws"] == 1
    assert len(runner_calls) == 1
    assert len(forward_calls) == 1
    assert len(feedback_calls) == 1
    assert order == ["settle", "feedback", "runner", "register"]
    assert (
        result["forward_experiment"]["settlements_before_decision"]
        == 1
    )
    assert result["forward_experiment"]["settlements_created"] == 1
    assert result["forward_experiment"]["evidence_status"] == (
        "collecting_forward_data"
    )
    assert result["forward_experiment"]["deployment_gate"]["status"] == (
        "collecting_joint_evidence"
    )
    assert phases == [
        "checking",
        "reviewing",
        "optimizing",
        "preregistering",
        "ready",
    ]


def test_sync_keeps_verified_artifacts_when_counts_are_unchanged(
    tmp_path, monkeypatch
):
    output = tmp_path / "simulation" / "results"
    output.mkdir(parents=True)
    (output / "manifest.json").write_text(
        json.dumps(_manifest()), encoding="utf-8"
    )

    class FakeStore:
        def draws(self, game):
            return [object()] * ({SUPER: 10, LOTTO649: 20}[game])

    class FakeEnv:
        def __init__(self, base):
            self.data_dir = base / "data"
            self.store = FakeStore()

    monkeypatch.setattr("engine.sync_service.Env", FakeEnv)

    def unexpected_runner(store, output_dir, feedback_provider):
        raise AssertionError("沒有新開獎時不應重建")

    phases = []
    pre_settle_calls = []
    result = sync_latest(
        tmp_path,
        fetcher=lambda game, data_dir: (1, 1),
        runner=unexpected_runner,
        pre_settler=lambda base, store: pre_settle_calls.append(
            (base, store)
        ),
        forward_syncer=lambda base, store, manifest: _forward_result(),
        progress=lambda phase, message, details: phases.append(phase),
    )

    assert result["regenerated"] is False
    assert result["new_draws_total"] == 0
    assert pre_settle_calls == []
    assert (
        result["forward_experiment"]["settlements_before_decision"]
        == 0
    )
    assert result["forward_experiment"]["verification"]["chain_valid"] is True
    assert phases == ["checking", "preregistering", "ready"]


def test_sync_never_registers_new_target_when_decision_rebuild_fails(
    tmp_path,
    monkeypatch,
):
    output = tmp_path / "simulation" / "results"
    output.mkdir(parents=True)
    (output / "manifest.json").write_text(
        json.dumps(_manifest()), encoding="utf-8"
    )

    class FakeStore:
        def draws(self, game):
            return [object()] * ({SUPER: 11, LOTTO649: 20}[game])

    class FakeEnv:
        def __init__(self, base):
            self.data_dir = base / "data"
            self.store = FakeStore()

    monkeypatch.setattr("engine.sync_service.Env", FakeEnv)
    registered = []

    def broken_runner(store, output_dir, feedback_provider):
        feedback_provider(
            SUPER,
            {"date": "2026-07-20", "period": 12},
        )
        raise RuntimeError("qwen failed")

    with pytest.raises(RuntimeError, match="qwen failed"):
        sync_latest(
            tmp_path,
            fetcher=lambda game, data_dir: (1, 1),
            pre_settler=lambda base, store: {
                "settlements_created": 1
            },
            feedback_loader=lambda base, game, target: {
                "feedback_hash": "verified"
            },
            runner=broken_runner,
            forward_syncer=lambda *args: registered.append(args),
        )

    assert registered == []
