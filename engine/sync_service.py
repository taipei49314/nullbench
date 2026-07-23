"""官方開獎偵測與 agent 閉環結果同步。

只重抓當月官方 API。若偵測到新期數，才重建完整逐期回放與下一期決策；
沒有新資料時保持既有可稽核產物不變。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from . import agent_loop, forward_lab, qwen_judge
from .env import Env
from .fetch import ingest
from .forward_feedback import FEEDBACK_EXPERIMENT_ID
from .games import GAME_NAMES, LOTTO649, SUPER
from .ledger import TAIPEI

GAMES = (SUPER, LOTTO649)
Progress = Callable[[str, str, Optional[dict]], None]
FeedbackProvider = Callable[[str, dict], dict]


def _current_ledger_hashes(base: Path) -> dict[str, str] | None:
    """Return replay content hashes when both canonical ledgers exist."""
    output_dir = Path(base) / "simulation" / "results"
    hashes = {}
    for game in GAMES:
        path = output_dir / f"{game}.jsonl"
        if not path.exists():
            return None
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        hashes[game] = digest.hexdigest()
    return hashes


def _study_ledger_hashes(study: dict) -> dict[str, str] | None:
    verification = study.get("data_quality", {}).get(
        "ledger_verification"
    )
    if not isinstance(verification, dict):
        return None
    hashes = {
        game: verification.get(game, {}).get("ledger_sha256")
        for game in GAMES
    }
    if any(not isinstance(value, str) for value in hashes.values()):
        return None
    return hashes


def _run_with_qwen(
    store,
    output_dir: Path,
    feedback_provider: FeedbackProvider,
) -> dict:
    def final_judge(decision: dict) -> dict:
        feedback = feedback_provider(
            decision["game"],
            decision["target"],
        )
        return qwen_judge.adjudicate(
            decision,
            feedback=feedback,
        )

    return agent_loop.run_all(
        store,
        output_dir,
        final_judge=final_judge,
    )


def _read_manifest(output_dir: Path) -> dict | None:
    path = output_dir / "manifest.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _probability_stacking_stale(
    base: Path,
    manifest: dict,
) -> bool:
    path = (
        Path(base)
        / "research"
        / "results"
        / "probability_stacking.json"
    )
    try:
        from research.probability_stacking import (
            validate_forward_candidate,
        )

        study = json.loads(path.read_text(encoding="utf-8"))
        candidate = validate_forward_candidate(
            study["future_forward_shadow_candidate"]
        )
        strength_path = (
            Path(base)
            / "research"
            / "results"
            / "decision_strength.json"
        )
        strength = json.loads(
            strength_path.read_text(encoding="utf-8")
        )
        strength_payload = {
            key: value
            for key, value in strength.items()
            if key != "audit_hash"
        }
        if strength.get("audit_hash") != agent_loop.canonical_hash(
            strength_payload
        ):
            return True
    except (
        KeyError,
        OSError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ):
        return True
    source_dates = study.get("data_quality", {}).get(
        "source_last_dates", {}
    )
    expected_dates = {
        game: manifest["games"][game]["last_target"]["date"]
        for game in GAMES
    }
    current_ledger_hashes = _current_ledger_hashes(base)
    return (
        study.get("schema_version") != "1"
        or study.get("conclusion", {}).get("status")
        != "future_shadow_only"
        or study.get("conclusion", {}).get(
            "historical_promotion_eligible"
        )
        is not False
        or source_dates != expected_dates
        or candidate["fitted_through"] != expected_dates
        or strength.get("source", {}).get("fitted_through")
        != expected_dates
        or strength.get("source", {}).get("manifest_hash")
        != manifest["manifest_hash"]
        or strength.get("decision", {}).get("status")
        != "retain_existing_future_shadow_only"
        or (
            current_ledger_hashes is not None
            and candidate["source_ledger_hashes"]
            != current_ledger_hashes
        )
    )


def _switching_bayes_stale(
    base: Path,
    manifest: dict,
) -> bool:
    path = (
        Path(base)
        / "research"
        / "results"
        / "switching_bayes.json"
    )
    # v2 is an additive shadow.  Repositories that have not explicitly
    # initialized the formal artifact keep the existing loop unchanged.
    if not path.exists():
        return False
    try:
        from research.switching_bayes import (
            validate_forward_candidate,
        )

        study = json.loads(path.read_text(encoding="utf-8"))
        candidate = validate_forward_candidate(
            study["future_forward_shadow_candidate"]
        )
    except (
        KeyError,
        OSError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ):
        return True
    expected_dates = {
        game: manifest["games"][game]["last_target"]["date"]
        for game in GAMES
    }
    current_ledger_hashes = _current_ledger_hashes(base)
    return (
        study.get("schema_version") != "1"
        or study.get("decision", {}).get("status")
        != "future_shadow_only"
        or study.get("decision", {}).get(
            "belief_layer_promoted"
        )
        is not False
        or study.get("data_quality", {}).get(
            "source_last_dates"
        )
        != expected_dates
        or candidate["fitted_through"] != expected_dates
        or study.get("records_integrity", {}).get("unchanged")
        is not True
        or (
            current_ledger_hashes is not None
            and _study_ledger_hashes(study)
            != current_ledger_hashes
        )
    )


def _null_safe_probability_stale(
    base: Path,
    manifest: dict,
) -> bool:
    formal_path = (
        Path(base)
        / "research"
        / "results"
        / "null_safe_probability.json"
    )
    forward_path = (
        Path(base)
        / "research"
        / "results"
        / "null_safe_probability_forward.json"
    )
    try:
        from research.null_safe_probability import (
            validate_forward_state_artifact,
            validate_forward_candidate,
        )
        from research.probability_stacking import (
            validate_forward_candidate as validate_stacking_candidate,
        )

        if forward_path.exists():
            study = validate_forward_state_artifact(
                json.loads(forward_path.read_text(encoding="utf-8"))
            )
            candidate = validate_forward_candidate(
                study["future_forward_shadow_candidate"]
            )
            formal_study = None
        else:
            study = json.loads(
                formal_path.read_text(encoding="utf-8")
            )
            candidate = validate_forward_candidate(
                study["future_forward_shadow_candidate"]
            )
            formal_study = study
        stacking_study = json.loads(
            (
                Path(base)
                / "research"
                / "results"
                / "probability_stacking.json"
            ).read_text(encoding="utf-8")
        )
        stacking_candidate = validate_stacking_candidate(
            stacking_study["future_forward_shadow_candidate"]
        )
    except (
        KeyError,
        OSError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ):
        return True
    expected_dates = {
        game: manifest["games"][game]["last_target"]["date"]
        for game in GAMES
    }
    current_ledger_hashes = _current_ledger_hashes(base)
    return (
        (
            formal_study is not None
            and (
                formal_study.get("schema_version") != "1"
                or formal_study.get("conclusion", {}).get("status")
                != "candidate_ready_future_shadow"
                or formal_study.get("conclusion", {}).get(
                    "historical_promotion_eligible"
                )
                is not False
                or formal_study.get(
                    "records_integrity", {}
                ).get("unchanged")
                is not True
                or formal_study.get("data_quality", {}).get(
                    "source_last_dates"
                )
                != expected_dates
            )
        )
        or candidate["fitted_through"] != expected_dates
        or candidate["fitted_through"]
        != stacking_candidate["fitted_through"]
        or candidate["source_ledger_hashes"]
        != stacking_candidate["source_ledger_hashes"]
        or (
            current_ledger_hashes is not None
            and candidate["source_ledger_hashes"]
            != current_ledger_hashes
        )
        or any(
            candidate["models"][game]["main_log_weights"]
            != stacking_candidate["models"][game][
                "main_log_weights"
            ]
            or candidate["models"][game]["main_weights"]
            != stacking_candidate["models"][game]["main_weights"]
            or (
                game == SUPER
                and (
                    candidate["models"][game][
                        "special_log_weights"
                    ]
                    != stacking_candidate["models"][game][
                        "special_log_weights"
                    ]
                    or candidate["models"][game][
                        "special_weights"
                    ]
                    != stacking_candidate["models"][game][
                        "special_weights"
                    ]
                )
            )
            for game in GAMES
        )
    )


def _shadow_research_stale(base: Path, manifest: dict) -> bool:
    results = Path(base) / "research" / "results"
    current_ledger_hashes = _current_ledger_hashes(base)
    for name in (
        "council_quality.json",
        "max_coverage.json",
        "label_signal.json",
        "partition_signal.json",
        "mechanism_signal.json",
    ):
        path = results / name
        try:
            study = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return True
        source_dates = study.get("data_quality", {}).get(
            "source_last_dates", {}
        )
        if any(
            source_dates.get(game)
            != manifest["games"][game]["last_target"]["date"]
            for game in GAMES
        ):
            return True
        if (
            current_ledger_hashes is not None
            and _study_ledger_hashes(study)
            != current_ledger_hashes
        ):
            return True
        if name == "max_coverage.json":
            from research.structural_optimum import (
                structural_proof_reference,
            )

            summary = study.get("summary", ())
            if (
                study.get("schema_version") != "1"
                or study.get("methodology", {}).get(
                    "structural_optimum_proof"
                )
                != structural_proof_reference()
                or len(summary) != 4
                or any(
                    not {
                        "proposal_coverage_exact_any_prize",
                        "max_coverage_exact_any_prize",
                        (
                            "minimum_max_minus_"
                            "proposal_coverage_exact_any_prize"
                        ),
                        "structural_non_decrease_rate",
                    }
                    <= set(row)
                    for row in summary
                )
            ):
                return True
        if name == "label_signal.json":
            from research.label_signal import RANKER_NAMES
            from research.structural_optimum import (
                structural_proof_reference,
            )

            if (
                study.get("schema_version") != "1"
                or study.get("methodology", {}).get("rankers")
                != list(RANKER_NAMES)
                or study.get("methodology", {}).get(
                    "structural_optimum_proof"
                )
                != structural_proof_reference()
                or len(study.get("summary", ()))
                != 2 * 2 * len(RANKER_NAMES)
                or study.get("conclusion", {}).get("status")
                not in {
                    "retain_consensus_label_ranking",
                    "eligible_for_label_ranker_upgrade",
                }
            ):
                return True
        if name == "partition_signal.json":
            from research.partition_signal import PARTITIONER_NAMES
            from research.structural_optimum import (
                structural_proof_reference,
            )

            if (
                study.get("schema_version") != "1"
                or study.get("methodology", {}).get("partitioners")
                != list(PARTITIONER_NAMES)
                or study.get("methodology", {}).get(
                    "structural_optimum_proof"
                )
                != structural_proof_reference()
                or len(study.get("summary", ()))
                != 2 * 2 * len(PARTITIONER_NAMES)
                or study.get("conclusion", {}).get("status")
                not in {
                    "retain_round_robin_partition",
                    "eligible_for_partition_upgrade",
                }
            ):
                return True
        if name == "mechanism_signal.json":
            from research.mechanism_signal import MAIN_CANDIDATES
            from research.profit_portfolio_forward import (
                validate_common_special_candidate,
            )
            from research.structural_optimum import (
                structural_proof_reference,
            )

            candidate = study.get(
                "future_forward_shadow_candidate", {}
            )
            profit_common_candidate = study.get(
                "future_profit_common_special_shadow_candidate", {}
            )
            try:
                validate_common_special_candidate(
                    profit_common_candidate
                )
            except (TypeError, ValueError):
                return True
            if (
                study.get("schema_version") != "1"
                or study.get("methodology", {}).get(
                    "main_candidates"
                )
                != {
                    game: list(candidates)
                    for game, candidates in MAIN_CANDIDATES.items()
                }
                or study.get("methodology", {}).get(
                    "structural_optimum_proof"
                )
                != structural_proof_reference()
                or study.get("conclusion", {}).get("status")
                not in {
                    "retain_current_label_and_special_ranking",
                    "eligible_for_mechanism_upgrade",
                }
                or len(candidate.get("candidate_hash", "")) != 64
                or candidate.get("use")
                != "future_forward_shadow_only"
            ):
                return True
    return False


def _refresh_shadow_research(base: Path, output_dir: Path) -> dict:
    """在正式下一期凍結後，唯讀重算 Agent 與五注機率影子研究。"""
    from research.council_quality import (
        run_quality_study,
        write_results as write_quality_results,
    )
    from research.max_coverage import (
        run_max_coverage_study,
        write_results as write_max_coverage_results,
    )
    from research.label_signal import (
        run_label_signal_study,
        write_results as write_label_signal_results,
    )
    from research.partition_signal import (
        run_partition_signal_study,
        write_results as write_partition_signal_results,
    )
    from research.mechanism_signal import (
        run_mechanism_signal_study,
        write_results as write_mechanism_signal_results,
    )

    quality_result = run_quality_study(
        {
            game: Path(output_dir) / f"{game}.jsonl"
            for game in GAMES
        },
        base=base,
        verify_ledgers=True,
    )
    quality_paths = write_quality_results(
        quality_result,
        Path(base) / "research" / "results",
    )
    coverage_result = run_max_coverage_study(
        {
            game: Path(output_dir) / f"{game}.jsonl"
            for game in GAMES
        },
        base=base,
        verify_ledgers=True,
    )
    coverage_paths = write_max_coverage_results(
        coverage_result,
        Path(base) / "research" / "results",
    )
    label_result = run_label_signal_study(
        {
            game: Path(output_dir) / f"{game}.jsonl"
            for game in GAMES
        },
        base=base,
        verify_ledgers=True,
    )
    label_paths = write_label_signal_results(
        label_result,
        Path(base) / "research" / "results",
    )
    partition_result = run_partition_signal_study(
        {
            game: Path(output_dir) / f"{game}.jsonl"
            for game in GAMES
        },
        base=base,
        verify_ledgers=True,
    )
    partition_paths = write_partition_signal_results(
        partition_result,
        Path(base) / "research" / "results",
    )
    mechanism_result = run_mechanism_signal_study(
        {
            game: Path(output_dir) / f"{game}.jsonl"
            for game in GAMES
        },
        base=base,
        verify_ledgers=True,
    )
    mechanism_paths = write_mechanism_signal_results(
        mechanism_result,
        Path(base) / "research" / "results",
    )
    return {
        "experiment_id": quality_result["experiment_id"],
        "generated_at": quality_result["generated_at"],
        "status": quality_result["conclusion"]["status"],
        "recommendation": quality_result["conclusion"][
            "recommendation"
        ],
        "records_unchanged": (
            quality_result["records_integrity"]["unchanged"]
            and coverage_result["records_integrity"]["unchanged"]
            and label_result["records_integrity"]["unchanged"]
            and partition_result["records_integrity"]["unchanged"]
            and mechanism_result["records_integrity"]["unchanged"]
        ),
        "result_file": str(quality_paths["json"].relative_to(base)),
        "coverage": {
            "experiment_id": coverage_result["experiment_id"],
            "generated_at": coverage_result["generated_at"],
            "status": coverage_result["conclusion"]["status"],
            "result_file": str(
                coverage_paths["json"].relative_to(base)
            ),
        },
        "label_signal": {
            "experiment_id": label_result["experiment_id"],
            "generated_at": label_result["generated_at"],
            "status": label_result["conclusion"]["status"],
            "result_file": str(
                label_paths["json"].relative_to(base)
            ),
        },
        "partition_signal": {
            "experiment_id": partition_result["experiment_id"],
            "generated_at": partition_result["generated_at"],
            "status": partition_result["conclusion"]["status"],
            "result_file": str(
                partition_paths["json"].relative_to(base)
            ),
        },
        "mechanism_signal": {
            "experiment_id": mechanism_result["experiment_id"],
            "generated_at": mechanism_result["generated_at"],
            "status": mechanism_result["conclusion"]["status"],
            "result_file": str(
                mechanism_paths["json"].relative_to(base)
            ),
            "forward_candidate_hash": mechanism_result[
                "future_forward_shadow_candidate"
            ]["candidate_hash"],
            "profit_common_special_forward_candidate_hash": (
                mechanism_result[
                    "future_profit_common_special_shadow_candidate"
                ]["candidate_hash"]
            ),
        },
    }


def _refresh_probability_stacking(
    base: Path,
    output_dir: Path,
) -> dict:
    """在下一期登記前更新 proper-score 權重；不寫正式 records。"""
    from research.probability_stacking import (
        run_probability_stacking,
        write_results,
    )
    from research.decision_strength import (
        run_decision_strength_audit,
        write_results as write_decision_strength_results,
    )

    result = run_probability_stacking(
        {
            game: Path(output_dir) / f"{game}.jsonl"
            for game in GAMES
        },
        base=base,
        verify_ledgers=True,
    )
    path = write_results(
        result,
        Path(base) / "research" / "results",
    )
    strength = run_decision_strength_audit(base)
    strength_path = write_decision_strength_results(
        strength,
        Path(base) / "research" / "results",
    )
    return {
        "experiment_id": result["experiment_id"],
        "generated_at": result["generated_at"],
        "status": result["conclusion"]["status"],
        "records_unchanged": result["records_integrity"][
            "unchanged"
        ],
        "candidate_hash": result[
            "future_forward_shadow_candidate"
        ]["candidate_hash"],
        "fitted_through": result[
            "future_forward_shadow_candidate"
        ]["fitted_through"],
        "result_file": str(path.relative_to(base)),
        "decision_strength": {
            "experiment_id": strength["experiment_id"],
            "audit_hash": strength["audit_hash"],
            "status": strength["decision"]["status"],
            "top_k_amplification_present": strength[
                "diagnosis"
            ]["top_k_amplification_present"],
            "result_file": str(strength_path.relative_to(base)),
        },
    }


def _refresh_switching_bayes(
    base: Path,
    output_dir: Path,
) -> dict:
    from research.switching_bayes import (
        run_switching_bayes_study,
        write_results,
    )

    base = Path(base)
    result = run_switching_bayes_study(
        {
            SUPER: Path(output_dir) / f"{SUPER}.jsonl",
            LOTTO649: Path(output_dir) / f"{LOTTO649}.jsonl",
        },
        base=base,
    )
    path = write_results(
        result,
        base / "research" / "results",
    )
    candidate = result["future_forward_shadow_candidate"]
    return {
        "experiment_id": result["experiment_id"],
        "status": result["decision"]["status"],
        "candidate_hash": candidate["candidate_hash"],
        "fitted_through": candidate["fitted_through"],
        "label_signal_proven": result["decision"][
            "label_signal_proven"
        ],
        "result_file": str(path.relative_to(base)),
    }


def _reconcile_switching_bayes(
    base: Path,
    store,
    manifest: dict,
) -> dict:
    from research.switching_bayes_forward import (
        reconcile_registry,
    )

    result = reconcile_registry(base, store, manifest)
    return {
        "settlements_created": result["settlements_created"],
        "registrations": result["registrations"],
        "verification": result["status"]["verification"],
        "pending": result["status"]["pending"],
        "status_path": str(
            Path(result["status_path"]).relative_to(base)
        ),
    }


def _refresh_null_safe_probability(
    base: Path,
    output_dir: Path,
) -> dict:
    """從凍結基線重建 gate；只讀取帳本中已登記的 v7 結算。"""
    from research.null_safe_probability import (
        build_forward_state_artifact,
        validate_forward_candidate,
        validate_forward_state_artifact,
        write_forward_state,
    )
    from research.probability_stacking import (
        validate_forward_candidate as validate_stacking_candidate,
    )
    results_dir = Path(base) / "research" / "results"
    forward_path = (
        results_dir / "null_safe_probability_forward.json"
    )
    if forward_path.exists():
        validate_forward_state_artifact(
            json.loads(forward_path.read_text(encoding="utf-8"))
        )
    formal = json.loads(
        (
            results_dir / "null_safe_probability.json"
        ).read_text(encoding="utf-8")
    )
    prior_candidate = validate_forward_candidate(
        formal["future_forward_shadow_candidate"]
    )
    stacking_study = json.loads(
        (
            results_dir / "probability_stacking.json"
        ).read_text(encoding="utf-8")
    )
    stacking_candidate = validate_stacking_candidate(
        stacking_study["future_forward_shadow_candidate"]
    )
    ledger = forward_lab.forward_ledger(base)
    forward_lab.verify_registry(ledger)
    score_settlements = []
    for event in ledger.events_of("forward_settlement"):
        content = event["content"]
        null_safe = content.get(
            "null_safe_probability_shadow"
        )
        if null_safe is None:
            continue
        score_settlements.append(
            {
                "game": content["game"],
                "target": content["target"],
                "registration_hash": content[
                    "registration_hash"
                ],
                "proper_score": null_safe["proper_score"],
            }
        )
    artifact = build_forward_state_artifact(
        prior_candidate,
        stacking_candidate,
        score_settlements,
    )
    path = write_forward_state(artifact, results_dir)
    candidate = artifact["future_forward_shadow_candidate"]
    return {
        "experiment_id": artifact["experiment_id"],
        "generated_at": artifact["generated_at"],
        "status": "candidate_ready_future_shadow",
        "historical_backfill_allowed": False,
        "candidate_hash": candidate["candidate_hash"],
        "fitted_through": candidate["fitted_through"],
        "applied_transitions": len(
            artifact["applied_transitions"]
        ),
        "registered_score_capsules": len(
            artifact["registered_score_capsules"]
        ),
        "current_gate_active": {
            SUPER: {
                "main": candidate["models"][SUPER][
                    "main_gate_active"
                ],
                "special": candidate["models"][SUPER][
                    "special_gate_active"
                ],
            },
            LOTTO649: {
                "main": candidate["models"][LOTTO649][
                    "main_gate_active"
                ],
                "special": None,
            },
        },
        "result_file": str(path.relative_to(base)),
    }


def compare_draw_counts(
    previous: dict[str, int], current: dict[str, int]
) -> dict[str, int]:
    """回傳各遊戲新增期數；資料倒退時 fail closed。"""
    changes = {}
    for game in GAMES:
        before = int(previous.get(game, 0))
        after = int(current.get(game, 0))
        if after < before:
            raise ValueError(
                f"{GAME_NAMES[game]}官方快取期數倒退：{after} < {before}"
            )
        changes[game] = after - before
    return changes


def sync_latest(
    base: Path,
    *,
    progress: Progress | None = None,
    fetcher=ingest,
    runner=_run_with_qwen,
    pre_settler=forward_lab.settle_forward_registry,
    feedback_loader=forward_lab.feedback_for_target,
    forward_syncer=forward_lab.reconcile_forward_registry,
    shadow_researcher=_refresh_shadow_research,
    probability_stacker=_refresh_probability_stacking,
    null_safe_probability_stacker=_refresh_null_safe_probability,
    switching_bayes_researcher=_refresh_switching_bayes,
    switching_bayes_forward_syncer=_reconcile_switching_bayes,
) -> dict:
    """檢查官方新資料、必要時重建閉環，並結算/凍結前向 A/B。"""
    base = Path(base)
    output_dir = base / "simulation" / "results"
    previous_manifest = _read_manifest(output_dir)
    previous_counts = {
        game: int(
            (previous_manifest or {}).get("games", {}).get(game, {}).get(
                "draws_replayed", 0
            )
        )
        for game in GAMES
    }

    def emit(phase: str, message: str, details: dict | None = None) -> None:
        if progress is not None:
            progress(phase, message, details)

    env = Env(base)
    emit("checking", "正在比對台彩官方當月開獎資料", None)
    fetched_months = {}
    for game in GAMES:
        _, fetched = fetcher(game, env.data_dir)
        fetched_months[game] = fetched

    fresh_env = Env(base)
    current_counts = {
        game: len(fresh_env.store.draws(game)) for game in GAMES
    }
    changes = compare_draw_counts(previous_counts, current_counts)
    new_total = sum(changes.values())
    needs_rebuild = previous_manifest is None or new_total > 0
    pre_settlements_created = 0

    if needs_rebuild:
        emit(
            "reviewing",
            f"偵測到 {new_total} 期新開獎，正在執行揭曉後檢討",
            {"new_draws": changes},
        )
        settled = pre_settler(base, fresh_env.store)
        pre_settlements_created = int(
            settled["settlements_created"]
        )

        def feedback_provider(game: str, target: dict) -> dict:
            return feedback_loader(base, game, target)

        emit(
            "optimizing",
            "正在重建完整回放、更新 Agent 評分與下一期候選",
            {
                "settlements_created": pre_settlements_created,
                "feedback_experiment": FEEDBACK_EXPERIMENT_ID,
            },
        )
        manifest = runner(
            fresh_env.store,
            output_dir,
            feedback_provider,
        )
    else:
        manifest = previous_manifest

    ledger_files_ready = all(
        (output_dir / f"{game}.jsonl").exists() for game in GAMES
    )
    probability_stacking = None
    if (
        ledger_files_ready
        and _probability_stacking_stale(base, manifest)
    ):
        emit(
            "calibrating",
            "正在用最新揭曉更新 proper-score 權重並凍結唯前向候選",
            {
                "formal_decision_frozen": False,
                "writes_formal_records": False,
            },
        )
        probability_stacking = probability_stacker(
            base,
            output_dir,
        )
    null_safe_probability = None
    if (
        ledger_files_ready
        and _null_safe_probability_stale(base, manifest)
    ):
        emit(
            "gating",
            "正在更新公平零模型證據閘門並凍結 v7 future-only 候選",
            {
                "activation_e_threshold": 60,
                "formal_decision_frozen": False,
                "writes_formal_records": False,
            },
        )
        null_safe_probability = null_safe_probability_stacker(
            base,
            output_dir,
        )
    switching_bayes = None
    switching_bayes_path = (
        base
        / "research"
        / "results"
        / "switching_bayes.json"
    )
    if (
        ledger_files_ready
        and switching_bayes_path.exists()
        and _switching_bayes_stale(base, manifest)
    ):
        emit(
            "switching",
            "正在更新未知生成器 switching-Bayes 權重與下一期候選",
            {
                "fixed_share": "1/208",
                "historical_backfill_allowed": False,
                "writes_formal_records": False,
            },
        )
        switching_bayes = switching_bayes_researcher(
            base,
            output_dir,
        )
    switching_bayes_forward = None
    if ledger_files_ready and switching_bayes_path.exists():
        switching_bayes_forward = (
            switching_bayes_forward_syncer(
                base,
                fresh_env.store,
                manifest,
            )
        )

    emit(
        "preregistering",
        "正在結算前向實驗並凍結下一期控制臂、coverage 與獲利 shadows",
        None,
    )
    forward_experiment = forward_syncer(
        base,
        fresh_env.store,
        manifest,
    )
    shadow_research = None
    if (
        ledger_files_ready
        and _shadow_research_stale(base, manifest)
    ):
        emit(
            "researching",
            "下一期已凍結，正在重算 Agent 與五注機率影子研究",
            {
                "formal_decision_frozen": True,
                "writes_formal_records": False,
            },
        )
        shadow_research = shadow_researcher(base, output_dir)

    games = {
        game: {
            "game_name": GAME_NAMES[game],
            "before": previous_counts[game],
            "after": current_counts[game],
            "new_draws": changes[game],
            "latest_target": manifest["games"][game]["last_target"],
            "next_target": manifest["games"][game]["next_decision"]["target"],
        }
        for game in GAMES
    }
    result = {
        "checked_at": datetime.now(TAIPEI).isoformat(timespec="seconds"),
        "regenerated": needs_rebuild,
        "new_draws_total": new_total,
        "fetched_months": fetched_months,
        "games": games,
        "manifest_hash": manifest["manifest_hash"],
        "feedback_provenance": {
            game: manifest["games"][game]["next_decision"][
                "adjudication"
            ]["judge"].get("feedback_provenance")
            for game in GAMES
        },
        "forward_experiment": {
            "settlements_created": (
                pre_settlements_created
                + forward_experiment["settlements_created"]
            ),
            "settlements_before_decision": pre_settlements_created,
            "registrations": forward_experiment["registrations"],
            "evidence_status": forward_experiment["summary"][
                "evidence_status"
            ],
            "recommendation": forward_experiment["summary"][
                "recommendation"
            ],
            "verification": forward_experiment["summary"]["verification"],
            "feedback_memory": forward_experiment["summary"].get(
                "feedback_memory", {}
            ),
            "deployment_gate": forward_experiment["summary"].get(
                "operations", {}
            ).get("deployment_gate"),
        },
        "shadow_research": shadow_research,
        "probability_stacking": probability_stacking,
        "null_safe_probability": null_safe_probability,
        "switching_bayes": switching_bayes,
        "switching_bayes_forward": switching_bayes_forward,
    }
    emit(
        "ready",
        (
            "新開獎已完成檢討、前向 A/B 結算與下一期凍結"
            if needs_rebuild
            else "官方資料無新增，下一期前向 A/B 已確認凍結"
        ),
        result,
    )
    return result
