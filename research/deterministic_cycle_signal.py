"""Audit low-complexity deterministic draw-cycle hypotheses.

Each candidate assumes that chronological draw index modulo a fixed period
defines a separate label-frequency regime.  Forecasts use only prior draws in
the target phase, score the complete unordered six-number subset, and update
the phase state only after the reveal.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import statistics

from engine.agent_loop import canonical_hash, verify_replay
from engine.games import GAME_NAMES, LOTTO649, PICK_N, POOL, SUPER
from research.agent_ablation import block_bootstrap_ci
from research.gates import tree_sha256
from research.persistent_bias_signal import (
    _update_label_counts,
    initial_label_counts,
    persistent_subset_probability,
)


EXPERIMENT_ID = "deterministic-cycle-subset-audit-v1"
GAMES = (SUPER, LOTTO649)
DEFAULT_MODULI = (2, 3, 4, 5, 7, 8, 13, 26, 52)
DEFAULT_WARMUP_DRAWS = 60
DEFAULT_DEVELOPMENT_FRACTION = 0.7
DEFAULT_BOOTSTRAP_SAMPLES = 2_000
DEFAULT_BOOTSTRAP_BLOCK = 13
ALPHA = 1.0


@dataclass(frozen=True)
class CycleConfig:
    moduli: tuple[int, ...] = DEFAULT_MODULI
    warmup_draws: int = DEFAULT_WARMUP_DRAWS
    development_fraction: float = DEFAULT_DEVELOPMENT_FRACTION
    bootstrap_samples: int = DEFAULT_BOOTSTRAP_SAMPLES
    bootstrap_block: int = DEFAULT_BOOTSTRAP_BLOCK

    def validate(self) -> None:
        if (
            not self.moduli
            or tuple(sorted(set(self.moduli))) != self.moduli
            or any(
                not isinstance(modulus, int) or modulus < 2
                for modulus in self.moduli
            )
        ):
            raise ValueError(
                "cycle moduli must be unique increasing integers >= 2"
            )
        if self.warmup_draws < 1:
            raise ValueError("cycle warmup must be positive")
        if not 0.5 <= self.development_fraction < 1.0:
            raise ValueError(
                "cycle development_fraction must be in [0.5, 1)"
            )
        if self.bootstrap_samples < 1 or self.bootstrap_block < 1:
            raise ValueError("cycle bootstrap settings must be positive")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _stable(value):
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("cycle result contains a non-finite number")
        return float(format(value, ".15g"))
    if isinstance(value, list):
        return [_stable(item) for item in value]
    if isinstance(value, tuple):
        return [_stable(item) for item in value]
    if isinstance(value, dict):
        return {key: _stable(item) for key, item in value.items()}
    return value


def initial_phase_counts(pool: int, modulus: int) -> list[list[int]]:
    if not isinstance(modulus, int) or modulus < 2:
        raise ValueError("cycle modulus must be an integer >= 2")
    return [
        initial_label_counts(pool)
        for _ in range(modulus)
    ]


def phase_subset_probability(
    target_numbers: tuple[int, ...] | list[int],
    counts_by_phase: list[list[int]],
    *,
    pool: int,
    phase: int,
    alpha: float = ALPHA,
) -> float:
    if (
        not isinstance(counts_by_phase, list)
        or len(counts_by_phase) < 2
        or not isinstance(phase, int)
        or not 0 <= phase < len(counts_by_phase)
    ):
        raise ValueError("cycle phase state is invalid")
    return persistent_subset_probability(
        target_numbers,
        counts_by_phase[phase],
        pool=pool,
        alpha=alpha,
    )


def _validate_rows(game: str, rows: list[dict]) -> None:
    if game not in GAMES or not rows:
        raise ValueError("cycle rows must contain one supported game")
    previous_date = None
    for sequence, row in enumerate(rows, 1):
        if (
            not isinstance(row, dict)
            or row.get("sequence", sequence) != sequence
            or not isinstance(row.get("date"), str)
            or (
                previous_date is not None
                and row["date"] <= previous_date
            )
        ):
            raise ValueError(
                "cycle rows must be chronological and contiguous"
            )
        numbers = row.get("numbers")
        if (
            not isinstance(numbers, (list, tuple))
            or len(numbers) != PICK_N
            or len(set(numbers)) != PICK_N
            or any(
                not isinstance(number, int)
                or not 1 <= number <= POOL[game]
                for number in numbers
            )
        ):
            raise ValueError("cycle row contains invalid main numbers")
        previous_date = row["date"]


def walk_forward_cycle(
    game: str,
    rows: list[dict],
    *,
    modulus: int,
) -> dict:
    """Return prequential proper-score regret for one fixed cycle."""
    _validate_rows(game, rows)
    pool = POOL[game]
    counts_by_phase = initial_phase_counts(pool, modulus)
    uniform_probability = 1.0 / math.comb(pool, PICK_N)
    regrets = []
    phase_draws = [0] * modulus

    for index, row in enumerate(rows):
        phase = index % modulus
        target = tuple(row["numbers"])
        probability = phase_subset_probability(
            target,
            counts_by_phase,
            pool=pool,
            phase=phase,
        )
        regret = -math.log(probability) + math.log(
            uniform_probability
        )
        if not math.isfinite(regret):
            raise RuntimeError("cycle proper-score regret is non-finite")
        regrets.append(regret)
        _update_label_counts(
            counts_by_phase[phase],
            target,
            pool=pool,
        )
        phase_draws[phase] += 1

    return {
        "modulus": modulus,
        "regrets": regrets,
        "phase_draws": phase_draws,
        "final_state_hash": canonical_hash(counts_by_phase),
    }


def _split_profile(total: int, config: CycleConfig) -> dict:
    eligible = total - config.warmup_draws
    if eligible < 20:
        raise ValueError("cycle study has insufficient post-warmup draws")
    development = math.floor(
        eligible * config.development_fraction
    )
    return {
        "total_draws": total,
        "warmup_draws": config.warmup_draws,
        "eligible_draws": eligible,
        "development_draws": development,
        "holdout_draws": eligible - development,
        "development_end_index": config.warmup_draws + development,
    }


def evaluate_cycle_candidates(
    game: str,
    rows: list[dict],
    *,
    config: CycleConfig | None = None,
) -> dict:
    """Select a modulus using development only, then audit holdout once."""
    config = config or CycleConfig()
    config.validate()
    _validate_rows(game, rows)
    split = _split_profile(len(rows), config)
    start = config.warmup_draws
    end = split["development_end_index"]
    candidates = []
    traces = {}

    for modulus in config.moduli:
        trace = walk_forward_cycle(
            game,
            rows,
            modulus=modulus,
        )
        traces[modulus] = trace
        development = trace["regrets"][start:end]
        holdout = trace["regrets"][end:]
        candidates.append(
            {
                "modulus": modulus,
                "development_mean_regret_nats": statistics.fmean(
                    development
                ),
                "holdout_mean_regret_nats": statistics.fmean(
                    holdout
                ),
                "final_state_hash": trace["final_state_hash"],
                "phase_draws": trace["phase_draws"],
            }
        )

    selected = min(
        candidates,
        key=lambda row: (
            row["development_mean_regret_nats"],
            row["modulus"],
        ),
    )
    selected_trace = traces[selected["modulus"]]["regrets"]
    development = selected_trace[start:end]
    holdout = selected_trace[end:]
    development_ci = block_bootstrap_ci(
        development,
        samples=config.bootstrap_samples,
        block=config.bootstrap_block,
        seed=(
            f"{EXPERIMENT_ID}|{game}|m={selected['modulus']}|"
            "development"
        ),
    )
    holdout_ci = block_bootstrap_ci(
        holdout,
        samples=config.bootstrap_samples,
        block=config.bootstrap_block,
        seed=(
            f"{EXPERIMENT_ID}|{game}|m={selected['modulus']}|"
            "holdout"
        ),
    )
    development_gate = (
        selected["development_mean_regret_nats"] < 0
        and development_ci[1] < 0
    )
    holdout_gate = (
        selected["holdout_mean_regret_nats"] < 0
        and holdout_ci[1] < 0
    )
    return {
        "game": game,
        "game_name": GAME_NAMES[game],
        "split": split,
        "candidates": candidates,
        "selected_modulus_from_development": selected["modulus"],
        "selected_development_mean_regret_nats": selected[
            "development_mean_regret_nats"
        ],
        "selected_development_bootstrap_95": list(development_ci),
        "development_gate_passed": development_gate,
        "selected_holdout_mean_regret_nats": selected[
            "holdout_mean_regret_nats"
        ],
        "selected_holdout_bootstrap_95": list(holdout_ci),
        "holdout_gate_passed": holdout_gate,
        "historical_promotion_eligible": (
            development_gate and holdout_gate
        ),
        "selected_score_trace_hash": canonical_hash(
            [_stable(value) for value in selected_trace]
        ),
    }


def _load_ledger_rows(path: Path, game: str) -> list[dict]:
    rows = []
    with Path(path).open(encoding="utf-8") as handle:
        for sequence, line in enumerate(handle, 1):
            event = json.loads(line)
            reveal = event.get("reveal", {})
            if (
                event.get("sequence") != sequence
                or event.get("decision", {}).get("game") != game
            ):
                raise ValueError("cycle ledger identity is invalid")
            rows.append(
                {
                    "sequence": sequence,
                    "date": reveal.get("date"),
                    "period": reveal.get("period"),
                    "numbers": reveal.get("numbers"),
                }
            )
    _validate_rows(game, rows)
    return rows


def run_deterministic_cycle_study(
    ledger_paths: dict[str, Path],
    *,
    base: Path,
    config: CycleConfig | None = None,
    verify_ledgers: bool = True,
) -> dict:
    config = config or CycleConfig()
    config.validate()
    base = Path(base)
    records_before = tree_sha256(base / "records")
    games = {}
    ledger_verification = {}
    source_last_dates = {}

    for game in GAMES:
        path = Path(ledger_paths[game])
        verification = (
            verify_replay(path)
            if verify_ledgers
            else {
                "lines": sum(
                    1 for _ in path.open(encoding="utf-8")
                ),
                "last_event_hash": None,
                "ledger_sha256": _file_sha256(path),
            }
        )
        rows = _load_ledger_rows(path, game)
        if verification["lines"] != len(rows):
            raise RuntimeError("cycle ledger line count mismatch")
        ledger_verification[game] = verification
        source_last_dates[game] = rows[-1]["date"]
        games[game] = evaluate_cycle_candidates(
            game,
            rows,
            config=config,
        )

    records_after = tree_sha256(base / "records")
    if records_before != records_after:
        raise RuntimeError("cycle study must not modify formal records")
    promoted = all(
        games[game]["historical_promotion_eligible"]
        for game in GAMES
    )
    payload = {
        "schema_version": "1",
        "experiment_id": EXPERIMENT_ID,
        "generated_at": (
            max(source_last_dates.values())
            + "T23:59:59+08:00"
        ),
        "question": (
            "Can a fixed chronological draw-index cycle predict the "
            "complete next six-number subset better than label symmetry?"
        ),
        "methodology": {
            "hypothesis": (
                "chronological_index_mod_m_defines_separate_"
                "label_frequency_regimes"
            ),
            "moduli": list(config.moduli),
            "alpha": ALPHA,
            "warmup_draws": config.warmup_draws,
            "development_fraction": config.development_fraction,
            "bootstrap_samples": config.bootstrap_samples,
            "bootstrap_block_draws": config.bootstrap_block,
            "score": (
                "negative_log_probability_of_complete_unordered_"
                "six_number_subset"
            ),
            "control": "exact_discrete_uniform_label_symmetry",
            "selection": (
                "minimum development mean regret; tie by smaller "
                "modulus; holdout never selects"
            ),
            "lookahead_control": (
                "phase is known before draw; forecast precedes "
                "same-phase state update"
            ),
        },
        "data_quality": {
            "status": "pass",
            "ledger_verification": ledger_verification,
            "source_last_dates": source_last_dates,
        },
        "games": games,
        "conclusion": {
            "status": (
                "eligible_for_future_cycle_shadow"
                if promoted
                else "reject_deterministic_cycle_challenger"
            ),
            "both_games_historical_promotion_eligible": promoted,
            "watcher_integration_allowed": promoted,
            "decision_rule": (
                "both games must pass negative-regret development "
                "and sealed holdout bootstrap gates"
            ),
            "historical_reuse": (
                "result closes this fixed modulus family; new cycle "
                "search requires a new preregistered experiment"
            ),
        },
        "records_integrity": {
            "before_sha256": records_before,
            "after_sha256": records_after,
            "unchanged": records_before == records_after,
        },
    }
    payload = _stable(payload)
    payload["audit_hash"] = canonical_hash(payload)
    return payload


def validate_result(result: dict) -> dict:
    if not isinstance(result, dict):
        raise ValueError("cycle result must be an object")
    payload = {
        key: value
        for key, value in result.items()
        if key != "audit_hash"
    }
    if (
        result.get("schema_version") != "1"
        or result.get("experiment_id") != EXPERIMENT_ID
        or result.get("audit_hash") != canonical_hash(payload)
        or set(result.get("games", {})) != set(GAMES)
        or not _is_sha256(result.get("audit_hash"))
    ):
        raise ValueError("cycle result schema or audit hash is invalid")
    promoted = all(
        result["games"][game].get(
            "historical_promotion_eligible"
        )
        is True
        for game in GAMES
    )
    expected_status = (
        "eligible_for_future_cycle_shadow"
        if promoted
        else "reject_deterministic_cycle_challenger"
    )
    if (
        result.get("conclusion", {}).get("status")
        != expected_status
        or result.get("conclusion", {}).get(
            "both_games_historical_promotion_eligible"
        )
        is not promoted
        or result.get("records_integrity", {}).get("unchanged")
        is not True
    ):
        raise ValueError("cycle conclusion is inconsistent")
    for game in GAMES:
        row = result["games"][game]
        candidates = row.get("candidates", [])
        if (
            [candidate.get("modulus") for candidate in candidates]
            != list(DEFAULT_MODULI)
            or row.get("selected_modulus_from_development")
            not in DEFAULT_MODULI
            or not _is_sha256(
                row.get("selected_score_trace_hash")
            )
        ):
            raise ValueError("cycle game diagnostics are invalid")
    return result


def write_result(result: dict, path: Path) -> Path:
    validate_result(result)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path
