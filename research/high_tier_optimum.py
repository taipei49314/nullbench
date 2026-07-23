"""五注高獎級累積事件與 4／5／6 主號門檻的精確最優證明。

原 v1 證書已證明完整任一獎與至少三主號的全域最優，且其 hash 已被
前向帳本引用。本補充證書不改動 v1；它利用 union bound 與完整獎級整數
計數，證明完全分散五注也同時達到高獎級累積事件的理論上限。
"""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import json
import math
import os
from pathlib import Path

from engine.agent_loop import canonical_hash
from engine.games import (
    GAME_NAMES,
    LOTTO649,
    PICK_N,
    POOL,
    SUPER,
    TIERS,
)
from research.gates import tree_sha256
from research.portfolio_coverage import (
    _favorable_main_draw_count,
    _membership_counts,
    _pair_intersection_count,
    _single_favorable_count,
)
from research.prize_tier_profile import exact_prize_profile
from research.structural_optimum import (
    OFFICIAL_RULE_URLS,
    disjoint_reference_tickets,
    proof_payload as structural_proof_payload,
    structural_proof_reference,
)


EXPERIMENT_ID = "five-ticket-high-tier-pareto-proof-v1"
PORTFOLIO_TICKETS = 5
MAIN_THRESHOLDS = (3, 4, 5, 6)
HIGH_TIER_CUTOFF_RANK = {
    SUPER: 7,
    LOTTO649: 6,
}


def _main_threshold_certificate(
    game: str,
    threshold: int,
) -> dict:
    if threshold not in MAIN_THRESHOLDS:
        raise ValueError("主號門檻必須介於 3 至 6")
    pool = POOL[game]
    denominator = math.comb(pool, PICK_N)
    single = _single_favorable_count(pool, threshold)
    disjoint = disjoint_reference_tickets(game)
    disjoint_count = _favorable_main_draw_count(
        pool,
        _membership_counts(
            pool,
            [set(ticket["numbers"]) for ticket in disjoint],
        ),
        require_all=False,
        threshold=threshold,
    )
    pair_counts = [
        _pair_intersection_count(pool, overlap, threshold)
        for overlap in range(PICK_N)
    ]
    if threshold == 3:
        source = structural_proof_payload()["games"][game][
            "three_main"
        ]
        upper = source["global_maximum_favorable_count"]
        proof_kind = "v1_three_order_charge_certificate"
        sufficient_overlap = 0
        if (
            source["global_optimum_proved"] is not True
            or disjoint_count != upper
        ):
            raise RuntimeError(
                f"{game} 三主號 v1 證明引用不一致"
            )
    else:
        upper = PORTFOLIO_TICKETS * single
        proof_kind = "first_order_union_bound_attained"
        sufficient_overlap = 2 * threshold - PICK_N - 1
        if (
            disjoint_count != upper
            or any(
                pair_counts[overlap] != 0
                for overlap in range(sufficient_overlap + 1)
            )
            or (
                sufficient_overlap < PICK_N - 1
                and pair_counts[sufficient_overlap + 1] <= 0
            )
        ):
            raise RuntimeError(
                f"{game} 至少 {threshold} 主號 union bound 未達成"
            )
    return {
        "minimum_main_hits": threshold,
        "denominator": denominator,
        "single_ticket_favorable_count": single,
        "five_ticket_universal_union_upper_count": upper,
        "disjoint_five_ticket_favorable_count": disjoint_count,
        "global_maximum_probability": disjoint_count / denominator,
        "proof_kind": proof_kind,
        "pair_intersection_by_main_overlap": [
            {
                "main_overlap": overlap,
                "intersection_count": count,
            }
            for overlap, count in enumerate(pair_counts)
        ],
        "known_sufficient_pairwise_overlap_max": (
            sufficient_overlap
        ),
        "disjoint_attains_global_maximum": True,
        "global_optimum_proved": True,
        "uniqueness": (
            "主號完全互斥是 v1 證明的唯一最優結構條件"
            if threshold == 3
            else "最優結構不唯一；符合列示 pairwise overlap"
            " 上限的五張不同主號票也能達到相同 union bound"
        ),
    }


def _cumulative_tier_rows(game: str) -> tuple[list[dict], dict]:
    cutoff = HIGH_TIER_CUTOFF_RANK[game]
    one = exact_prize_profile(
        game, disjoint_reference_tickets(game)[:1]
    )
    five = exact_prize_profile(
        game, disjoint_reference_tickets(game)
    )
    if one["denominator"] != five["denominator"]:
        raise RuntimeError("單注與五注獎級樣本空間分母不一致")
    denominator = one["denominator"]
    single_cumulative = 0
    five_cumulative = 0
    rows = []
    boundary = None
    for tier, single_row, five_row in zip(
        TIERS[game],
        one["best_tier_distribution"],
        five["best_tier_distribution"],
    ):
        single_cumulative += single_row["numerator"]
        five_cumulative += five_row["numerator"]
        universal_upper = (
            PORTFOLIO_TICKETS * single_cumulative
        )
        attained = five_cumulative == universal_upper
        current = {
            "maximum_best_tier_rank": tier.rank,
            "maximum_best_tier_label": tier.label,
            "minimum_main_hits_in_event": min(
                item.match_main
                for item in TIERS[game]
                if item.rank <= tier.rank
            ),
            "single_ticket_cumulative_count": single_cumulative,
            "five_ticket_universal_union_upper_count": (
                universal_upper
            ),
            "disjoint_five_ticket_cumulative_count": (
                five_cumulative
            ),
            "disjoint_probability": (
                five_cumulative / denominator
            ),
            "union_upper_attained": attained,
            "global_optimum_proved": (
                attained and tier.rank <= cutoff
            ),
        }
        if tier.rank <= cutoff:
            if not attained:
                raise RuntimeError(
                    f"{game} 高獎級 rank {tier.rank} 未達 union bound"
                )
            rows.append(current)
        elif boundary is None:
            boundary = {
                **current,
                "union_upper_deficit_count": (
                    universal_upper - five_cumulative
                ),
                "explanation": (
                    "加入下一獎級後，不同票券的獲獎事件開始能在"
                    "同一開獎重疊；簡單 first-order union bound"
                    " 不再能取等號，完整任一獎改由 v1 三階證書處理。"
                ),
            }
    if (
        boundary is None
        or boundary["union_upper_attained"]
        or boundary["union_upper_deficit_count"] <= 0
    ):
        raise RuntimeError(f"{game} 高獎級邊界證據不符")
    return rows, {
        "denominator": denominator,
        "first_non_exclusive_cumulative_tier": boundary,
    }


@lru_cache(maxsize=1)
def _proof_payload_cached() -> dict:
    games = {}
    for game in (SUPER, LOTTO649):
        cumulative, boundary = _cumulative_tier_rows(game)
        games[game] = {
            "game_name": GAME_NAMES[game],
            "pool": POOL[game],
            "pick_n": PICK_N,
            "high_tier_cutoff_rank": (
                HIGH_TIER_CUTOFF_RANK[game]
            ),
            "high_tier_cutoff_label": TIERS[game][
                HIGH_TIER_CUTOFF_RANK[game] - 1
            ].label,
            "main_hit_thresholds": [
                _main_threshold_certificate(game, threshold)
                for threshold in MAIN_THRESHOLDS
            ],
            "cumulative_high_tier_union_bounds": cumulative,
            **boundary,
        }
    return {
        "schema_version": "1",
        "experiment_id": EXPERIMENT_ID,
        "rules_as_of": "2026-07-19",
        "official_prize_rules": OFFICIAL_RULE_URLS,
        "source_structural_proof": structural_proof_reference(),
        "question": (
            "五注完全分散是否只提高低獎聯集率，或也同時"
            "最大化至少 4／5／6 主號與高獎級累積機率？"
        ),
        "methodology": {
            "universal_upper_bound": (
                "任意五事件的 union 不超過五個單注事件機率"
                "之和；若完全分散構造的精確聯集計數等於此和，"
                "即直接證明全域最大。"
            ),
            "main_threshold_exclusivity": (
                "六主號開獎若要同時讓兩票各中至少 m 主號，"
                "票券主號 overlap 必須至少 2m-6；逐 overlap"
                " 的精確 pair intersection 另以整數計數驗證。"
            ),
            "tier_counting": (
                "重用已由縮小號碼池獨立窮舉驗證的完整獎級"
                " membership DP，比較單注累積計數×5與"
                "完全分散五注累積聯集計數。"
            ),
            "backward_compatibility": (
                "這是獨立補充證書；不修改已被 7/20、7/21"
                " 前向登記引用的 v1 certificate hash。"
            ),
            "calculation": "全程整數組合計數；不使用 Monte Carlo",
            "lookahead": "純規則與結構分析，不讀歷史開獎或 reveal",
        },
        "games": games,
        "conclusion": {
            "all_high_tier_union_bounds_attained": True,
            "super": (
                "主號完全互斥且第二區互異的五注，同時最大化"
                "頭獎至柒獎的每一個累積聯集機率；至少"
                "4／5／6 主號也全域最大。"
            ),
            "lotto649": (
                "主號完全互斥的五注，同時最大化頭獎至陸獎"
                "的每一個累積聯集機率；至少 4／5／6 主號"
                "也全域最大。"
            ),
            "non_unique_high_tier_optima": (
                "高門檻最優不唯一：至少4主號允許票間 overlap<=1，"
                "至少5主號允許 overlap<=3，頭獎只要求五張"
                "完整票券彼此不同；完全分散仍同時滿足所有門檻。"
            ),
            "strategy": (
                "現行 coverage 五注不是用高獎機率交換低獎機率；"
                "它位於所有已證明目標的共同全域最優交集。"
            ),
        },
        "limitations": [
            "高獎級證明最大化命中事件機率，不最大化浮動獎金或期望報酬。",
            "威力彩柒獎以下、大樂透陸獎以下開始出現事件重疊；完整任一獎仍由 v1 證書證明。",
            "依賴現行獎級規則、公平且各期獨立的開獎模型。",
            "純模擬，不構成購買或下注建議。",
        ],
    }


def proof_payload() -> dict:
    return deepcopy(_proof_payload_cached())


def build_high_tier_optimum_certificate(base: Path) -> dict:
    base = Path(base)
    records_before = tree_sha256(base / "records")
    payload = proof_payload()
    records_after = tree_sha256(base / "records")
    if records_before != records_after:
        raise RuntimeError("高獎級最優證明不應改動正式 records")
    return {
        **payload,
        "certificate_hash": canonical_hash(payload),
        "records_integrity": {
            "before_sha256": records_before,
            "after_sha256": records_after,
            "unchanged": records_before == records_after,
        },
    }


def verify_high_tier_optimum_certificate(result: dict) -> None:
    payload = proof_payload()
    expected = {
        **payload,
        "certificate_hash": canonical_hash(payload),
    }
    actual = {
        key: result.get(key)
        for key in expected
    }
    if actual != expected:
        raise RuntimeError(
            "高獎級最優證明內容或 certificate hash 不符"
        )
    integrity = result.get("records_integrity", {})
    if (
        integrity.get("unchanged") is not True
        or integrity.get("before_sha256")
        != integrity.get("after_sha256")
    ):
        raise RuntimeError("高獎級最優證明 records 完整性不符")


def write_results(result: dict, path: Path) -> Path:
    verify_high_tier_optimum_certificate(result)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return path
