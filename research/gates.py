"""研究流程的顯式階段閘門。

每個閘門回傳可序列化的檢查清單；任何必要條件失敗時，研究流程必須在進入
下一階段前停止。這個模組不讀寫正式 ``records/``。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable

from engine.games import LOTTO649, SUPER
from engine.store import monday_of, week_id_of


EXPECTED_GAMES = (SUPER, LOTTO649)


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

    expected_policy_ids = {
        "random_5",
        "current_ensemble",
        "trained_family_ensemble",
        "trained_best_5",
        "trained_blend",
    }
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


def require_gate(gate: dict) -> None:
    """失敗時阻止流程前進。"""
    if gate.get("status") != "pass":
        raise StageGateError(
            str(gate.get("stage", "unknown")),
            tuple(gate.get("failed_checks", ())),
        )
