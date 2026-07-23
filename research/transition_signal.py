"""前一期號碼對下一期主號標籤的條件轉移訊號稽核。

這個研究刻意不重測已覆蓋的熱號、冷號、gap 或同期共現。候選只使用
目標期以前的 lag-1／lag-2 轉移計數；每期評分後才更新狀態。完整歷史
已被其他研究檢視，因此任何結果都只能產生未來 forward shadow，不能
直接替換正式號碼。
"""
from __future__ import annotations

import csv
from collections import Counter, deque
from copy import deepcopy
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import statistics

from engine.agent_loop import (
    LOOP_EXPERIMENT_ID,
    canonical_hash,
    verify_replay,
)
from engine.games import (
    GAME_NAMES,
    LOTTO649,
    PICK_N,
    POOL,
    SUPER,
)
from research.agent_ablation import (
    _validate_event,
    block_bootstrap_ci,
)
from research.gates import tree_sha256
from research.label_signal import (
    GUARDRAILS,
    METRICS,
    _holm_adjust,
    _realized_metrics,
    _tickets_from_ranking,
)
from research.max_coverage import (
    _support_rows,
    select_consensus_disjoint_portfolio,
)
from research.mechanism_signal import (
    _exact_total_hit_upper_tail,
    _profile_events,
)
from research.structural_optimum import structural_proof_reference


EXPERIMENT_ID = "lag-transition-signal-audit-v1"
FORWARD_EXPERIMENT_ID = "lag-transition-forward-shadow-v1"
SELECTED_MAIN_NUMBERS = 30
TRANSITION_LAGS = (1, 2)
ROLLING_WINDOWS = (260, 520)
PRIOR_STRENGTH = 50.0
TRANSITION_CANDIDATES = (
    "lag1_all_probability",
    "lag1_all_lift",
    "lag1_520_lift",
    "lag1_260_lift",
    "lag2_all_lift",
    "lag12_all_lift",
    "consensus_lag1_all_mix",
    "consensus_lag12_all_mix",
)
PRIMARY_METRIC = "union_main_hits"


@dataclass(frozen=True)
class TransitionSignalConfig:
    warmup_draws: int = 60
    development_fraction: float = 0.70
    inner_training_fraction: float = 0.70
    bootstrap_samples: int = 2_000
    bootstrap_block: int = 13

    def validate(self) -> None:
        if self.warmup_draws < 2:
            raise ValueError("transition signal warmup 至少為 2")
        if not 0.5 <= self.development_fraction < 1:
            raise ValueError(
                "development_fraction 必須介於 0.5 與 1"
            )
        if not 0.5 <= self.inner_training_fraction < 1:
            raise ValueError(
                "inner_training_fraction 必須介於 0.5 與 1"
            )
        if self.bootstrap_samples < 100:
            raise ValueError("bootstrap_samples 至少為 100")
        if self.bootstrap_block < 1:
            raise ValueError("bootstrap_block 至少為 1")


def transition_protocol_reference() -> dict:
    """回傳結果揭曉前固定的候選與統計決策契約。"""
    payload = {
        "experiment_id": EXPERIMENT_ID,
        "candidates": list(TRANSITION_CANDIDATES),
        "lags": list(TRANSITION_LAGS),
        "rolling_windows": list(ROLLING_WINDOWS),
        "prior_strength": PRIOR_STRENGTH,
        "selected_main_numbers": SELECTED_MAIN_NUMBERS,
        "primary_metric": PRIMARY_METRIC,
        "guardrails": list(GUARDRAILS),
        "selection": (
            "inner validation 只選一個相對 consensus 主要指標正向且"
            "全部護欄不下降的候選"
        ),
        "holdout": (
            "全 16 項候選×遊戲 exact-null p 共用 Holm；選中候選"
            "另須 paired block-bootstrap 下界>0、前後半正向且"
            "護欄不下降"
        ),
    }
    return {
        **payload,
        "protocol_hash": canonical_hash(payload),
    }


def verify_transition_protocol(reference: dict) -> None:
    expected = transition_protocol_reference()
    if reference != expected:
        raise ValueError("transition signal 預註冊契約不符")


def _initial_transition_state(game: str) -> dict:
    if game not in (SUPER, LOTTO649):
        raise ValueError(f"不支援的遊戲：{game}")
    return {
        "game": game,
        "history": deque(maxlen=max(TRANSITION_LAGS)),
        "all": {
            lag: {
                "transitions": 0,
                "source_counts": Counter(),
                "target_counts": Counter(),
                "pair_counts": Counter(),
            }
            for lag in TRANSITION_LAGS
        },
        "recent": {
            lag: deque(maxlen=max(ROLLING_WINDOWS))
            for lag in TRANSITION_LAGS
        },
        "draws_seen": 0,
    }


def _add_transition(
    stats: dict,
    source: tuple[int, ...],
    target: tuple[int, ...],
) -> None:
    stats["transitions"] += 1
    stats["source_counts"].update(source)
    stats["target_counts"].update(target)
    stats["pair_counts"].update(
        (left, right)
        for left in source
        for right in target
    )


def _update_transition_state(
    state: dict,
    numbers: list[int] | tuple[int, ...],
) -> None:
    """揭曉後更新；預測函式不接收當期 reveal。"""
    game = state.get("game")
    target = tuple(sorted(int(number) for number in numbers))
    if (
        len(target) != PICK_N
        or len(set(target)) != PICK_N
        or any(not 1 <= number <= POOL[game] for number in target)
    ):
        raise ValueError("transition state 收到非法主號")
    history = state["history"]
    for lag in TRANSITION_LAGS:
        if len(history) < lag:
            continue
        source = tuple(history[-lag])
        _add_transition(state["all"][lag], source, target)
        state["recent"][lag].append((source, target))
    history.append(target)
    state["draws_seen"] += 1


def _rolling_statistics(state: dict, lag: int, window: int) -> dict:
    rows = list(state["recent"][lag])[-window:]
    stats = {
        "transitions": 0,
        "source_counts": Counter(),
        "target_counts": Counter(),
        "pair_counts": Counter(),
    }
    for source, target in rows:
        _add_transition(stats, source, target)
    return stats


def _transition_scores(
    state: dict,
    *,
    lag: int,
    window: int | None,
    lift: bool,
) -> dict[int, float]:
    if len(state["history"]) < lag:
        return {
            number: 0.0
            for number in range(1, POOL[state["game"]] + 1)
        }
    stats = (
        state["all"][lag]
        if window is None
        else _rolling_statistics(state, lag, window)
    )
    game = state["game"]
    pool = POOL[game]
    base = PICK_N / pool
    source = state["history"][-lag]
    transitions = stats["transitions"]
    scores = {}
    for target in range(1, pool + 1):
        conditional = statistics.fmean(
            (
                stats["pair_counts"][(left, target)]
                + PRIOR_STRENGTH * base
            )
            / (
                stats["source_counts"][left]
                + PRIOR_STRENGTH
            )
            for left in source
        )
        if lift:
            marginal = (
                stats["target_counts"][target]
                + PRIOR_STRENGTH * base
            ) / (transitions + PRIOR_STRENGTH)
            conditional -= marginal
        scores[target] = conditional
    return scores


def _rank_scores(scores: dict[int, float]) -> list[int]:
    return sorted(
        scores,
        key=lambda number: (-scores[number], number),
    )


def _average_scores(*rows: dict[int, float]) -> dict[int, float]:
    return {
        number: statistics.fmean(row[number] for row in rows)
        for number in rows[0]
    }


def _mixed_ranking(
    transition_ranking: list[int],
    consensus_ranking: list[int],
) -> list[int]:
    transition_position = {
        number: position
        for position, number in enumerate(transition_ranking)
    }
    consensus_position = {
        number: position
        for position, number in enumerate(consensus_ranking)
    }
    return sorted(
        transition_position,
        key=lambda number: (
            transition_position[number]
            + consensus_position[number],
            consensus_position[number],
            transition_position[number],
            number,
        ),
    )


def candidate_transition_rankings(
    game: str,
    decision: dict,
    state: dict,
) -> dict[str, list[int]]:
    """只使用目標期以前狀態與已封存辯論建立固定候選排序。"""
    if decision.get("game") != game:
        raise ValueError("transition decision 遊戲不符")
    if state.get("game") != game:
        raise ValueError("transition state 遊戲不符")
    lag1_probability = _rank_scores(
        _transition_scores(
            state, lag=1, window=None, lift=False
        )
    )
    lag1_lift_scores = _transition_scores(
        state, lag=1, window=None, lift=True
    )
    lag2_lift_scores = _transition_scores(
        state, lag=2, window=None, lift=True
    )
    lag1_lift = _rank_scores(lag1_lift_scores)
    lag12_lift = _rank_scores(
        _average_scores(lag1_lift_scores, lag2_lift_scores)
    )
    consensus = [
        row["number"] for row in _support_rows(game, decision)
    ]
    rankings = {
        "lag1_all_probability": lag1_probability,
        "lag1_all_lift": lag1_lift,
        "lag1_520_lift": _rank_scores(
            _transition_scores(
                state, lag=1, window=520, lift=True
            )
        ),
        "lag1_260_lift": _rank_scores(
            _transition_scores(
                state, lag=1, window=260, lift=True
            )
        ),
        "lag2_all_lift": _rank_scores(lag2_lift_scores),
        "lag12_all_lift": lag12_lift,
        "consensus_lag1_all_mix": _mixed_ranking(
            lag1_lift, consensus
        ),
        "consensus_lag12_all_mix": _mixed_ranking(
            lag12_lift, consensus
        ),
    }
    expected = list(range(1, POOL[game] + 1))
    if tuple(rankings) != TRANSITION_CANDIDATES:
        raise RuntimeError("transition candidate 集合或順序不符")
    if any(sorted(ranking) != expected for ranking in rankings.values()):
        raise RuntimeError("transition candidate 未形成完整號碼排列")
    return rankings


def _split_profile(
    total_draws: int,
    config: TransitionSignalConfig,
) -> dict:
    eligible = total_draws - config.warmup_draws
    if eligible < 20:
        raise ValueError("transition signal 暖機後資料不足")
    development = math.floor(
        eligible * config.development_fraction
    )
    inner_training = math.floor(
        development * config.inner_training_fraction
    )
    inner_validation = development - inner_training
    holdout = eligible - development
    if min(inner_training, inner_validation, holdout) < 5:
        raise ValueError("transition signal 時間切分資料不足")
    return {
        "total_draws": total_draws,
        "warmup_draws": config.warmup_draws,
        "eligible_draws": eligible,
        "development_draws": development,
        "inner_training_draws": inner_training,
        "inner_validation_draws": inner_validation,
        "holdout_draws": holdout,
    }


def _mean(
    rows: list[dict],
    candidate: str,
    metric: str,
) -> float:
    return statistics.fmean(
        row[candidate][metric] for row in rows
    )


def _metric_deltas(
    rows: list[dict],
    candidate: str,
) -> dict[str, float]:
    return {
        metric: (
            _mean(rows, candidate, metric)
            - _mean(rows, "consensus", metric)
        )
        for metric in METRICS
    }


def _choose_inner_candidate(rows: list[dict]) -> str:
    eligible = []
    for candidate in TRANSITION_CANDIDATES:
        deltas = _metric_deltas(rows, candidate)
        if deltas[PRIMARY_METRIC] > 0 and all(
            deltas[metric] >= -1e-15
            for metric in GUARDRAILS
        ):
            eligible.append(
                (
                    -deltas[PRIMARY_METRIC],
                    -sum(deltas[metric] for metric in GUARDRAILS),
                    candidate,
                )
            )
    if not eligible:
        return "consensus"
    eligible.sort()
    return eligible[0][2]


def _candidate_holdout_row(
    game: str,
    candidate: str,
    inner_validation: list[dict],
    holdout: list[dict],
    config: TransitionSignalConfig,
) -> dict:
    inner_deltas = _metric_deltas(inner_validation, candidate)
    vectors = {
        metric: [
            row[candidate][metric] - row["consensus"][metric]
            for row in holdout
        ]
        for metric in METRICS
    }
    holdout_deltas = {
        metric: statistics.fmean(values)
        for metric, values in vectors.items()
    }
    interval = block_bootstrap_ci(
        vectors[PRIMARY_METRIC],
        samples=config.bootstrap_samples,
        block=config.bootstrap_block,
        seed=(
            f"{EXPERIMENT_ID}|{game}|{candidate}|holdout|"
            f"{PRIMARY_METRIC}"
        ),
    )
    midpoint = len(holdout) // 2
    observed = round(
        sum(row[candidate][PRIMARY_METRIC] for row in holdout)
    )
    return {
        "game": game,
        "game_name": GAME_NAMES[game],
        "candidate": candidate,
        "inner_validation_draws": len(inner_validation),
        **{
            f"inner_validation_{metric}_delta_vs_consensus": value
            for metric, value in inner_deltas.items()
        },
        "holdout_draws": len(holdout),
        "holdout_observed_union_main_hits": observed,
        "holdout_exact_null_mean_union_main_hits": (
            PICK_N * SELECTED_MAIN_NUMBERS / POOL[game]
        ),
        **{
            f"holdout_{metric}_delta_vs_consensus": value
            for metric, value in holdout_deltas.items()
        },
        "holdout_union_main_hits_ci_low": interval[0],
        "holdout_union_main_hits_ci_high": interval[1],
        "holdout_first_half_union_delta_vs_consensus": (
            statistics.fmean(
                vectors[PRIMARY_METRIC][:midpoint]
            )
        ),
        "holdout_second_half_union_delta_vs_consensus": (
            statistics.fmean(
                vectors[PRIMARY_METRIC][midpoint:]
            )
        ),
        "holdout_raw_exact_null_one_sided_p_value": (
            _exact_total_hit_upper_tail(
                game,
                len(holdout),
                observed,
            )
        ),
    }


def _summary_rows(
    game: str,
    split: str,
    rows: list[dict],
) -> list[dict]:
    return [
        {
            "game": game,
            "game_name": GAME_NAMES[game],
            "split": split,
            "candidate": candidate,
            "draws": len(rows),
            **{
                metric: _mean(rows, candidate, metric)
                for metric in METRICS
            },
            **{
                f"{metric}_minus_consensus": (
                    _mean(rows, candidate, metric)
                    - _mean(rows, "consensus", metric)
                )
                for metric in METRICS
            },
        }
        for candidate in ("consensus", *TRANSITION_CANDIDATES)
    ]


def _build_forward_protocol(
    decisions: dict[str, dict],
    source_last_dates: dict[str, str],
) -> dict:
    algorithms = {
        game: decisions[game]["inner_selected_candidate"]
        for game in (SUPER, LOTTO649)
    }
    registration_eligible = any(
        candidate != "consensus"
        for candidate in algorithms.values()
    )
    payload = {
        "experiment_id": FORWARD_EXPERIMENT_ID,
        "source_experiment_id": EXPERIMENT_ID,
        "source_protocol_hash": transition_protocol_reference()[
            "protocol_hash"
        ],
        "frozen_source_last_dates": deepcopy(source_last_dates),
        "algorithms": algorithms,
        "online_refit": (
            "候選演算法固定；每次只用目標期以前的全部正式開獎"
            "更新轉移計數，再凍結下一期 30 號"
        ),
        "registration_eligible": registration_eligible,
        "registration_reason": (
            "inner validation 至少選出一個非 consensus 候選"
            if registration_eligible
            else "兩款遊戲 inner validation 都保留 consensus；"
            "不建立與控制臂相同的重複 shadow"
        ),
        "promotion_eligible": False,
        "use": "future_forward_shadow_only",
        "structural_optimum_proof": structural_proof_reference(),
    }
    return {
        **payload,
        "candidate_hash": canonical_hash(payload),
    }


def run_transition_signal_study(
    ledger_paths: dict[str, Path],
    *,
    base: Path,
    config: TransitionSignalConfig | None = None,
    verify_ledgers: bool = True,
) -> dict:
    """逐期稽核條件轉移排序，inner validation 選模、holdout 開封。"""
    config = config or TransitionSignalConfig()
    config.validate()
    protocol = transition_protocol_reference()
    verify_transition_protocol(protocol)
    base = Path(base)
    records_before = tree_sha256(base / "records")
    proof_path = (
        base / "research" / "results" / "structural_optimum.json"
    )
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    if (
        proof.get("certificate_hash")
        != structural_proof_reference()["certificate_hash"]
    ):
        raise RuntimeError("transition signal 結構證明來源不符")

    profiles = {}
    verifications = {}
    splits = {}
    source_last_dates = {}
    all_summary_rows = []
    candidate_rows = []
    decisions = {}

    for game in (SUPER, LOTTO649):
        path = Path(ledger_paths[game])
        verification = (
            verify_replay(path)
            if verify_ledgers
            else {
                "lines": sum(
                    1 for line in path.open(encoding="utf-8")
                    if line.strip()
                )
            }
        )
        verifications[game] = verification
        events = []
        with path.open(encoding="utf-8") as handle:
            for sequence, line in enumerate(handle, 1):
                event = json.loads(line)
                _validate_event(event, game, sequence)
                events.append(event)
        profile = _profile_events(game, events)
        if profile["quality_status"] != "pass":
            raise RuntimeError(
                f"{game} transition data quality 失敗"
            )
        profile["off_schedule_treatment"] = (
            "保留所有合法春節加開；transition 依實際時間順序"
            "更新，不把星期外開獎刪除或改標。"
        )
        profiles[game] = profile
        source_last_dates[game] = profile["last_date"]
        split = _split_profile(len(events), config)
        splits[game] = split

        state = _initial_transition_state(game)
        eligible_rows = []
        for sequence, event in enumerate(events, 1):
            decision = event["decision"]
            if sequence > config.warmup_draws:
                rankings = candidate_transition_rankings(
                    game, decision, state
                )
                consensus, _ = (
                    select_consensus_disjoint_portfolio(
                        game, decision
                    )
                )
                reveal = event["reveal"]
                eligible_rows.append(
                    {
                        "consensus": _realized_metrics(
                            game, consensus, reveal
                        ),
                        **{
                            candidate: _realized_metrics(
                                game,
                                _tickets_from_ranking(
                                    game, decision, ranking
                                ),
                                reveal,
                            )
                            for candidate, ranking in rankings.items()
                        },
                    }
                )
            _update_transition_state(
                state, event["reveal"]["numbers"]
            )
        if len(eligible_rows) != split["eligible_draws"]:
            raise RuntimeError(
                "transition signal eligible 期數不符"
            )
        development = eligible_rows[
            : split["development_draws"]
        ]
        inner_validation = development[
            split["inner_training_draws"] :
        ]
        holdout = eligible_rows[split["development_draws"] :]
        all_summary_rows.extend(
            _summary_rows(
                game, "inner_validation", inner_validation
            )
        )
        all_summary_rows.extend(
            _summary_rows(game, "holdout", holdout)
        )
        selected = _choose_inner_candidate(inner_validation)
        decisions[game] = {
            "inner_selected_candidate": selected,
            "inner_selection_used_holdout": False,
        }
        for candidate in TRANSITION_CANDIDATES:
            candidate_rows.append(
                _candidate_holdout_row(
                    game,
                    candidate,
                    inner_validation,
                    holdout,
                    config,
                )
            )

    raw = {
        f"{row['game']}:{row['candidate']}": row[
            "holdout_raw_exact_null_one_sided_p_value"
        ]
        for row in candidate_rows
    }
    adjusted = _holm_adjust(raw)
    for row in candidate_rows:
        key = f"{row['game']}:{row['candidate']}"
        row["holm_adjusted_exact_null_one_sided_p_value"] = (
            adjusted[key]
        )

    for game in (SUPER, LOTTO649):
        selected = decisions[game]["inner_selected_candidate"]
        selected_row = next(
            (
                row
                for row in candidate_rows
                if row["game"] == game
                and row["candidate"] == selected
            ),
            None,
        )
        eligible = bool(
            selected_row
            and selected != "consensus"
            and selected_row[
                "inner_validation_union_main_hits_delta_vs_consensus"
            ]
            > 0
            and all(
                selected_row[
                    f"inner_validation_{metric}_delta_vs_consensus"
                ]
                >= -1e-15
                for metric in GUARDRAILS
            )
            and selected_row[
                "holm_adjusted_exact_null_one_sided_p_value"
            ]
            < 0.05
            and selected_row["holdout_union_main_hits_ci_low"] > 0
            and selected_row[
                "holdout_first_half_union_delta_vs_consensus"
            ]
            > 0
            and selected_row[
                "holdout_second_half_union_delta_vs_consensus"
            ]
            > 0
            and all(
                selected_row[
                    f"holdout_{metric}_delta_vs_consensus"
                ]
                >= -1e-15
                for metric in GUARDRAILS
            )
        )
        decisions[game].update(
            {
                "historical_promotion_eligible": eligible,
                "decision": (
                    f"future_shadow_{selected}"
                    if selected != "consensus"
                    else "retain_consensus"
                ),
                "holdout_evidence": selected_row,
            }
        )

    records_after = tree_sha256(base / "records")
    if records_before != records_after:
        raise RuntimeError(
            "transition signal 研究不應改動正式 records"
        )
    any_eligible = any(
        row["historical_promotion_eligible"]
        for row in decisions.values()
    )
    forward_protocol = _build_forward_protocol(
        decisions, source_last_dates
    )
    return {
        "schema_version": "1",
        "experiment_id": EXPERIMENT_ID,
        "source_experiment_id": LOOP_EXPERIMENT_ID,
        "generated_at": max(source_last_dates.values())
        + "T23:59:59+08:00",
        "question": (
            "上一期或上兩期主號，是否對下一期 30 號標籤存在"
            "可跨時間重現的條件轉移訊號，並能勝過現行 Agent 共識？"
        ),
        "protocol": protocol,
        "methodology": {
            "warmup_draws": config.warmup_draws,
            "development_fraction": config.development_fraction,
            "inner_training_fraction": (
                config.inner_training_fraction
            ),
            "bootstrap_samples": config.bootstrap_samples,
            "bootstrap_block_draws": config.bootstrap_block,
            "candidates": list(TRANSITION_CANDIDATES),
            "prior_strength": PRIOR_STRENGTH,
            "rolling_windows": list(ROLLING_WINDOWS),
            "primary_metric": PRIMARY_METRIC,
            "guardrails": list(GUARDRAILS),
            "nested_selection": (
                "inner training 只累積狀態；inner validation 選唯一"
                "候選；外層 holdout 不得改選。"
            ),
            "multiple_testing": (
                "8 候選×2 遊戲共 16 個 holdout exact-null"
                "單尾 p 使用 Holm family-wise correction。"
            ),
            "promotion_gate": (
                "inner validation 主要指標正向且護欄不降；"
                "Holm p<0.05；holdout 13 期區塊 bootstrap"
                "下界>0；前後半皆正向且三個護欄不下降。"
            ),
            "lookahead_control": (
                "candidate_transition_rankings 不接受 reveal；"
                "當期評分完成後才更新 lag transition state。"
            ),
            "historical_reuse": (
                "歷史已被其他研究檢視；即使通過也只建立"
                "未來 forward shadow，不直接升級。"
            ),
            "structural_optimum_proof": (
                structural_proof_reference()
            ),
        },
        "data_quality": {
            "status": (
                "pass"
                if all(
                    profile["quality_status"] == "pass"
                    for profile in profiles.values()
                )
                else "fail"
            ),
            "profiles": profiles,
            "ledger_verification": verifications,
            "split_profiles": splits,
            "source_last_dates": source_last_dates,
        },
        "summary": all_summary_rows,
        "candidate_holdout": candidate_rows,
        "decisions": decisions,
        "future_forward_shadow_protocol": forward_protocol,
        "conclusion": {
            "status": (
                "historical_transition_signal_detected_shadow_only"
                if any_eligible
                else "no_confirmed_transition_signal"
            ),
            "any_historical_promotion_eligible": any_eligible,
            "forward_action": (
                "inner validation 未選出任何非 consensus 候選；"
                "不新增重複 shadow，也不改寫既有 7/20、7/21"
                " 登記。若未來提出新假說，必須使用新 experiment ID。"
                if not forward_protocol["registration_eligible"]
                else "只可把 inner-validation 預選演算法凍結為"
                "未來配對 shadow；不得改寫既有 7/20、7/21 登記。"
            ),
        },
        "records_integrity": {
            "before_sha256": records_before,
            "after_sha256": records_after,
            "unchanged": records_before == records_after,
        },
        "limitations": [
            "條件轉移矩陣維度高，已用固定 prior shrinkage 降低稀疏估計波動。",
            "完整歷史不是全新的確認性樣本，只有未來前向配對能確認。",
            "候選仍維持 30 個互斥主號，理論結構機率不變。",
            "公平獨立開獎下條件轉移理論上為零；本研究是可被否證的機制稽核。",
            "純模擬，不構成購買或下注建議。",
        ],
    }


def write_results(
    result: dict,
    output_dir: Path,
) -> dict[str, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "json": output_dir / "transition_signal.json",
        "candidates": (
            output_dir / "transition_signal_candidates.csv"
        ),
    }
    temporary = paths["json"].with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, paths["json"])
    rows = result["candidate_holdout"]
    with paths["candidates"].open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(rows[0])
        )
        writer.writeheader()
        writer.writerows(rows)
    return paths
