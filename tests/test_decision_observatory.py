from engine.decision_observatory import (
    ARM_QWEN,
    ARM_RANDOM,
    ARM_RULE,
    OPS_EXPERIMENT_ID,
    build_observatory,
)
from engine.games import LOTTO649, SUPER


def _registration(game, index, *, source="ollama", wall=1000, complete=True):
    telemetry = {
        "schema_version": "1",
        "outcome": "success" if source == "ollama" else "error",
        "wall_duration_ms": wall,
        "eval_count": 100,
        "eval_tokens_per_second": 20,
        "complete": complete,
    }
    diagnostics = {
        "main_number_union_size": 24,
        "source_agent_count": 5,
        "mean_pairwise_main_overlap": 0.6,
    }
    return {
        "ops_experiment_id": OPS_EXPERIMENT_ID,
        "game": game,
        "target": {
            "date": f"2099-01-{index + 1:02d}",
            "period": 188000000 + index,
        },
        "arms": {
            ARM_QWEN: {
                "source": source,
                "metadata": {
                    "telemetry": telemetry,
                    "selection_diagnostics": (
                        diagnostics if source == "ollama" else None
                    ),
                },
            }
        },
    }


def _settlement(game, index, registration_hash):
    return {
        "game": game,
        "registration_hash": registration_hash,
        "target": {
            "date": f"2099-01-{index + 1:02d}",
            "period": 188000000 + index,
        },
        "qwen_vs_rule": {"eligible": True},
        "arm_results": {
            ARM_QWEN: {"best_main_hits": 3},
            ARM_RULE: {"best_main_hits": 2},
            ARM_RANDOM: {"best_main_hits": 1},
        },
    }


def _healthy_inputs():
    registrations = {}
    settlements = []
    for game in (SUPER, LOTTO649):
        for index in range(10):
            key = f"{game}-{index}"
            registrations[key] = _registration(game, index)
            settlements.append(_settlement(game, index, key))
    return registrations, settlements


def test_healthy_operations_plus_supported_performance_allows_shadow_review():
    registrations, settlements = _healthy_inputs()

    result = build_observatory(
        registrations,
        settlements,
        performance_status="qwen_advantage_supported",
    )

    assert result["experiment_id"] == OPS_EXPERIMENT_ID
    assert result["deployment_gate"] == {
        "performance_status": "qwen_advantage_supported",
        "operations_ready": True,
        "status": "eligible_for_qwen_shadow_promotion",
        "recommendation": "qwen_shadow_with_rule_control",
    }
    for game in (SUPER, LOTTO649):
        summary = result["games"][game]
        assert summary["status"] == "operationally_healthy"
        assert summary["fallback_rate"] == 0
        assert summary["telemetry_completeness"] == 1
        assert summary["latency_ms"]["p95"] == 1000
        assert summary["quality"]["qwen_minus_rule_best_main_hits"] == 1
        assert summary["quality"]["qwen_minus_random_best_main_hits"] == 2


def test_fallback_and_latency_breach_block_operational_gate():
    registrations, settlements = _healthy_inputs()
    registrations[f"{SUPER}-0"] = _registration(
        SUPER,
        0,
        source="deterministic_fallback",
    )
    registrations[f"{SUPER}-1"] = _registration(
        SUPER,
        1,
        wall=600_000,
    )

    result = build_observatory(
        registrations,
        settlements,
        performance_status="qwen_advantage_supported",
    )
    game = result["games"][SUPER]

    assert game["status"] == "operationally_degraded"
    assert game["fallback_rate"] == 0.1
    assert game["latency_ms"]["p95"] > 300_000
    assert game["gates"]["latency"] is False
    assert "latency_p95_high" in game["alerts"]
    assert (
        result["deployment_gate"]["status"]
        == "blocked_by_operational_quality"
    )


def test_legacy_registrations_are_reported_but_never_backfilled():
    registrations, settlements = _healthy_inputs()
    registrations["legacy"] = {
        "game": SUPER,
        "target": {"date": "2098-12-31", "period": 1},
        "arms": {ARM_QWEN: {"source": "ollama", "metadata": {}}},
    }

    result = build_observatory(
        registrations,
        settlements,
        performance_status="collecting_forward_data",
    )

    assert result["games"][SUPER]["legacy_uninstrumented_registrations"] == 1
    assert result["games"][SUPER]["instrumented_registrations"] == 10
    assert (
        result["deployment_gate"]["status"]
        == "collecting_joint_evidence"
    )


def test_incomplete_telemetry_is_a_visible_operational_failure():
    registrations, settlements = _healthy_inputs()
    registrations[f"{LOTTO649}-0"] = _registration(
        LOTTO649,
        0,
        complete=False,
    )
    registrations[f"{LOTTO649}-1"] = _registration(
        LOTTO649,
        1,
        complete=False,
    )

    result = build_observatory(
        registrations,
        settlements,
        performance_status="qwen_advantage_supported",
    )
    game = result["games"][LOTTO649]

    assert game["telemetry_completeness"] == 0.8
    assert game["gates"]["telemetry_complete"] is False
    assert "telemetry_incomplete" in game["alerts"]
    assert game["status"] == "operationally_degraded"


def test_insufficient_samples_stay_collecting_even_when_first_call_succeeds():
    registrations = {"one": _registration(SUPER, 0)}

    result = build_observatory(
        registrations,
        [],
        performance_status="qwen_advantage_supported",
    )

    assert (
        result["games"][SUPER]["status"]
        == "collecting_operational_data"
    )
    assert result["games"][SUPER]["window_attempts"] == 1
    assert result["games"][LOTTO649]["window_attempts"] == 0
    assert (
        result["deployment_gate"]["recommendation"]
        == "keep_rule_as_control"
    )
