"""階段 4：決策、報告、來源與正式帳本不變性測試。"""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from research.artifact import build_artifact, write_artifact
from research.gates import (
    StageGateError,
    build_decision_report_gate,
    require_gate,
    tree_sha256,
)


BASE = Path(__file__).parent.parent
RESULTS = BASE / "research" / "results"


def _load_study():
    study = json.loads(
        (RESULTS / "strategy_research.json").read_text(encoding="utf-8")
    )
    study["stage_gates"] = {
        "data_quality": {"status": "pass"},
        "strategy_search": {"status": "pass"},
        "validation_holdout": {"status": "pass"},
    }
    return study


def _gate(study, artifact, before="a" * 64, after="a" * 64, output=None):
    return build_decision_report_gate(
        study,
        artifact,
        before,
        after,
        BASE,
        output or RESULTS,
    )


def test_tree_hash_is_stable_and_content_sensitive(tmp_path):
    root = tmp_path / "records"
    root.mkdir()
    (root / "b.txt").write_text("two", encoding="utf-8")
    (root / "a.txt").write_text("one", encoding="utf-8")
    first = tree_sha256(root)
    second = tree_sha256(root)
    assert first == second
    assert len(first) == 64
    (root / "a.txt").write_text("changed", encoding="utf-8")
    assert tree_sha256(root) != first


def test_artifact_structure_and_snapshot_match_study():
    study = _load_study()
    artifact = build_artifact(RESULTS)
    manifest = artifact["manifest"]
    snapshot = artifact["snapshot"]
    assert manifest["blocks"][0]["body"] == f"# {manifest['title']}"
    assert manifest["charts"] and manifest["tables"]
    assert snapshot["status"] == "ready"
    assert len(snapshot["datasets"]["policy_holdout"]) == 10
    rows = {
        row["game"]: row for row in snapshot["datasets"]["decision_rows"]
    }
    for game, selected in study["selected"].items():
        assert rows[game]["selected_policy"] == selected["policy_id"]
        assert rows[game]["conditional_decision"] == selected[
            "conditional_decision"
        ]
        assert rows[game]["edge_proven"] == (
            "已證明" if selected["edge_proven"] else "未證明"
        )


def test_chart_and_table_sources_are_actual_select_queries():
    artifact = build_artifact(RESULTS)
    widgets = artifact["manifest"]["charts"] + artifact["manifest"]["tables"]
    assert widgets
    for widget in widgets:
        query = widget["source"]["query"]
        assert query["language"] == "sql"
        assert query["sql"].lstrip().upper().startswith("SELECT")
        assert query["tables_used"] == [
            "research/results/strategy_summary.csv"
        ]


def test_decision_report_gate_passes_complete_artifact():
    study = _load_study()
    artifact = build_artifact(RESULTS)
    gate = _gate(study, artifact)
    require_gate(gate)
    assert gate["status"] == "pass"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda study, artifact: study["decision"].update(
            {"economic": "buy"}
        ),
        lambda study, artifact: study["decision"][
            "conditional_simulation"
        ].update({"super": "trained_blend"}),
        lambda study, artifact: artifact["manifest"].update({"charts": []}),
        lambda study, artifact: artifact["snapshot"].update(
            {"status": "partial"}
        ),
        lambda study, artifact: artifact["snapshot"]["datasets"][
            "decision_rows"
        ].pop(),
    ],
)
def test_decision_report_gate_rejects_tampering(mutation):
    study = _load_study()
    artifact = build_artifact(RESULTS)
    mutation(study, artifact)
    gate = _gate(study, artifact)
    with pytest.raises(StageGateError):
        require_gate(gate)


def test_decision_report_gate_rejects_records_change_and_records_output():
    study = _load_study()
    artifact = build_artifact(RESULTS)
    changed = _gate(study, artifact, before="a" * 64, after="b" * 64)
    with pytest.raises(StageGateError, match="records_tree_unchanged"):
        require_gate(changed)

    unsafe = _gate(study, artifact, output=BASE / "records" / "research")
    with pytest.raises(StageGateError, match="output_isolated_from_records"):
        require_gate(unsafe)


def test_writing_artifact_does_not_touch_records(tmp_path):
    copied = tmp_path / "results"
    copied.mkdir()
    for name in (
        "strategy_research.json",
        "strategy_summary.csv",
        "policy_weekly.csv",
    ):
        (copied / name).write_bytes((RESULTS / name).read_bytes())
    before = tree_sha256(BASE / "records")
    output = write_artifact(copied)
    after = tree_sha256(BASE / "records")
    assert output == copied / "artifact.json"
    assert before == after
