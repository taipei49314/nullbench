"""研究流程的顯式階段閘門。

每個閘門回傳可序列化的檢查清單；任何必要條件失敗時，研究流程必須在進入
下一階段前停止。這個模組不讀寫正式 ``records/``。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from engine.games import LOTTO649, SUPER


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


def require_gate(gate: dict) -> None:
    """失敗時阻止流程前進。"""
    if gate.get("status") != "pass":
        raise StageGateError(
            str(gate.get("stage", "unknown")),
            tuple(gate.get("failed_checks", ())),
        )
