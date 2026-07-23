"""逐一精算同一期 15 選 5，稽核近似 selector 是否漏掉更高機率組合。"""
from __future__ import annotations

import argparse
from itertools import combinations, islice
import json
import math
import os
from pathlib import Path
import time
from typing import Callable

from engine.agent_loop import SELECTED_TICKETS
from engine.games import LOTTO649, SPECIAL_POOL, SUPER
from research.portfolio_coverage import (
    exact_any_prize_probability,
    exact_main_hit_probability,
    portfolio_structure,
    select_coverage_portfolio,
)


EXPERIMENT_ID = "exact-selector-audit-v1"
Progress = Callable[[int, int], None]


def _candidate_tickets(proposals: list[dict], indexes: tuple[int, ...]):
    return [
        {
            "slot": slot,
            "source_agent": proposals[index]["agent"],
            "source_proposal": proposals[index]["proposal_id"],
            "numbers": list(proposals[index]["numbers"]),
            "special": proposals[index]["special"],
        }
        for slot, index in enumerate(indexes, 1)
    ]


def _compact_candidate(
    *,
    tickets: list[dict],
    any_prize: float,
    three_main: float,
) -> dict:
    return {
        "proposal_ids": [
            ticket["source_proposal"] for ticket in tickets
        ],
        "exact_any_prize": any_prize,
        "exact_at_least_three_main": three_main,
        "main_union_size": len(
            set().union(
                *(set(ticket["numbers"]) for ticket in tickets)
            )
        ),
        "special_values": (
            sorted({int(ticket["special"]) for ticket in tickets})
            if tickets[0]["special"] is not None
            else None
        ),
    }


def disjoint_reference_tickets(game: str) -> list[dict]:
    """建立五注主號互斥、威力彩第二區也互異的固定參考結構。"""
    return [
        {
            "slot": index + 1,
            "source_agent": "probability_reference",
            "source_proposal": f"disjoint-{index + 1}",
            "numbers": list(range(index * 6 + 1, index * 6 + 7)),
            "special": index + 1 if game == SUPER else None,
        }
        for index in range(SELECTED_TICKETS)
    ]


def audit_exact_candidate_pool(
    game: str,
    decision: dict,
    *,
    limit: int | None = None,
    progress: Progress | None = None,
) -> dict:
    """精算所有候選五注；不接受 reveal，也不依賴事後命中。"""
    if game not in (SUPER, LOTTO649):
        raise ValueError(f"不支援的遊戲：{game}")
    if decision.get("game") != game:
        raise ValueError("decision 遊戲不符")
    proposals = list(decision.get("proposals", ()))
    if len(proposals) != 15:
        raise ValueError("精確 selector 稽核需要 15 組封存提案")
    total = math.comb(len(proposals), SELECTED_TICKETS)
    if limit is not None and not 1 <= limit <= total:
        raise ValueError(f"limit 必須介於 1 與 {total}")

    baseline = portfolio_structure(
        game, list(decision["selected_tickets"])
    )
    selected, selection = select_coverage_portfolio(game, decision)
    selected_any = selection["selected"]["exact_any_prize"]
    selected_main = selection["selected"][
        "exact_at_least_three_main"
    ]
    selected_compact = _compact_candidate(
        tickets=selected,
        any_prize=selected_any,
        three_main=selected_main,
    )
    selected_key = (
        -selected_any,
        -selected_main,
        tuple(selected_compact["proposal_ids"]),
    )
    best_unconstrained = (selected_key, selected_compact)
    best_safe = (
        (selected_key, selected_compact)
        if (
            selected_any >= baseline["exact_any_prize"] - 1e-15
            and selected_main
            >= baseline["exact_at_least_three_main"] - 1e-15
        )
        else None
    )
    safe_better_than_selected = 0
    evaluated = 0
    started = time.perf_counter()
    iterable = combinations(range(len(proposals)), SELECTED_TICKETS)
    if limit is not None:
        iterable = islice(iterable, limit)

    for indexes in iterable:
        number_keys = {
            tuple(sorted(proposals[index]["numbers"]))
            for index in indexes
        }
        if len(number_keys) != SELECTED_TICKETS:
            continue
        tickets = _candidate_tickets(proposals, indexes)
        any_prize = exact_any_prize_probability(game, tickets)
        three_main = exact_main_hit_probability(game, tickets)
        proposal_ids = tuple(
            ticket["source_proposal"] for ticket in tickets
        )
        key = (-any_prize, -three_main, proposal_ids)
        compact = _compact_candidate(
            tickets=tickets,
            any_prize=any_prize,
            three_main=three_main,
        )
        if best_unconstrained is None or key < best_unconstrained[0]:
            best_unconstrained = (key, compact)
        safe = (
            any_prize >= baseline["exact_any_prize"] - 1e-15
            and three_main
            >= baseline["exact_at_least_three_main"] - 1e-15
        )
        if safe and (best_safe is None or key < best_safe[0]):
            best_safe = (key, compact)
        if (
            safe
            and any_prize > selected_any + 1e-15
            and three_main >= baseline[
                "exact_at_least_three_main"
            ] - 1e-15
        ):
            safe_better_than_selected += 1
        evaluated += 1
        if progress is not None and (
            evaluated == 1
            or evaluated % 250 == 0
            or evaluated == (limit or total)
        ):
            progress(evaluated, limit or total)

    if best_unconstrained is None or best_safe is None:
        raise RuntimeError("候選池沒有可稽核的安全五注組合")
    reference = portfolio_structure(
        game, disjoint_reference_tickets(game)
    )
    safe_best = best_safe[1]
    return {
        "schema_version": "1",
        "experiment_id": EXPERIMENT_ID,
        "game": game,
        "source_decision_hash": decision["decision_hash"],
        "target": dict(decision["target"]),
        "proposals": len(proposals),
        "combinations_expected": total,
        "combinations_evaluated": evaluated,
        "complete_enumeration": evaluated == total,
        "elapsed_seconds": time.perf_counter() - started,
        "baseline": baseline,
        "heuristic_selected": {
            **selected_compact,
            "fallback_to_current": selection[
                "fallback_to_current"
            ],
        },
        "exact_best_unconstrained": best_unconstrained[1],
        "exact_best_safe": safe_best,
        "safe_candidates_better_than_heuristic": (
            safe_better_than_selected
        ),
        "heuristic_any_prize_regret": (
            safe_best["exact_any_prize"] - selected_any
        ),
        "disjoint_reference": reference,
        "candidate_pool_gap_to_disjoint_reference": (
            reference["exact_any_prize"]
            - safe_best["exact_any_prize"]
        ),
        "lookahead_control": (
            "audit_exact_candidate_pool 不接受 reveal；所有排序只使用"
            "開獎前封存提案與可精確計算的組合結構。"
        ),
        "special_pool": SPECIAL_POOL.get(game),
    }


def _write_json(path: Path, result: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="精算目前 manifest 的 15 選 5 selector 機率遺憾"
    )
    parser.add_argument(
        "--game",
        choices=(SUPER, LOTTO649),
        required=True,
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("simulation") / "results" / "manifest.json",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args(argv)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    decision = manifest["games"][args.game]["next_decision"]

    def show_progress(done: int, total: int) -> None:
        print(
            f"[{args.game}] {done}/{total} "
            f"({done / total:.1%})",
            flush=True,
        )

    result = audit_exact_candidate_pool(
        args.game,
        decision,
        limit=args.limit,
        progress=show_progress,
    )
    _write_json(args.output, result)
    print(
        json.dumps(
            {
                "game": args.game,
                "complete": result["complete_enumeration"],
                "heuristic_regret": result[
                    "heuristic_any_prize_regret"
                ],
                "candidate_pool_gap": result[
                    "candidate_pool_gap_to_disjoint_reference"
                ],
                "output": str(args.output.resolve()),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
