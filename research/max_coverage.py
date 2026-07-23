"""以 Agent 開獎前共識排序合成五注完全分散的最大覆蓋影子策略。"""
from __future__ import annotations

import csv
import json
import math
import os
from pathlib import Path
import statistics
from typing import Iterable

from engine.agent_loop import (
    LOOP_EXPERIMENT_ID,
    SELECTED_TICKETS,
    canonical_hash,
    verify_replay,
)
from engine.games import (
    GAME_NAMES,
    LOTTO649,
    PICK_N,
    POOL,
    SPECIAL_POOL,
    SUPER,
)
from research.agent_ablation import (
    _validate_event,
    block_bootstrap_ci,
    portfolio_metrics,
)
from research.gates import tree_sha256
from research.portfolio_coverage import (
    CoverageConfig,
    _split_profile,
    portfolio_structure,
    select_coverage_portfolio,
)
from research.structural_optimum import structural_proof_reference


EXPERIMENT_ID = "max-coverage-consensus-shadow-v1"
SELECTED_MAIN_NUMBERS = SELECTED_TICKETS * PICK_N
OFFICIAL_RULE_URLS = {
    SUPER: (
        "https://www.taiwanlottery.com/lotto/info/"
        "super_lotto638"
    ),
    LOTTO649: (
        "https://www.taiwanlottery.com/lotto/info/lotto649"
    ),
}


def _support_rows(
    game: str,
    decision: dict,
) -> list[dict]:
    scores = {
        row["proposal_id"]: float(row["debate_score"])
        for row in decision.get("adjudication", {}).get(
            "candidate_scores", ()
        )
    }
    proposals = list(decision.get("proposals", ()))
    if len(proposals) != 15 or set(scores) != {
        proposal["proposal_id"] for proposal in proposals
    }:
        raise ValueError("共識覆蓋需要完整 15 組提案與辯論分數")
    contributions: dict[int, list[float]] = {
        number: [] for number in range(1, POOL[game] + 1)
    }
    agents: dict[int, set[str]] = {
        number: set() for number in range(1, POOL[game] + 1)
    }
    appearances = {number: 0 for number in contributions}
    for proposal in proposals:
        score = scores[proposal["proposal_id"]]
        for number in proposal["numbers"]:
            value = int(number)
            contributions[value].append(score)
            agents[value].add(proposal["agent"])
            appearances[value] += 1
    rows = [
        {
            "number": number,
            "debate_support": math.fsum(contributions[number]),
            "agent_coverage": len(agents[number]),
            "proposal_appearances": appearances[number],
        }
        for number in contributions
    ]
    return sorted(
        rows,
        key=lambda row: (
            -row["debate_support"],
            -row["agent_coverage"],
            -row["proposal_appearances"],
            row["number"],
        ),
    )


def _special_ranking(decision: dict) -> list[dict]:
    scores = {
        row["proposal_id"]: float(row["debate_score"])
        for row in decision["adjudication"]["candidate_scores"]
    }
    contributions = {
        special: []
        for special in range(1, SPECIAL_POOL[SUPER] + 1)
    }
    appearances = {special: 0 for special in contributions}
    for proposal in decision["proposals"]:
        special = int(proposal["special"])
        contributions[special].append(scores[proposal["proposal_id"]])
        appearances[special] += 1
    rows = [
        {
            "special": special,
            "debate_support": math.fsum(contributions[special]),
            "proposal_appearances": appearances[special],
        }
        for special in contributions
    ]
    return sorted(
        rows,
        key=lambda row: (
            -row["debate_support"],
            -row["proposal_appearances"],
            row["special"],
        ),
    )


def select_consensus_disjoint_portfolio(
    game: str,
    decision: dict,
) -> tuple[list[dict], dict]:
    """合成五注完全分散組合；只讀開獎前提案與辯論分數。"""
    if game not in (SUPER, LOTTO649):
        raise ValueError(f"不支援的遊戲：{game}")
    if decision.get("game") != game:
        raise ValueError("decision 遊戲不符")
    ranking = _support_rows(game, decision)
    selected_rows = ranking[:SELECTED_MAIN_NUMBERS]
    selected_numbers = [row["number"] for row in selected_rows]
    if len(set(selected_numbers)) != SELECTED_MAIN_NUMBERS:
        raise RuntimeError("共識覆蓋未選出 30 個不同主號")

    # round-robin 將高支持號碼平均分散到五注；分組不改變完全互斥結構的
    # 精確聯集機率，只保留每注近似相同的 Agent 支持量。
    bins = [[] for _ in range(SELECTED_TICKETS)]
    support_by_number = {
        row["number"]: row["debate_support"] for row in selected_rows
    }
    for index, number in enumerate(selected_numbers):
        bins[index % SELECTED_TICKETS].append(number)
    bin_support = [
        math.fsum(support_by_number[number] for number in numbers)
        for numbers in bins
    ]

    if game == SUPER:
        special_rows = _special_ranking(decision)
        specials = [
            row["special"]
            for row in special_rows[:SELECTED_TICKETS]
        ]
        bin_order = sorted(
            range(SELECTED_TICKETS),
            key=lambda index: (-bin_support[index], index),
        )
        special_by_bin = {
            bin_index: specials[rank]
            for rank, bin_index in enumerate(bin_order)
        }
    else:
        special_rows = []
        special_by_bin = {
            index: None for index in range(SELECTED_TICKETS)
        }

    tickets = [
        {
            "slot": index + 1,
            "source_agent": "consensus_coverage_synthesizer",
            "source_proposal": f"consensus-disjoint:{index + 1}",
            "numbers": sorted(numbers),
            "special": special_by_bin[index],
        }
        for index, numbers in enumerate(bins)
    ]
    structure = portfolio_structure(game, tickets)
    if (
        structure["main_union_size"] != SELECTED_MAIN_NUMBERS
        or structure["maximum_pairwise_main_overlap"] != 0
        or (
            game == SUPER
            and structure["special_coverage_probability"]
            != SELECTED_TICKETS / SPECIAL_POOL[SUPER]
        )
    ):
        raise RuntimeError("共識覆蓋結構未達完全分散契約")
    support_evidence = {
        "number_ranking": ranking,
        "special_ranking": special_rows,
    }
    return tickets, {
        "experiment_id": EXPERIMENT_ID,
        "source_decision_hash": decision["decision_hash"],
        "support_evidence_hash": canonical_hash(support_evidence),
        "structural_optimum_proof": structural_proof_reference(),
        "selected_main_numbers": selected_numbers,
        "selected_specials": (
            sorted(special_by_bin.values())
            if game == SUPER
            else None
        ),
        "ticket_debate_support": bin_support,
        "structure": structure,
        "construction": (
            "依辯論加權支持選 30 個不同主號，以 round-robin 分成五注；"
            "威力彩另選五個不同第二區；該結構已由有限整數證明確認"
            "為完整任一獎級與三主號聯集機率的全域最大值。"
        ),
    }


def _mean(values: Iterable[float]) -> float:
    rows = list(values)
    return statistics.fmean(rows) if rows else 0.0


def _summary(
    metrics: dict[tuple[str, str], dict[str, list[float]]],
    config: CoverageConfig,
) -> list[dict]:
    rows = []
    for (game, split), values in sorted(metrics.items()):
        vs_rule_ci = block_bootstrap_ci(
            values["max_minus_rule_best"],
            samples=config.bootstrap_samples,
            block=config.bootstrap_block,
            seed=f"{EXPERIMENT_ID}|{game}|{split}|vs-rule-best",
        )
        vs_coverage_ci = block_bootstrap_ci(
            values["max_minus_coverage_best"],
            samples=config.bootstrap_samples,
            block=config.bootstrap_block,
            seed=(
                f"{EXPERIMENT_ID}|{game}|{split}|vs-coverage-best"
            ),
        )
        rows.append(
            {
                "game": game,
                "game_name": GAME_NAMES[game],
                "split": split,
                "draws": len(values["max_best"]),
                "rule_best_main_hits": _mean(values["rule_best"]),
                "proposal_coverage_best_main_hits": _mean(
                    values["coverage_best"]
                ),
                "max_coverage_best_main_hits": _mean(
                    values["max_best"]
                ),
                "max_minus_rule_best_main_hits": _mean(
                    values["max_minus_rule_best"]
                ),
                "max_minus_rule_best_ci_low": vs_rule_ci[0],
                "max_minus_rule_best_ci_high": vs_rule_ci[1],
                "max_minus_proposal_coverage_best_main_hits": _mean(
                    values["max_minus_coverage_best"]
                ),
                "max_minus_proposal_coverage_best_ci_low": (
                    vs_coverage_ci[0]
                ),
                "max_minus_proposal_coverage_best_ci_high": (
                    vs_coverage_ci[1]
                ),
                "rule_any_three_plus": _mean(
                    values["rule_any_three"]
                ),
                "proposal_coverage_any_three_plus": _mean(
                    values["coverage_any_three"]
                ),
                "max_coverage_any_three_plus": _mean(
                    values["max_any_three"]
                ),
                "rule_exact_any_prize": _mean(
                    values["rule_exact_any"]
                ),
                "proposal_coverage_exact_any_prize": _mean(
                    values["coverage_exact_any"]
                ),
                "max_coverage_exact_any_prize": _mean(
                    values["max_exact_any"]
                ),
                "max_minus_proposal_coverage_exact_any_prize": _mean(
                    values["max_minus_coverage_exact_any"]
                ),
                "minimum_max_minus_proposal_coverage_exact_any_prize": (
                    min(values["max_minus_coverage_exact_any"])
                ),
                "structural_non_decrease_rate": _mean(
                    values["structural_non_decrease"]
                ),
                "proposal_coverage_exact_three_main": _mean(
                    values["coverage_exact_three"]
                ),
                "max_coverage_exact_three_main": _mean(
                    values["max_exact_three"]
                ),
                "max_minus_proposal_coverage_exact_three_main": _mean(
                    values["max_minus_coverage_exact_three"]
                ),
                "minimum_max_minus_proposal_coverage_exact_three_main": (
                    min(values["max_minus_coverage_exact_three"])
                ),
                "max_union_size": _mean(values["max_union_size"]),
            }
        )
    return rows


def run_max_coverage_study(
    ledger_paths: dict[str, Path],
    *,
    base: Path,
    config: CoverageConfig | None = None,
    verify_ledgers: bool = True,
) -> dict:
    """比較規則、15 候選 coverage 與共識完全分散五注。"""
    config = config or CoverageConfig()
    config.validate()
    base = Path(base)
    records_before = tree_sha256(base / "records")
    verification = {}
    split_profiles = {}
    source_last_dates = {}
    all_metrics = {}
    metric_names = (
        "rule_best",
        "coverage_best",
        "max_best",
        "max_minus_rule_best",
        "max_minus_coverage_best",
        "rule_any_three",
        "coverage_any_three",
        "max_any_three",
        "rule_exact_any",
        "coverage_exact_any",
        "max_exact_any",
        "max_minus_coverage_exact_any",
        "structural_non_decrease",
        "coverage_exact_three",
        "max_exact_three",
        "max_minus_coverage_exact_three",
        "max_union_size",
    )
    for game in (SUPER, LOTTO649):
        path = Path(ledger_paths[game])
        verification[game] = (
            verify_replay(path)
            if verify_ledgers
            else {
                "lines": sum(
                    1
                    for line in path.read_text(
                        encoding="utf-8"
                    ).splitlines()
                    if line.strip()
                )
            }
        )
        total = int(verification[game]["lines"])
        profile, development = _split_profile(total, config)
        split_profiles[game] = profile
        with path.open(encoding="utf-8") as handle:
            for sequence, line in enumerate(handle, 1):
                event = json.loads(line)
                _validate_event(event, game, sequence)
                source_last_dates[game] = event["reveal"]["date"]
                if sequence <= config.warmup_draws:
                    continue
                eligible = sequence - config.warmup_draws
                split = (
                    "development"
                    if eligible <= development
                    else "holdout"
                )
                decision = event["decision"]
                rule = decision["selected_tickets"]
                coverage, coverage_meta = select_coverage_portfolio(
                    game, decision
                )
                maximum, maximum_meta = (
                    select_consensus_disjoint_portfolio(game, decision)
                )
                reveal = event["reveal"]
                rule_result = portfolio_metrics(game, rule, reveal)
                coverage_result = portfolio_metrics(
                    game, coverage, reveal
                )
                maximum_result = portfolio_metrics(
                    game, maximum, reveal
                )
                rule_structure = coverage_meta["baseline"]
                coverage_structure = coverage_meta["selected"]
                maximum_structure = maximum_meta["structure"]
                row = {
                    "rule_best": rule_result["best_main_hits"],
                    "coverage_best": coverage_result["best_main_hits"],
                    "max_best": maximum_result["best_main_hits"],
                    "max_minus_rule_best": (
                        maximum_result["best_main_hits"]
                        - rule_result["best_main_hits"]
                    ),
                    "max_minus_coverage_best": (
                        maximum_result["best_main_hits"]
                        - coverage_result["best_main_hits"]
                    ),
                    "rule_any_three": rule_result["any_three_plus"],
                    "coverage_any_three": coverage_result[
                        "any_three_plus"
                    ],
                    "max_any_three": maximum_result["any_three_plus"],
                    "rule_exact_any": rule_structure[
                        "exact_any_prize"
                    ],
                    "coverage_exact_any": coverage_structure[
                        "exact_any_prize"
                    ],
                    "max_exact_any": maximum_structure[
                        "exact_any_prize"
                    ],
                    "max_minus_coverage_exact_any": (
                        maximum_structure["exact_any_prize"]
                        - coverage_structure["exact_any_prize"]
                    ),
                    "structural_non_decrease": float(
                        maximum_structure["exact_any_prize"]
                        >= coverage_structure["exact_any_prize"]
                        - 1e-15
                        and maximum_structure[
                            "exact_at_least_three_main"
                        ]
                        >= coverage_structure[
                            "exact_at_least_three_main"
                        ]
                        - 1e-15
                    ),
                    "coverage_exact_three": coverage_structure[
                        "exact_at_least_three_main"
                    ],
                    "max_exact_three": maximum_structure[
                        "exact_at_least_three_main"
                    ],
                    "max_minus_coverage_exact_three": (
                        maximum_structure[
                            "exact_at_least_three_main"
                        ]
                        - coverage_structure[
                            "exact_at_least_three_main"
                        ]
                    ),
                    "max_union_size": maximum_structure[
                        "main_union_size"
                    ],
                }
                key = (game, split)
                all_metrics.setdefault(
                    key, {name: [] for name in metric_names}
                )
                for name in metric_names:
                    all_metrics[key][name].append(float(row[name]))

    summary = _summary(all_metrics, config)
    holdout = {
        row["game"]: row
        for row in summary
        if row["split"] == "holdout"
    }
    structural_pass = {
        game: (
            row["structural_non_decrease_rate"] == 1.0
            and row[
                "minimum_max_minus_proposal_coverage_exact_any_prize"
            ]
            >= -1e-15
            and row[
                "max_minus_proposal_coverage_exact_any_prize"
            ]
            > 0
            and row[
                "minimum_max_minus_proposal_coverage_exact_three_main"
            ]
            >= -1e-15
            and row[
                "max_minus_proposal_coverage_exact_three_main"
            ]
            > 0
            and row["max_union_size"] == SELECTED_MAIN_NUMBERS
        )
        for game, row in holdout.items()
    }
    records_after = tree_sha256(base / "records")
    if records_before != records_after:
        raise RuntimeError("最大覆蓋研究不應改動正式 records")
    return {
        "schema_version": "1",
        "experiment_id": EXPERIMENT_ID,
        "source_experiment_id": LOOP_EXPERIMENT_ID,
        "generated_at": max(source_last_dates.values())
        + "T23:59:59+08:00",
        "question": (
            "在保留 Agent 開獎前共識排序的同時，合成 30 個互斥主號與"
            "威力彩五個互異第二區，能否比 15 選 5 coverage 再提高"
            "完整任一獎級機率？"
        ),
        "methodology": {
            "warmup_draws": config.warmup_draws,
            "development_fraction": config.development_fraction,
            "bootstrap_samples": config.bootstrap_samples,
            "bootstrap_block_draws": config.bootstrap_block,
            "lookahead_control": (
                "selector 函式不接受 reveal；開獎只在五注合成後計算"
                "回顧性命中。"
            ),
            "selection_budget": "每期固定五注",
            "official_prize_rules": OFFICIAL_RULE_URLS,
            "construction": (
                "以 15 組提案辯論分數彙總每個號碼支持，選前 30 個"
                "不同主號並平均分散成五注；威力彩選五個不同第二區。"
            ),
            "structural_optimum_proof": structural_proof_reference(),
        },
        "data_quality": {
            "status": "pass",
            "ledger_verification": verification,
            "split_profiles": split_profiles,
            "source_last_dates": source_last_dates,
        },
        "summary": summary,
        "conclusion": {
            "status": (
                "eligible_for_forward_shadow"
                if all(structural_pass.values())
                else "retain_proposal_coverage"
            ),
            "structural_probability_pass": structural_pass,
            "decision_rule": (
                "兩款遊戲 holdout 每期完整任一獎級與三主號精確機率"
                "均不得低於 proposal coverage，且平均完整機率必須"
                "嚴格提高；完全分散結構另由有限整數證明確認為全域"
                "最大，命中區間只作診斷。"
            ),
        },
        "records_integrity": {
            "before_sha256": records_before,
            "after_sha256": records_after,
            "unchanged": records_before == records_after,
        },
        "limitations": [
            "結構證明最大化五注聯集事件，不代表任何號碼標籤更容易開出。",
            "Agent 共識只決定同機率結構中的號碼標籤，不改變單注機率。",
            "回顧性命中差不能代替新期前向 shadow。",
            "純模擬，不構成購買或下注建議。",
        ],
    }


def write_results(result: dict, output_dir: Path) -> dict[str, Path]:
    result.setdefault("methodology", {})[
        "official_prize_rules"
    ] = OFFICIAL_RULE_URLS
    result["methodology"][
        "structural_optimum_proof"
    ] = structural_proof_reference()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "json": output_dir / "max_coverage.json",
        "summary": output_dir / "max_coverage_summary.csv",
    }
    temporary = paths["json"].with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, paths["json"])
    rows = result["summary"]
    with paths["summary"].open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return paths
