"""未知生成機制的五個競爭假說。

這個模組只服務 agent-loop v3。舊版 analysts.py 仍保留給已封存的正式週票帳本，
避免改名或換演算法後破壞歷史重現。

所有假說共用相同介面與先驗地位：

* H0 independent_null：獨立均勻只是待比較的基準，不保留席位。
* H1 temporal_dependency：檢驗近期頻率與一期轉移依賴。
* H2 regime_shift：檢驗短窗相對長窗的分布漂移。
* H3 structural_bias：檢驗長期號碼與組合結構偏差。
* H4 overfit_guard：只保留跨多個時間窗一致、且向均勻分布收縮的訊號。

輸出的是開獎前機率快照與可重現候選；沒有任何假說被宣告為真。
"""
from __future__ import annotations

import hashlib
import json
import math
import random
from collections import Counter

from .games import PICK_N, POOL, SPECIAL_POOL, SUPER, Draw


HYPOTHESES = {
    "independent_null": {
        "code": "H0",
        "name": "獨立隨機",
        "doctrine": "均勻獨立 · 基準假說",
        "thesis": "歷史不改變下一期的號碼分布；它只是競爭基準，不享有保留席位。",
    },
    "temporal_dependency": {
        "code": "H1",
        "name": "時間依賴",
        "doctrine": "近期頻率 · 條件轉移",
        "thesis": "若生成機制帶有短期記憶，近期頻率與相鄰期轉移應留下可重複訊號。",
    },
    "regime_shift": {
        "code": "H2",
        "name": "狀態轉換",
        "doctrine": "短長窗差異 · 變點追蹤",
        "thesis": "若機器、球組或流程狀態改變，短窗分布應相對長窗基準產生漂移。",
    },
    "structural_bias": {
        "code": "H3",
        "name": "結構偏差",
        "doctrine": "長期分布 · 組合幾何",
        "thesis": "若生成機制存在持續偏差，號碼邊際與組合結構應長期偏離均勻基準。",
    },
    "overfit_guard": {
        "code": "H4",
        "name": "反過度擬合",
        "doctrine": "跨窗一致 · 收縮驗證",
        "thesis": "只有跨時間窗方向一致且經收縮後仍存在的訊號，才值得帶入下一期。",
    },
}

HYPOTHESIS_IDS = tuple(sorted(HYPOTHESES))
NAMES = {key: value["name"] for key, value in HYPOTHESES.items()}
STRUCTURAL_SEARCH_CANDIDATES = 48


def _weighted_sample(
    rng: random.Random,
    weights: dict[int, float],
    k: int,
) -> list[int]:
    pool = {number: max(float(weight), 1e-12) for number, weight in weights.items()}
    chosen = []
    for _ in range(k):
        keys = sorted(pool)
        total = sum(pool.values())
        cursor = rng.random() * total
        accumulated = 0.0
        selected = keys[-1]
        for number in keys:
            accumulated += pool[number]
            if cursor < accumulated:
                selected = number
                break
        chosen.append(selected)
        del pool[selected]
    return sorted(chosen)


def _mean_one(values: dict[int, float]) -> dict[int, float]:
    if not values:
        return {}
    mean = sum(values.values()) / len(values)
    if mean <= 1e-15:
        return {key: 1.0 for key in values}
    return {key: max(1e-6, value / mean) for key, value in values.items()}


def _blend(
    pool_size: int,
    components: list[tuple[float, dict[int, float]]],
) -> dict[int, float]:
    scaled = [(weight, _mean_one(values)) for weight, values in components]
    return {
        number: max(
            1e-6,
            sum(weight * values[number] for weight, values in scaled),
        )
        for number in range(1, pool_size + 1)
    }


def _inclusion_probabilities(
    weights: dict[int, float],
    selections: int,
) -> dict[int, float]:
    """把相對權重轉成總和為 selections、單點不超過 1 的邊際近似。"""
    remaining = set(weights)
    probabilities = {number: 0.0 for number in weights}
    mass = float(selections)
    while remaining and mass > 1e-12:
        total = sum(max(weights[number], 1e-12) for number in remaining)
        saturated = {
            number
            for number in remaining
            if mass * max(weights[number], 1e-12) / total >= 1.0
        }
        if not saturated:
            for number in remaining:
                probabilities[number] = (
                    mass * max(weights[number], 1e-12) / total
                )
            break
        for number in saturated:
            probabilities[number] = 1.0
            mass -= 1.0
        remaining -= saturated
    return probabilities


def _frequency_weights(
    sequences: list[tuple[int, ...]],
    pool_size: int,
    *,
    window: int,
    decay: float = 1.0,
) -> dict[int, float]:
    weights = {number: 1.0 for number in range(1, pool_size + 1)}
    for age, values in enumerate(reversed(sequences[-window:])):
        contribution = decay**age
        for number in values:
            weights[number] += contribution
    return weights


def _temporal_weights(
    sequences: list[tuple[int, ...]],
    pool_size: int,
) -> tuple[dict[int, float], dict]:
    recent = _frequency_weights(
        sequences,
        pool_size,
        window=60,
        decay=0.965,
    )
    transitions = {number: 0.25 for number in range(1, pool_size + 1)}
    if sequences:
        anchor = set(sequences[-1])
        pairs = list(zip(sequences[-121:-1], sequences[-120:]))
        for age, (previous, following) in enumerate(reversed(pairs)):
            similarity = len(anchor & set(previous)) / max(1, len(anchor))
            if similarity <= 0:
                continue
            contribution = similarity * (0.985**age)
            for number in following:
                transitions[number] += contribution
    weights = _blend(
        pool_size,
        [(0.42, {number: 1.0 for number in recent}), (0.36, recent), (0.22, transitions)],
    )
    transition_scaled = _mean_one(transitions)
    return weights, {
        "recent_window": min(60, len(sequences)),
        "transition_pairs": max(0, min(120, len(sequences) - 1)),
        "transition_peak": round(max(transition_scaled.values()), 6),
    }


def _regime_weights(
    sequences: list[tuple[int, ...]],
    pool_size: int,
) -> tuple[dict[int, float], dict]:
    short_window = min(18, len(sequences))
    long_window = min(120, len(sequences))
    short = Counter(
        number
        for values in sequences[-short_window:]
        for number in values
    )
    long = Counter(
        number
        for values in sequences[-long_window:]
        for number in values
    )
    values_per_draw = len(sequences[-1]) if sequences else 1
    short_denominator = max(1, short_window * values_per_draw)
    long_denominator = max(1, long_window * values_per_draw)
    ratios = {}
    shifts = {}
    prior = 1 / pool_size
    for number in range(1, pool_size + 1):
        short_rate = (short[number] + 2 * prior) / (short_denominator + 2)
        long_rate = (long[number] + 6 * prior) / (long_denominator + 6)
        ratio = short_rate / max(long_rate, 1e-12)
        ratios[number] = min(3.0, max(0.25, ratio))
        shifts[number] = abs(short_rate - long_rate) / max(prior, 1e-12)
    weights = _blend(
        pool_size,
        [(0.55, {number: 1.0 for number in ratios}), (0.45, ratios)],
    )
    return weights, {
        "short_window": short_window,
        "long_window": long_window,
        "shift_index": round(sum(shifts.values()) / pool_size, 6),
        "max_rate_ratio": round(max(ratios.values()), 6),
    }


def _structural_weights(
    sequences: list[tuple[int, ...]],
    pool_size: int,
) -> tuple[dict[int, float], dict]:
    persistent = _frequency_weights(
        sequences,
        pool_size,
        window=max(1, len(sequences)),
    )
    weights = _blend(
        pool_size,
        [(0.38, {number: 1.0 for number in persistent}), (0.62, persistent)],
    )
    recent = sequences[-240:]
    sums = [sum(values) for values in recent]
    odd_counts = [sum(number % 2 for number in values) for values in recent]
    ranges = [max(values) - min(values) for values in recent] if recent else []
    consecutive = [
        sum(1 for left, right in zip(values, values[1:]) if right - left == 1)
        for values in recent
    ]
    return weights, {
        "history_window": len(recent),
        "target_sum": round(sum(sums) / len(sums), 4) if sums else None,
        "target_odd": round(sum(odd_counts) / len(odd_counts), 4)
        if odd_counts
        else None,
        "target_range": round(sum(ranges) / len(ranges), 4)
        if ranges
        else None,
        "target_consecutive": round(sum(consecutive) / len(consecutive), 4)
        if consecutive
        else None,
    }


def _guard_weights(
    sequences: list[tuple[int, ...]],
    pool_size: int,
) -> tuple[dict[int, float], dict]:
    windows = (18, 36, 72)
    expected = 1 / pool_size
    relative_by_window = []
    values_per_draw = len(sequences[-1]) if sequences else 1
    for window in windows:
        selected = sequences[-window:]
        counts = Counter(number for values in selected for number in values)
        denominator = max(1, len(selected) * values_per_draw)
        relative_by_window.append(
            {
                number: (counts[number] + 4 * expected)
                / (denominator + 4)
                / expected
                for number in range(1, pool_size + 1)
            }
        )
    stability = {}
    weights = {}
    for number in range(1, pool_size + 1):
        values = [window[number] for window in relative_by_window]
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        standard_deviation = math.sqrt(variance)
        stable_signal = max(0.0, mean - 1.0) / (1.0 + 3.0 * standard_deviation)
        stability[number] = stable_signal
        weights[number] = 1.0 + 0.70 * stable_signal
    return weights, {
        "windows": [min(window, len(sequences)) for window in windows],
        "mean_stable_signal": round(sum(stability.values()) / pool_size, 6),
        "max_stable_signal": round(max(stability.values()), 6),
        "shrinkage_to_uniform": 0.70,
    }


def _sequence_models(
    sequences: list[tuple[int, ...]],
    pool_size: int,
) -> dict[str, tuple[dict[int, float], dict]]:
    uniform = {number: 1.0 for number in range(1, pool_size + 1)}
    return {
        "independent_null": (
            uniform,
            {"history_used": 0, "distribution": "uniform-independent"},
        ),
        "temporal_dependency": _temporal_weights(sequences, pool_size),
        "regime_shift": _regime_weights(sequences, pool_size),
        "structural_bias": _structural_weights(sequences, pool_size),
        "overfit_guard": _guard_weights(sequences, pool_size),
    }


def _evidence_strength(
    hypothesis: str,
    history_count: int,
    diagnostics: dict,
) -> float:
    if hypothesis == "independent_null":
        return 1.0
    maturity = min(1.0, history_count / 120)
    if hypothesis == "regime_shift":
        signal = min(1.0, float(diagnostics.get("shift_index", 0)) / 0.8)
    elif hypothesis == "overfit_guard":
        signal = min(
            1.0,
            float(diagnostics.get("max_stable_signal", 0)) / 0.8,
        )
    elif hypothesis == "temporal_dependency":
        signal = min(
            1.0,
            max(0.0, float(diagnostics.get("transition_peak", 1)) - 1),
        )
    else:
        signal = maturity
    return round(0.20 + 0.80 * maturity * max(0.25, signal), 6)


def build_hypothesis_context(game: str, draws: list[Draw]) -> dict:
    main_sequences = [tuple(draw.numbers) for draw in draws]
    main_models = _sequence_models(main_sequences, POOL[game])
    special_models = None
    if game == SUPER:
        special_sequences = [(int(draw.special),) for draw in draws]
        special_models = _sequence_models(
            special_sequences,
            SPECIAL_POOL[SUPER],
        )

    models = {}
    for hypothesis in HYPOTHESIS_IDS:
        main_weights, diagnostics = main_models[hypothesis]
        special_weights = (
            special_models[hypothesis][0] if special_models is not None else None
        )
        strength = _evidence_strength(
            hypothesis,
            len(draws),
            diagnostics,
        )
        models[hypothesis] = {
            **HYPOTHESES[hypothesis],
            "main_weights": main_weights,
            "main_probabilities": _inclusion_probabilities(
                main_weights,
                PICK_N,
            ),
            "special_weights": special_weights,
            "special_probabilities": (
                _inclusion_probabilities(special_weights, 1)
                if special_weights is not None
                else None
            ),
            "diagnostics": diagnostics,
            "evidence_strength": strength,
        }
    return {
        "history_count": len(draws),
        "models": models,
    }


def _structural_distance(numbers: list[int], diagnostics: dict) -> float:
    if not diagnostics.get("history_window"):
        return 0.0
    consecutive = sum(
        1
        for left, right in zip(numbers, numbers[1:])
        if right - left == 1
    )
    return (
        abs(sum(numbers) - diagnostics["target_sum"]) / max(1.0, diagnostics["target_sum"])
        + abs(sum(number % 2 for number in numbers) - diagnostics["target_odd"]) / PICK_N
        + abs((numbers[-1] - numbers[0]) - diagnostics["target_range"])
        / max(1.0, diagnostics["target_range"])
        + abs(consecutive - diagnostics["target_consecutive"]) / PICK_N
    )


def propose(
    hypothesis: str,
    game: str,
    rng: random.Random,
    context: dict,
) -> dict:
    model = context["models"][hypothesis]
    if hypothesis == "structural_bias":
        candidates = [
            _weighted_sample(rng, model["main_weights"], PICK_N)
            for _ in range(STRUCTURAL_SEARCH_CANDIDATES)
        ]
        numbers = min(
            candidates,
            key=lambda values: (
                _structural_distance(values, model["diagnostics"]),
                values,
            ),
        )
    else:
        numbers = _weighted_sample(rng, model["main_weights"], PICK_N)
    special = (
        _weighted_sample(rng, model["special_weights"], 1)[0]
        if game == SUPER
        else None
    )
    distribution_payload = {
        "hypothesis": hypothesis,
        "main": [
            round(model["main_probabilities"][number], 10)
            for number in sorted(model["main_probabilities"])
        ],
        "special": (
            [
                round(model["special_probabilities"][number], 10)
                for number in sorted(model["special_probabilities"])
            ]
            if model["special_probabilities"] is not None
            else None
        ),
    }
    distribution_hash = hashlib.sha256(
        json.dumps(
            distribution_payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "numbers": numbers,
        "special": special,
        "meta": {
            "hypothesis_code": model["code"],
            "evidence_strength": model["evidence_strength"],
            "distribution_hash": distribution_hash,
        },
    }


def public_hypothesis_snapshots(context: dict) -> list[dict]:
    snapshots = []
    for hypothesis in sorted(
        HYPOTHESIS_IDS,
        key=lambda item: HYPOTHESES[item]["code"],
    ):
        model = context["models"][hypothesis]
        snapshots.append(
            {
                "id": hypothesis,
                "code": model["code"],
                "name": model["name"],
                "doctrine": model["doctrine"],
                "thesis": model["thesis"],
                "evidence_strength": model["evidence_strength"],
                "diagnostics": model["diagnostics"],
                "main_probabilities": [
                    round(model["main_probabilities"][number], 10)
                    for number in sorted(model["main_probabilities"])
                ],
                "special_probabilities": (
                    [
                        round(model["special_probabilities"][number], 10)
                        for number in sorted(model["special_probabilities"])
                    ]
                    if model["special_probabilities"] is not None
                    else None
                ),
            }
        )
    return snapshots
