"""研究流程的顯式階段閘門。

每個閘門回傳可序列化的檢查清單；任何必要條件失敗時，研究流程必須在進入
下一階段前停止。這個模組不讀寫正式 ``records/``。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
from pathlib import Path
from typing import Iterable

from engine.games import LOTTO649, SUPER
from engine.store import monday_of, week_id_of


EXPECTED_GAMES = (SUPER, LOTTO649)
FINAL_POLICY_IDS = (
    "random_5",
    "current_ensemble",
    "trained_family_ensemble",
    "trained_best_5",
    "trained_blend",
)


@dataclass(frozen=True)
class StageGateError(RuntimeError):
    """階段閘門未通過。"""

    stage: str
    failed_checks: tuple[str, ...]

    def __str__(self) -> str:
        checks = ", ".join(self.failed_checks)
        return f"{self.stage} 階段閘門未通過：{checks}"


def _check(check_id: str, passed: bool, evidence) -> dict:
    return {
        "id": check_id,
        "passed": bool(passed),
        "evidence": evidence,
    }


def build_data_quality_gate(profiles: Iterable[dict]) -> dict:
    """把兩款遊戲的資料剖析轉成可稽核的第一階段閘門。"""
    profiles = list(profiles)
    by_game = {profile.get("game"): profile for profile in profiles}
    checks = [
        _check(
            "games_exactly_once",
            len(profiles) == len(EXPECTED_GAMES)
            and set(by_game) == set(EXPECTED_GAMES),
            sorted(str(game) for game in by_game),
        )
    ]
    for game in EXPECTED_GAMES:
        profile = by_game.get(game)
        if profile is None:
            checks.append(_check(f"{game}.profile_present", False, "missing"))
            continue
        prefix = f"{game}."
        checks.extend(
            [
                _check(
                    prefix + "nonempty",
                    profile.get("draws", 0) > 0,
                    profile.get("draws", 0),
                ),
                _check(
                    prefix + "chronological",
                    profile.get("ordered_chronologically") is True,
                    profile.get("ordered_chronologically"),
                ),
                _check(
                    prefix + "unique_periods",
                    profile.get("duplicate_periods") == 0,
                    profile.get("duplicate_periods"),
                ),
                _check(
                    prefix + "unique_dates",
                    profile.get("duplicate_dates") == 0,
                    profile.get("duplicate_dates"),
                ),
                _check(
                    prefix + "legal_draws",
                    profile.get("invalid_numbers") == 0
                    and profile.get("invalid_special") == 0
                    and profile.get("game_mismatches") == 0
                    and profile.get("invalid_periods") == 0
                    and profile.get("invalid_dates") == 0,
                    {
                        "invalid_numbers": profile.get("invalid_numbers"),
                        "invalid_special": profile.get("invalid_special"),
                        "game_mismatches": profile.get("game_mismatches"),
                        "invalid_periods": profile.get("invalid_periods"),
                        "invalid_dates": profile.get("invalid_dates"),
                    },
                ),
                _check(
                    prefix + "complete_prizes",
                    not any(profile.get("missing_prize_fields", {}).values())
                    and profile.get("invalid_prize_records") == 0,
                    {
                        "missing": profile.get("missing_prize_fields", {}),
                        "invalid": profile.get("invalid_prize_records"),
                    },
                ),
                _check(
                    prefix + "fingerprinted",
                    len(profile.get("dataset_sha256", "")) == 64,
                    profile.get("dataset_sha256"),
                ),
                _check(
                    prefix + "profile_pass",
                    profile.get("quality_status") == "pass",
                    profile.get("quality_failures", []),
                ),
            ]
        )
    failed = [check["id"] for check in checks if not check["passed"]]
    return {
        "stage": "data_quality",
        "status": "pass" if not failed else "fail",
        "checks": checks,
        "failed_checks": failed,
    }


def _candidate_family(candidate) -> str | None:
    if isinstance(candidate, dict):
        return candidate.get("family")
    return getattr(candidate, "family", None)


def _policy_id(policy) -> str | None:
    if isinstance(policy, dict):
        return policy.get("policy_id")
    return getattr(policy, "policy_id", None)


def _policy_slots(policy):
    if isinstance(policy, dict):
        return policy.get("slots", ())
    return getattr(policy, "slots", ())


def _context_checks(game: str, contexts: list) -> list[dict]:
    n = len(contexts)
    train_end = n // 2
    validation_end = train_end + n // 4
    expected_splits = [
        (
            "train"
            if i < train_end
            else "validation"
            if i < validation_end
            else "holdout"
        )
        for i in range(n)
    ]
    weeks = [context.week for context in contexts]
    no_lookahead = True
    history_chain = True
    floors_historical = True
    draws_in_own_week = True
    history = []
    floors: dict[str, int] = {}
    for context in contexts:
        monday = monday_of(context.week)
        no_lookahead = no_lookahead and all(
            draw.date < monday.isoformat() for draw in context.history
        )
        history_chain = history_chain and tuple(history) == context.history
        floors_historical = (
            floors_historical and floors == context.floor_table
        )
        draws_in_own_week = draws_in_own_week and all(
            week_id_of(date.fromisoformat(draw.date)) == context.week
            for draw in context.draws
        )
        for draw in context.draws:
            for key, info in draw.prizes.items():
                per_prize = int(info.get("per_prize", 0))
                if int(info.get("winner_count", 0)) > 0 and per_prize > 0:
                    floors[key] = min(floors.get(key, per_prize), per_prize)
        history.extend(context.draws)
    return [
        _check(f"{game}.contexts_nonempty", n > 0, n),
        _check(
            f"{game}.weeks_unique_ordered",
            len(weeks) == len(set(weeks)) and weeks == sorted(weeks),
            {"first": weeks[0] if weeks else None, "last": weeks[-1] if weeks else None},
        ),
        _check(
            f"{game}.split_boundaries",
            [context.split for context in contexts] == expected_splits,
            {
                "train": expected_splits.count("train"),
                "validation": expected_splits.count("validation"),
                "holdout": expected_splits.count("holdout"),
            },
        ),
        _check(f"{game}.no_lookahead", no_lookahead, no_lookahead),
        _check(f"{game}.history_chain", history_chain, history_chain),
        _check(
            f"{game}.historical_floor_table",
            floors_historical,
            floors_historical,
        ),
        _check(
            f"{game}.draws_in_own_week",
            draws_in_own_week,
            draws_in_own_week,
        ),
    ]


def build_strategy_search_gate(
    contexts_by_game: dict,
    coarse_candidates: Iterable,
    coarse_winners: dict,
    refined_winners: dict,
    final_policies: dict,
    determinism_probe: dict,
) -> dict:
    """驗證策略搜尋只建立在歷史切片上，且輸出可決定性重播。"""
    checks = []
    checks.append(
        _check(
            "contexts_games_complete",
            set(contexts_by_game) == set(EXPECTED_GAMES),
            sorted(contexts_by_game),
        )
    )
    for game in EXPECTED_GAMES:
        checks.extend(_context_checks(game, list(contexts_by_game.get(game, ()))))

    coarse_candidates = list(coarse_candidates)
    candidate_ids = [
        (
            candidate.get("candidate_id")
            if isinstance(candidate, dict)
            else getattr(candidate, "candidate_id", None)
        )
        for candidate in coarse_candidates
    ]
    checks.extend(
        [
            _check("coarse.count", len(coarse_candidates) == 31, len(coarse_candidates)),
            _check(
                "coarse.ids_unique",
                None not in candidate_ids
                and len(candidate_ids) == len(set(candidate_ids)),
                len(set(candidate_ids)),
            ),
            _check(
                "coarse.families_complete",
                {_candidate_family(candidate) for candidate in coarse_candidates}
                == {"uniform", "hot", "cold", "balance", "antipop"},
                sorted(
                    str(_candidate_family(candidate))
                    for candidate in coarse_candidates
                ),
            ),
        ]
    )
    expected_families = {"hot", "cold", "balance", "antipop"}
    for label, winner_map in (
        ("coarse_winners", coarse_winners),
        ("refined_winners", refined_winners),
    ):
        for game in EXPECTED_GAMES:
            winners = winner_map.get(game, {})
            checks.append(
                _check(
                    f"{label}.{game}.families",
                    set(winners) == expected_families
                    and all(
                        _candidate_family(winners[family]) == family
                        for family in expected_families
                    ),
                    sorted(winners),
                )
            )

    expected_policy_ids = set(FINAL_POLICY_IDS)
    for game in EXPECTED_GAMES:
        policies = list(final_policies.get(game, ()))
        ids = [_policy_id(policy) for policy in policies]
        checks.extend(
            [
                _check(
                    f"final_policies.{game}.ids",
                    set(ids) == expected_policy_ids and len(ids) == len(set(ids)),
                    ids,
                ),
                _check(
                    f"final_policies.{game}.five_slots",
                    all(len(_policy_slots(policy)) == 5 for policy in policies),
                    [len(_policy_slots(policy)) for policy in policies],
                ),
            ]
        )
    checks.append(
        _check(
            "ticket_generation_deterministic",
            determinism_probe.get("passed") is True
            and determinism_probe.get("comparisons", 0) >= 10,
            determinism_probe,
        )
    )
    failed = [check["id"] for check in checks if not check["passed"]]
    return {
        "stage": "strategy_search",
        "status": "pass" if not failed else "fail",
        "checks": checks,
        "failed_checks": failed,
    }


def _serialized_policy(policy) -> dict:
    if isinstance(policy, dict):
        return policy
    return policy.as_dict()


def _holdout_seal_material(
    contexts_by_game: dict,
    final_policies: dict,
    dataset_fingerprints: dict[str, str],
) -> dict:
    games = {}
    for game in EXPECTED_GAMES:
        holdout = [
            context
            for context in contexts_by_game.get(game, ())
            if context.split == "holdout"
        ]
        policies = sorted(
            (
                _serialized_policy(policy)
                for policy in final_policies.get(game, ())
            ),
            key=lambda policy: policy["policy_id"],
        )
        games[game] = {
            "dataset_sha256": dataset_fingerprints.get(game),
            "weeks": [
                {
                    "week": context.week,
                    "periods": [draw.period for draw in context.draws],
                    "dates": [draw.date for draw in context.draws],
                }
                for context in holdout
            ],
            "policies": policies,
        }
    return {"games": games}


def create_holdout_seal(
    contexts_by_game: dict,
    final_policies: dict,
    dataset_fingerprints: dict[str, str],
) -> dict:
    """在 validation 選擇與 holdout 評估之前封存資料與政策集合。"""
    material = _holdout_seal_material(
        contexts_by_game, final_policies, dataset_fingerprints
    )
    digest = hashlib.sha256(
        json.dumps(
            material,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "schema_version": "1",
        "status": "sealed",
        "sha256": digest,
        "games": {
            game: {
                "dataset_sha256": material["games"][game]["dataset_sha256"],
                "holdout_weeks": len(material["games"][game]["weeks"]),
                "holdout_draws": sum(
                    len(week["periods"])
                    for week in material["games"][game]["weeks"]
                ),
                "policy_ids": [
                    policy["policy_id"]
                    for policy in material["games"][game]["policies"]
                ],
            }
            for game in EXPECTED_GAMES
        },
    }


def verify_holdout_seal(
    seal: dict,
    contexts_by_game: dict,
    final_policies: dict,
    dataset_fingerprints: dict[str, str],
) -> bool:
    expected = create_holdout_seal(
        contexts_by_game, final_policies, dataset_fingerprints
    )
    return seal == expected


def edge_is_proven(holdout: dict) -> bool:
    """唯一允許升級條件式政策的外驗門檻。"""
    return (
        holdout["delta_ci_low"] > 0
        and holdout["delta_fixed_roi_mean"] >= 0
        and holdout["positive_replicate_rate"] >= 0.75
        and holdout["active_week_win_rate"] > 0.50
    )


def build_validation_holdout_gate(
    final_summaries: Iterable[dict],
    selected: dict,
    holdout_seal: dict,
    contexts_by_game: dict,
    final_policies: dict,
    dataset_fingerprints: dict[str, str],
) -> dict:
    """驗證 validation 只選一次，且 holdout 決策符合封存門檻。"""
    summaries = list(final_summaries)
    checks = [
        _check(
            "holdout_seal_valid",
            verify_holdout_seal(
                holdout_seal,
                contexts_by_game,
                final_policies,
                dataset_fingerprints,
            ),
            holdout_seal.get("sha256"),
        ),
        _check(
            "selected_games_complete",
            set(selected) == set(EXPECTED_GAMES),
            sorted(selected),
        ),
    ]
    expected_ids = set(FINAL_POLICY_IDS)
    for game in EXPECTED_GAMES:
        for split in ("train", "validation", "holdout"):
            rows = [
                row
                for row in summaries
                if row.get("game") == game and row.get("split") == split
            ]
            ids = [row.get("policy_id") for row in rows]
            checks.append(
                _check(
                    f"{game}.{split}.policy_coverage",
                    set(ids) == expected_ids and len(ids) == len(set(ids)),
                    ids,
                )
            )
        validation_rows = [
            row
            for row in summaries
            if row.get("game") == game and row.get("split") == "validation"
        ]
        expected_choice = (
            sorted(
                validation_rows,
                key=lambda row: (
                    -row["delta_robust_roi_mean"],
                    row["policy_id"],
                ),
            )[0]
            if validation_rows
            else None
        )
        decision = selected.get(game, {})
        policy_id = decision.get("policy_id")
        checks.append(
            _check(
                f"{game}.validation_choice",
                expected_choice is not None
                and policy_id == expected_choice["policy_id"]
                and decision.get("validation") == expected_choice,
                {
                    "expected": (
                        expected_choice["policy_id"] if expected_choice else None
                    ),
                    "actual": policy_id,
                },
            )
        )
        holdout_rows = [
            row
            for row in summaries
            if row.get("game") == game
            and row.get("split") == "holdout"
            and row.get("policy_id") == policy_id
        ]
        actual_holdout = decision.get("holdout")
        checks.append(
            _check(
                f"{game}.holdout_exact_row",
                len(holdout_rows) == 1 and actual_holdout == holdout_rows[0],
                len(holdout_rows),
            )
        )
        expected_edge = (
            edge_is_proven(actual_holdout) if actual_holdout is not None else False
        )
        checks.extend(
            [
                _check(
                    f"{game}.edge_gate",
                    decision.get("edge_proven") is expected_edge,
                    {
                        "expected": expected_edge,
                        "actual": decision.get("edge_proven"),
                    },
                ),
                _check(
                    f"{game}.conditional_decision",
                    decision.get("conditional_decision")
                    == (policy_id if expected_edge else "random_5"),
                    decision.get("conditional_decision"),
                ),
            ]
        )
        baseline_rows = [
            row
            for row in summaries
            if row.get("game") == game and row.get("policy_id") == "random_5"
        ]
        checks.append(
            _check(
                f"{game}.paired_baseline_zero",
                len(baseline_rows) == 3
                and all(
                    row.get("delta_robust_roi_mean") == 0
                    and row.get("delta_fixed_roi_mean") == 0
                    for row in baseline_rows
                ),
                len(baseline_rows),
            )
        )
    failed = [check["id"] for check in checks if not check["passed"]]
    return {
        "stage": "validation_holdout",
        "status": "pass" if not failed else "fail",
        "checks": checks,
        "failed_checks": failed,
    }


def tree_sha256(root: Path) -> str:
    """對目錄內相對路徑與檔案內容做決定性指紋。"""
    root = root.resolve()
    digest = hashlib.sha256()
    if not root.exists():
        digest.update(b"<missing>")
        return digest.hexdigest()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _is_output_isolated(base: Path, output_dir: Path) -> bool:
    records = (base / "records").resolve()
    output = output_dir.resolve()
    return output != records and records not in output.parents


def build_decision_report_gate(
    study: dict,
    artifact: dict,
    records_before: str,
    records_after: str,
    base: Path,
    output_dir: Path,
) -> dict:
    """驗證最終決策、報告結構與正式帳本不變性。"""
    previous_gates = study.get("stage_gates", {})
    required_previous = {
        "data_quality",
        "strategy_search",
        "validation_holdout",
    }
    decision = study.get("decision", {})
    selected = study.get("selected", {})
    conditional = decision.get("conditional_simulation", {})
    manifest = artifact.get("manifest", {})
    snapshot = artifact.get("snapshot", {})
    blocks = manifest.get("blocks", [])
    charts = manifest.get("charts", [])
    tables = manifest.get("tables", [])
    datasets = snapshot.get("datasets", {})
    decision_rows = datasets.get("decision_rows", [])
    rows_by_game = {row.get("game"): row for row in decision_rows}

    checks = [
        _check(
            "previous_gates_pass",
            required_previous.issubset(previous_gates)
            and all(
                previous_gates[name].get("status") == "pass"
                for name in required_previous
            ),
            {
                name: previous_gates.get(name, {}).get("status")
                for name in sorted(required_previous)
            },
        ),
        _check(
            "economic_decision_no_play",
            decision.get("economic") == "no_play"
            and bool(decision.get("reason")),
            decision.get("economic"),
        ),
        _check(
            "records_tree_unchanged",
            len(records_before) == 64 and records_before == records_after,
            {"before": records_before, "after": records_after},
        ),
        _check(
            "output_isolated_from_records",
            _is_output_isolated(base, output_dir),
            str(output_dir.resolve()),
        ),
        _check(
            "artifact_title_and_first_heading",
            bool(manifest.get("title"))
            and bool(blocks)
            and blocks[0].get("type") == "markdown"
            and blocks[0].get("body")
            == f"# {manifest.get('title')}",
            manifest.get("title"),
        ),
        _check(
            "artifact_has_chart_and_table",
            bool(charts)
            and bool(tables)
            and any(block.get("type") == "chart" for block in blocks)
            and any(block.get("type") == "table" for block in blocks),
            {"charts": len(charts), "tables": len(tables)},
        ),
        _check(
            "artifact_snapshot_ready",
            snapshot.get("status") == "ready"
            and all(isinstance(rows, list) for rows in datasets.values()),
            {
                "status": snapshot.get("status"),
                "datasets": sorted(datasets),
            },
        ),
        _check(
            "artifact_sources_have_sql",
            all(
                isinstance(item.get("source", {}).get("query", {}).get("sql"), str)
                and item["source"]["query"]["sql"].lstrip().upper().startswith(
                    "SELECT"
                )
                for item in charts + tables
            ),
            len(charts) + len(tables),
        ),
    ]
    for game in EXPECTED_GAMES:
        item = selected.get(game, {})
        expected_conditional = (
            item.get("policy_id")
            if item.get("edge_proven") is True
            else "random_5"
        )
        row = rows_by_game.get(game, {})
        checks.extend(
            [
                _check(
                    f"{game}.conditional_matches_edge",
                    conditional.get(game) == expected_conditional
                    and item.get("conditional_decision")
                    == expected_conditional,
                    conditional.get(game),
                ),
                _check(
                    f"{game}.artifact_decision_matches",
                    row.get("selected_policy") == item.get("policy_id")
                    and row.get("conditional_decision")
                    == expected_conditional
                    and row.get("edge_proven")
                    == ("已證明" if item.get("edge_proven") else "未證明"),
                    row,
                ),
            ]
        )
    checks.append(
        _check(
            "artifact_decision_games_complete",
            set(rows_by_game) == set(EXPECTED_GAMES)
            and len(decision_rows) == len(EXPECTED_GAMES),
            sorted(str(game) for game in rows_by_game),
        )
    )
    failed = [check["id"] for check in checks if not check["passed"]]
    return {
        "stage": "decision_report",
        "status": "pass" if not failed else "fail",
        "checks": checks,
        "failed_checks": failed,
    }


def require_gate(gate: dict) -> None:
    """失敗時阻止流程前進。"""
    if gate.get("status") != "pass":
        raise StageGateError(
            str(gate.get("stage", "unknown")),
            tuple(gate.get("failed_checks", ())),
        )
