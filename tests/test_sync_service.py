from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from engine.games import LOTTO649, SUPER
from engine.sync_service import (
    _null_safe_probability_stale,
    _probability_stacking_stale,
    _refresh_null_safe_probability,
    _shadow_research_stale,
    _switching_bayes_stale,
    compare_draw_counts,
    sync_latest,
)
from engine.agent_loop import canonical_hash
from research.label_signal import RANKER_NAMES
from research.mechanism_signal import MAIN_CANDIDATES
from research.partition_signal import PARTITIONER_NAMES
from research.structural_optimum import structural_proof_reference


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


def test_probability_stacking_staleness_tracks_draws_and_ledger_hashes(
    tmp_path,
):
    source = (
        Path(__file__).parent.parent
        / "research"
        / "results"
        / "probability_stacking.json"
    )
    study = json.loads(source.read_text(encoding="utf-8"))
    results = tmp_path / "research" / "results"
    results.mkdir(parents=True)
    target = results / "probability_stacking.json"
    target.write_text(
        json.dumps(study),
        encoding="utf-8",
    )
    strength = json.loads(
        (
            Path(__file__).parent.parent
            / "research"
            / "results"
            / "decision_strength.json"
        ).read_text(encoding="utf-8")
    )
    manifest = _manifest()
    for game in (SUPER, LOTTO649):
        manifest["games"][game]["last_target"]["date"] = study[
            "data_quality"
        ]["source_last_dates"][game]
    strength["source"]["manifest_hash"] = manifest["manifest_hash"]
    strength_payload = {
        key: value
        for key, value in strength.items()
        if key != "audit_hash"
    }
    strength["audit_hash"] = canonical_hash(strength_payload)
    (results / "decision_strength.json").write_text(
        json.dumps(strength),
        encoding="utf-8",
    )

    assert (
        _probability_stacking_stale(tmp_path, manifest)
        is False
    )
    output = tmp_path / "simulation" / "results"
    output.mkdir(parents=True)
    for game in (SUPER, LOTTO649):
        (output / f"{game}.jsonl").write_text(
            "rewritten\n",
            encoding="utf-8",
        )
    assert _probability_stacking_stale(tmp_path, manifest) is True

    manifest["games"][SUPER]["last_target"]["date"] = "2099-01-01"
    assert (
        _probability_stacking_stale(tmp_path, manifest)
        is True
    )


def test_null_safe_staleness_tracks_candidate_draws_and_ledger_hashes(
    tmp_path,
):
    source = (
        Path(__file__).parent.parent
        / "research"
        / "results"
        / "null_safe_probability.json"
    )
    study = json.loads(source.read_text(encoding="utf-8"))
    results = tmp_path / "research" / "results"
    results.mkdir(parents=True)
    target = results / "null_safe_probability.json"
    target.write_text(json.dumps(study), encoding="utf-8")
    stacking_source = (
        Path(__file__).parent.parent
        / "research"
        / "results"
        / "probability_stacking.json"
    )
    (results / "probability_stacking.json").write_text(
        stacking_source.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    manifest = _manifest()
    for game in (SUPER, LOTTO649):
        manifest["games"][game]["last_target"]["date"] = study[
            "data_quality"
        ]["source_last_dates"][game]

    assert _null_safe_probability_stale(tmp_path, manifest) is False

    output = tmp_path / "simulation" / "results"
    output.mkdir(parents=True)
    for game in (SUPER, LOTTO649):
        (output / f"{game}.jsonl").write_text(
            "rewritten\n",
            encoding="utf-8",
        )
    assert _null_safe_probability_stale(tmp_path, manifest) is True

    manifest["games"][LOTTO649]["last_target"]["date"] = (
        "2099-01-01"
    )
    assert _null_safe_probability_stale(tmp_path, manifest) is True


def test_switching_bayes_staleness_tracks_draws_and_ledger_hashes(
    tmp_path,
):
    source = (
        Path(__file__).parent.parent
        / "research"
        / "results"
        / "switching_bayes.json"
    )
    study = json.loads(source.read_text(encoding="utf-8"))
    results = tmp_path / "research" / "results"
    results.mkdir(parents=True)
    target = results / "switching_bayes.json"
    target.write_text(json.dumps(study), encoding="utf-8")
    manifest = _manifest()
    for game in (SUPER, LOTTO649):
        manifest["games"][game]["last_target"]["date"] = study[
            "data_quality"
        ]["source_last_dates"][game]

    assert _switching_bayes_stale(tmp_path, manifest) is False
    output = tmp_path / "simulation" / "results"
    output.mkdir(parents=True)
    for game in (SUPER, LOTTO649):
        (output / f"{game}.jsonl").write_text(
            "rewritten\n",
            encoding="utf-8",
        )
    assert _switching_bayes_stale(tmp_path, manifest) is True

    manifest["games"][SUPER]["last_target"]["date"] = "2099-01-01"
    assert _switching_bayes_stale(tmp_path, manifest) is True

    target.unlink()
    assert _switching_bayes_stale(tmp_path, manifest) is False

    manifest["games"][LOTTO649]["last_target"]["date"] = study[
        "data_quality"
    ]["source_last_dates"][LOTTO649]
    study["future_forward_shadow_candidate"]["candidate_hash"] = (
        "0" * 64
    )
    target.write_text(json.dumps(study), encoding="utf-8")
    assert _null_safe_probability_stale(tmp_path, manifest) is True


def test_null_safe_operational_state_is_validated_before_freshness(
    tmp_path,
):
    from research.null_safe_probability import (
        build_forward_state_artifact,
    )

    base = Path(__file__).parent.parent
    results = tmp_path / "research" / "results"
    results.mkdir(parents=True)
    formal = json.loads(
        (
            base
            / "research"
            / "results"
            / "null_safe_probability.json"
        ).read_text(encoding="utf-8")
    )
    stacking_study = json.loads(
        (
            base
            / "research"
            / "results"
            / "probability_stacking.json"
        ).read_text(encoding="utf-8")
    )
    (results / "null_safe_probability.json").write_text(
        json.dumps(formal),
        encoding="utf-8",
    )
    (results / "probability_stacking.json").write_text(
        json.dumps(stacking_study),
        encoding="utf-8",
    )
    artifact = build_forward_state_artifact(
        formal["future_forward_shadow_candidate"],
        stacking_study["future_forward_shadow_candidate"],
        [],
    )
    path = results / "null_safe_probability_forward.json"
    path.write_text(json.dumps(artifact), encoding="utf-8")
    manifest = _manifest()
    for game in (SUPER, LOTTO649):
        manifest["games"][game]["last_target"]["date"] = artifact[
            "future_forward_shadow_candidate"
        ]["fitted_through"][game]

    assert _null_safe_probability_stale(tmp_path, manifest) is False

    artifact["state_hash"] = "0" * 64
    path.write_text(json.dumps(artifact), encoding="utf-8")
    assert _null_safe_probability_stale(tmp_path, manifest) is True


def test_refresh_null_safe_state_does_not_backfill_v6_settlement(
    tmp_path,
    monkeypatch,
):
    base = Path(__file__).parent.parent
    results = tmp_path / "research" / "results"
    results.mkdir(parents=True)
    formal = json.loads(
        (
            base
            / "research"
            / "results"
            / "null_safe_probability.json"
        ).read_text(encoding="utf-8")
    )
    stacking_study = json.loads(
        (
            base
            / "research"
            / "results"
            / "probability_stacking.json"
        ).read_text(encoding="utf-8")
    )
    stacking = deepcopy(
        stacking_study["future_forward_shadow_candidate"]
    )
    stacking.pop("candidate_hash")
    stacking["fitted_through"] = {
        SUPER: "2099-01-01",
        LOTTO649: "2099-01-02",
    }
    stacking["candidate_hash"] = canonical_hash(stacking)
    stacking_study["future_forward_shadow_candidate"] = stacking
    (results / "null_safe_probability.json").write_text(
        json.dumps(formal),
        encoding="utf-8",
    )
    (results / "probability_stacking.json").write_text(
        json.dumps(stacking_study),
        encoding="utf-8",
    )

    class FakeLedger:
        def events_of(self, event_type):
            assert event_type == "forward_settlement"
            return [
                {
                    "content": {
                        "game": SUPER,
                        "target": {
                            "date": "2099-01-01",
                            "period": 990001,
                        },
                        "registration_hash": "a" * 64,
                        "probability_stacking_shadow": {},
                    }
                }
            ]

    monkeypatch.setattr(
        "engine.sync_service.forward_lab.forward_ledger",
        lambda base: FakeLedger(),
    )
    monkeypatch.setattr(
        "engine.sync_service.forward_lab.verify_registry",
        lambda ledger: {"chain_valid": True},
    )

    result = _refresh_null_safe_probability(
        tmp_path,
        tmp_path / "simulation" / "results",
    )
    artifact = json.loads(
        (
            results / "null_safe_probability_forward.json"
        ).read_text(encoding="utf-8")
    )
    candidate = artifact["future_forward_shadow_candidate"]
    prior = formal["future_forward_shadow_candidate"]

    assert result["applied_transitions"] == 0
    assert result["registered_score_capsules"] == 0
    assert candidate["fitted_through"] == stacking["fitted_through"]
    for game in (SUPER, LOTTO649):
        assert (
            candidate["models"][game]["main_e_process"]
            == prior["models"][game]["main_e_process"]
        )
    assert (
        candidate["models"][SUPER]["special_e_process"]
        == prior["models"][SUPER]["special_e_process"]
    )

    repeated = _refresh_null_safe_probability(
        tmp_path,
        tmp_path / "simulation" / "results",
    )
    repeated_artifact = json.loads(
        (
            results / "null_safe_probability_forward.json"
        ).read_text(encoding="utf-8")
    )
    assert repeated["candidate_hash"] == result["candidate_hash"]
    assert repeated_artifact == artifact


def test_shadow_bundle_requires_both_current_research_results(tmp_path):
    results = tmp_path / "research" / "results"
    results.mkdir(parents=True)
    manifest = _manifest()
    source_dates = {
        game: manifest["games"][game]["last_target"]["date"]
        for game in (SUPER, LOTTO649)
    }
    council_payload = {
        "data_quality": {"source_last_dates": source_dates}
    }
    (results / "council_quality.json").write_text(
        json.dumps(council_payload), encoding="utf-8"
    )

    assert _shadow_research_stale(tmp_path, manifest) is True

    max_coverage_payload = {
        "schema_version": "1",
        "methodology": {
            "structural_optimum_proof": structural_proof_reference()
        },
        "data_quality": {"source_last_dates": dict(source_dates)},
        "summary": [
            {
                "proposal_coverage_exact_any_prize": 0.1,
                "max_coverage_exact_any_prize": 0.2,
                (
                    "minimum_max_minus_"
                    "proposal_coverage_exact_any_prize"
                ): 0.0,
                "structural_non_decrease_rate": 1.0,
            }
            for _ in range(4)
        ],
    }
    (results / "max_coverage.json").write_text(
        json.dumps(max_coverage_payload), encoding="utf-8"
    )
    assert _shadow_research_stale(tmp_path, manifest) is True

    label_signal_payload = {
        "schema_version": "1",
        "methodology": {
            "rankers": list(RANKER_NAMES),
            "structural_optimum_proof": structural_proof_reference(),
        },
        "data_quality": {"source_last_dates": dict(source_dates)},
        "summary": [{} for _ in range(2 * 2 * len(RANKER_NAMES))],
        "conclusion": {
            "status": "retain_consensus_label_ranking"
        },
    }
    (results / "label_signal.json").write_text(
        json.dumps(label_signal_payload), encoding="utf-8"
    )
    assert _shadow_research_stale(tmp_path, manifest) is True

    partition_signal_payload = {
        "schema_version": "1",
        "methodology": {
            "partitioners": list(PARTITIONER_NAMES),
            "structural_optimum_proof": structural_proof_reference(),
        },
        "data_quality": {"source_last_dates": dict(source_dates)},
        "summary": [
            {} for _ in range(2 * 2 * len(PARTITIONER_NAMES))
        ],
        "conclusion": {
            "status": "retain_round_robin_partition"
        },
    }
    (results / "partition_signal.json").write_text(
        json.dumps(partition_signal_payload), encoding="utf-8"
    )
    assert _shadow_research_stale(tmp_path, manifest) is True

    mechanism_signal_payload = {
        "schema_version": "1",
        "methodology": {
            "main_candidates": {
                game: list(candidates)
                for game, candidates in MAIN_CANDIDATES.items()
            },
            "structural_optimum_proof": structural_proof_reference(),
        },
        "data_quality": {"source_last_dates": dict(source_dates)},
        "conclusion": {
            "status": "retain_current_label_and_special_ranking"
        },
        "future_forward_shadow_candidate": {
            "candidate_hash": "a" * 64,
            "use": "future_forward_shadow_only",
        },
        "future_profit_common_special_shadow_candidate": (
            json.loads(
                (
                    Path(__file__).parent.parent
                    / "research"
                    / "results"
                    / "mechanism_signal.json"
                ).read_text(encoding="utf-8")
            )[
                "future_profit_common_special_shadow_candidate"
            ]
        ),
    }
    (results / "mechanism_signal.json").write_text(
        json.dumps(mechanism_signal_payload), encoding="utf-8"
    )
    assert _shadow_research_stale(tmp_path, manifest) is False

    output = tmp_path / "simulation" / "results"
    output.mkdir(parents=True)
    ledger_hashes = {}
    for game in (SUPER, LOTTO649):
        ledger_path = output / f"{game}.jsonl"
        ledger_path.write_bytes(f"{game}-ledger".encode())
        ledger_hashes[game] = hashlib.sha256(
            ledger_path.read_bytes()
        ).hexdigest()
    assert _shadow_research_stale(tmp_path, manifest) is True

    payloads = {
        "council_quality.json": council_payload,
        "max_coverage.json": max_coverage_payload,
        "label_signal.json": label_signal_payload,
        "partition_signal.json": partition_signal_payload,
        "mechanism_signal.json": mechanism_signal_payload,
    }
    verification = {
        game: {"ledger_sha256": ledger_hashes[game]}
        for game in (SUPER, LOTTO649)
    }
    for name, payload in payloads.items():
        payload["data_quality"]["ledger_verification"] = deepcopy(
            verification
        )
        (results / name).write_text(
            json.dumps(payload), encoding="utf-8"
        )
    assert _shadow_research_stale(tmp_path, manifest) is False

    (output / f"{SUPER}.jsonl").write_bytes(b"rewritten-ledger")
    assert _shadow_research_stale(tmp_path, manifest) is True
    (output / f"{SUPER}.jsonl").write_bytes(
        f"{SUPER}-ledger".encode()
    )

    max_coverage_payload["data_quality"]["source_last_dates"][
        SUPER
    ] = "2000-01-01"
    (results / "max_coverage.json").write_text(
        json.dumps(max_coverage_payload), encoding="utf-8"
    )
    assert _shadow_research_stale(tmp_path, manifest) is True


def test_shadow_bundle_rejects_legacy_coverage_schema(tmp_path):
    results = tmp_path / "research" / "results"
    results.mkdir(parents=True)
    manifest = _manifest()
    source_dates = {
        game: manifest["games"][game]["last_target"]["date"]
        for game in (SUPER, LOTTO649)
    }
    payload = {
        "schema_version": "0",
        "data_quality": {"source_last_dates": source_dates},
        "summary": [],
    }
    for name in (
        "council_quality.json",
        "max_coverage.json",
        "label_signal.json",
        "partition_signal.json",
        "mechanism_signal.json",
    ):
        (results / name).write_text(
            json.dumps(payload), encoding="utf-8"
        )

    assert _shadow_research_stale(tmp_path, manifest) is True


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


def test_sync_refreshes_stale_shadow_research_only_after_registration(
    tmp_path,
    monkeypatch,
):
    output = tmp_path / "simulation" / "results"
    output.mkdir(parents=True)
    for game in (SUPER, LOTTO649):
        (output / f"{game}.jsonl").write_text("{}\n", encoding="utf-8")

    class FakeStore:
        def draws(self, game):
            return [object()] * ({SUPER: 11, LOTTO649: 20}[game])

    class FakeEnv:
        def __init__(self, base):
            self.data_dir = base / "data"
            self.store = FakeStore()

    monkeypatch.setattr("engine.sync_service.Env", FakeEnv)
    order = []

    def runner(store, output_dir, feedback_provider):
        order.append("runner")
        return _manifest(11, 20)

    def register(base, store, manifest):
        order.append("register")
        return _forward_result()

    def research(base, output_dir):
        order.append("research")
        return {
            "experiment_id": "council-quality-shadow-v1",
            "status": "retain_current_council",
        }

    def calibrate(base, output_dir):
        order.append("calibrate")
        return {
            "experiment_id": "online-probability-stacking-shadow-v1",
            "status": "future_shadow_only",
        }

    def gate(base, output_dir):
        order.append("gate")
        return {
            "experiment_id": "null-safe-probability-gate-v1",
            "status": "candidate_ready_future_shadow",
        }

    phases = []
    result = sync_latest(
        tmp_path,
        fetcher=lambda game, data_dir: (1, 1),
        runner=runner,
        pre_settler=lambda base, store: {"settlements_created": 0},
        forward_syncer=register,
        shadow_researcher=research,
        probability_stacker=calibrate,
        null_safe_probability_stacker=gate,
        progress=lambda phase, message, details: phases.append(phase),
    )

    assert order == [
        "runner",
        "calibrate",
        "gate",
        "register",
        "research",
    ]
    assert result["probability_stacking"]["status"] == (
        "future_shadow_only"
    )
    assert result["shadow_research"]["status"] == (
        "retain_current_council"
    )
    assert result["null_safe_probability"]["status"] == (
        "candidate_ready_future_shadow"
    )
    assert phases == [
        "checking",
        "reviewing",
        "optimizing",
        "calibrating",
        "gating",
        "preregistering",
        "researching",
        "ready",
    ]


def test_stale_shadow_research_retries_without_new_draws(
    tmp_path,
    monkeypatch,
):
    output = tmp_path / "simulation" / "results"
    output.mkdir(parents=True)
    (output / "manifest.json").write_text(
        json.dumps(_manifest()), encoding="utf-8"
    )
    for game in (SUPER, LOTTO649):
        (output / f"{game}.jsonl").write_text("{}\n", encoding="utf-8")

    class FakeStore:
        def draws(self, game):
            return [object()] * ({SUPER: 10, LOTTO649: 20}[game])

    class FakeEnv:
        def __init__(self, base):
            self.data_dir = base / "data"
            self.store = FakeStore()

    monkeypatch.setattr("engine.sync_service.Env", FakeEnv)
    calls = []
    result = sync_latest(
        tmp_path,
        fetcher=lambda game, data_dir: (1, 1),
        runner=lambda *args: (_ for _ in ()).throw(
            AssertionError("沒有新開獎不得重建正式決策")
        ),
        forward_syncer=lambda base, store, manifest: _forward_result(),
        shadow_researcher=lambda base, output_dir: calls.append(
            (base, output_dir)
        )
        or {"status": "refreshed"},
        probability_stacker=lambda base, output_dir: {
            "status": "future_shadow_only"
        },
        null_safe_probability_stacker=lambda base, output_dir: {
            "status": "candidate_ready_future_shadow"
        },
    )

    assert result["new_draws_total"] == 0
    assert result["regenerated"] is False
    assert result["shadow_research"] == {"status": "refreshed"}
    assert len(calls) == 1
