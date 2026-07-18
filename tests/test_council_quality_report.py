"""Agent 品質影子研究正式輸出與驗收門檻。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import council_quality_verify


BASE = Path(__file__).parent.parent
RESULT = BASE / "research" / "results" / "council_quality.json"
AGENTS = (
    "antipop_taoist",
    "balance_engineer",
    "cold_keeper",
    "hot_hunter",
    "random_monk",
)


def _formal_result() -> dict:
    agent_rows = [
        {"game": game, "split": split, "agent": agent}
        for game in ("super", "lotto649")
        for split in ("development", "holdout")
        for agent in AGENTS
    ]
    return {
        "methodology": {
            "warmup_draws": 60,
            "bootstrap_samples": 2_000,
            "bootstrap_block_draws": 13,
            "candidate_agent": "coverage_auditor",
            "candidate_proposals_per_draw": 3,
            "candidate_search_samples_per_proposal": 160,
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
        "agent_quality": agent_rows,
        "critic_quality": [{}] * 20,
        "critic_pair_redundancy": [{}] * 40,
        "judge_sensitivity": [{}] * 20,
        "selected_replacements": {
            game: {
                "development": {"agent": "antipop_taoist"},
                "holdout": {"agent": "antipop_taoist"},
            }
            for game in ("super", "lotto649")
        },
        "recent_holdout_trace": {
            "super": [{"period": 1}],
            "lotto649": [{"period": 1}],
        },
        "conclusion": {"status": "retain_current_council"},
    }


def test_formal_result_requires_all_quality_and_integrity_gates():
    council_quality_verify.verify_formal_result(_formal_result())


@pytest.mark.parametrize(
    "mutation",
    [
        lambda result: result["methodology"].update(
            {"bootstrap_samples": 200}
        ),
        lambda result: result["data_quality"].update({"status": "fail"}),
        lambda result: result["records_integrity"].update(
            {"unchanged": False}
        ),
        lambda result: result.update({"agent_quality": []}),
        lambda result: result.update({"critic_quality": []}),
        lambda result: result["selected_replacements"]["super"][
            "holdout"
        ].update({"agent": "random_monk"}),
        lambda result: result.update({"recent_holdout_trace": {}}),
        lambda result: result["conclusion"].update({"status": "unknown"}),
    ],
)
def test_formal_result_rejects_incomplete_or_failed_run(mutation):
    result = _formal_result()
    mutation(result)
    with pytest.raises(RuntimeError, match="正式驗收失敗"):
        council_quality_verify.verify_formal_result(result)


def test_committed_result_is_safe_summary_without_raw_ticket_numbers():
    if not RESULT.exists():
        pytest.skip("正式 Agent 品質研究尚未產生")
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    council_quality_verify.verify_formal_result(result)
    serialized = json.dumps(result, ensure_ascii=False)

    assert result["records_integrity"]["unchanged"] is True
    assert result["data_quality"]["status"] == "pass"
    assert '"selected_tickets"' not in serialized
    assert '"numbers"' not in serialized
