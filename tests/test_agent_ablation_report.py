"""Agent 數量消融報告 artifact 與正式驗收門檻。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import agent_ablation_verify
from research.agent_ablation_artifact import build_artifact


BASE = Path(__file__).parent.parent
RESULTS = BASE / "research" / "results"


def test_committed_artifact_has_answer_first_structure_and_native_evidence():
    if not (RESULTS / "agent_ablation.json").exists():
        pytest.skip("正式 Agent 消融結果尚未產生")
    artifact = build_artifact(RESULTS)
    manifest = artifact["manifest"]
    snapshot = artifact["snapshot"]

    assert artifact["surface"] == "report"
    assert manifest["title"] == "Agent 數量消融測試"
    assert manifest["blocks"][0]["type"] == "markdown"
    assert manifest["blocks"][0]["body"] == f"# {manifest['title']}"
    assert manifest["blocks"][1]["body"].startswith("## Executive Summary")
    assert any(block["type"] == "chart" for block in manifest["blocks"])
    assert manifest["charts"]
    assert manifest["tables"]
    assert all("defaultSort" in table for table in manifest["tables"])
    assert snapshot["status"] == "ready"
    assert all(
        isinstance(rows, list) for rows in snapshot["datasets"].values()
    )
    assert {row["agent_count"] for row in snapshot["datasets"]["count_holdout"]} == {
        2,
        3,
        4,
        5,
    }


def _formal_result() -> dict:
    return {
        "methodology": {
            "agent_subsets": 26,
            "warmup_draws": 60,
            "null_replicates_per_draw": 200,
            "bootstrap_samples": 2_000,
            "bootstrap_block_draws": 13,
        },
        "data_quality": {
            "status": "pass",
            "split_profiles": {
                "super": {"holdout_draws": 561},
                "lotto649": {"holdout_draws": 628},
            },
        },
        "records_integrity": {
            "unchanged": True,
            "before_sha256": "a" * 64,
            "after_sha256": "a" * 64,
        },
        "count_summary": [
            {"game": game, "split": split, "agent_count": size}
            for game in ("super", "lotto649")
            for split in ("development", "holdout")
            for size in range(2, 6)
        ],
        "conclusion": {"status": "not_supported"},
    }


def test_formal_result_requires_full_configuration_and_all_gates():
    agent_ablation_verify.verify_formal_result(_formal_result())


@pytest.mark.parametrize(
    "mutation",
    [
        lambda result: result["methodology"].update(
            {"null_replicates_per_draw": 20}
        ),
        lambda result: result["methodology"].update(
            {"bootstrap_samples": 200}
        ),
        lambda result: result["data_quality"].update({"status": "fail"}),
        lambda result: result["records_integrity"].update(
            {"unchanged": False}
        ),
        lambda result: result.update({"count_summary": []}),
        lambda result: result["conclusion"].update({"status": "unknown"}),
    ],
)
def test_formal_result_rejects_incomplete_or_failed_run(mutation):
    result = _formal_result()
    mutation(result)
    with pytest.raises(RuntimeError, match="Agent 消融正式驗收失敗"):
        agent_ablation_verify.verify_formal_result(result)


def test_committed_result_is_valid_json_and_records_are_unchanged():
    if not (RESULTS / "agent_ablation.json").exists():
        pytest.skip("正式 Agent 消融結果尚未產生")
    result = json.loads(
        (RESULTS / "agent_ablation.json").read_text(encoding="utf-8")
    )
    assert result["records_integrity"]["unchanged"] is True
    assert result["data_quality"]["status"] == "pass"
