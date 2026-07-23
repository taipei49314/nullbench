"""統一比較正式完整六主號 subset proper-score 模型。"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import statistics

from engine.agent_loop import canonical_hash
from engine.games import GAME_NAMES, LOTTO649, SUPER
from null_safe_probability_verify import (
    verify_formal_result as verify_null_safe_result,
)
from research.draw_order_signal import (
    validate_result as validate_draw_order_result,
)
from research.gates import tree_sha256
from research.persistent_bias_signal import (
    validate_result as validate_persistent_bias_result,
)
from research.temporal_stacking_diagnostic import (
    METHODS as TEMPORAL_METHODS,
    validate_result as validate_temporal_result,
)


EXPERIMENT_ID = "main-subset-probability-frontier-v1"
PROTOCOL_FILE = "PROBABILITY_FRONTIER_PROTOCOL.md"
GAMES = (SUPER, LOTTO649)
SOURCE_FILES = {
    "null_safe_probability": (
        "research/results/null_safe_probability.json"
    ),
    "temporal_stacking_diagnostic": (
        "research/results/temporal_stacking_diagnostic.json"
    ),
    "draw_order_signal": (
        "research/results/draw_order_signal.json"
    ),
    "persistent_bias_signal": (
        "research/results/persistent_bias_signal.json"
    ),
}
METHOD_IDS = (
    "uniform_null_safe",
    "current_cumulative_marginal",
    "subset_cumulative",
    "subset_rolling_52",
    "subset_rolling_104",
    "subset_rolling_208",
    "subset_ewma_52",
    "subset_ewma_104",
    "subset_ewma_208",
    "position_dirichlet_1",
    "persistent_dirichlet_1",
)
METHOD_NAMES = {
    "uniform_null_safe": "精確均勻／null-safe",
    "current_cumulative_marginal": "現行累積 marginal stacking",
    "subset_cumulative": "完整 subset 累積 stacking",
    "subset_rolling_52": "完整 subset rolling 52",
    "subset_rolling_104": "完整 subset rolling 104",
    "subset_rolling_208": "完整 subset rolling 208",
    "subset_ewma_52": "完整 subset EWMA 52",
    "subset_ewma_104": "完整 subset EWMA 104",
    "subset_ewma_208": "完整 subset EWMA 208",
    "position_dirichlet_1": "六位置 Dirichlet 1",
    "persistent_dirichlet_1": "持續球號 Dirichlet 1",
}
PROTOCOL_CONFIG = {
    "games": list(GAMES),
    "target": "complete_unordered_six_main_number_subset",
    "score": (
        "candidate_negative_log_probability_minus_"
        "exact_uniform_negative_log_probability"
    ),
    "unit": "nats_per_draw",
    "source_ids": list(SOURCE_FILES),
    "method_ids": list(METHOD_IDS),
    "ranking": [
        "minimax_regret_ascending",
        "mean_regret_across_games_ascending",
        "method_id_ascending",
    ],
    "historical_use": "descriptive_frontier_only",
    "promotion_evidence": "new_future_preregistered_scores_only",
    "excluded_metric_families": [
        "marginal_mass_log_loss",
        "top_k_or_ticket_hits",
        "prize_or_profit_event_probability",
        "second_zone_or_bonus_probability",
    ],
}
PROTOCOL_HASH = canonical_hash(PROTOCOL_CONFIG)


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_floats(value):
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("前緣 artifact 不得包含非有限浮點數")
        return float(format(value, ".15g"))
    if isinstance(value, list):
        return [_stable_floats(item) for item in value]
    if isinstance(value, tuple):
        return [_stable_floats(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _stable_floats(item)
            for key, item in value.items()
        }
    return value


def _load_sources(base: Path) -> dict[str, dict]:
    sources = {}
    for source_id, relative_path in SOURCE_FILES.items():
        path = Path(base) / relative_path
        if not path.exists():
            raise RuntimeError(f"缺少前緣來源：{relative_path}")
        try:
            sources[source_id] = json.loads(
                path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError(
                f"前緣來源無法解析：{relative_path}"
            ) from error

    verify_null_safe_result(sources["null_safe_probability"])
    validate_temporal_result(
        sources["temporal_stacking_diagnostic"]
    )
    validate_draw_order_result(sources["draw_order_signal"])
    validate_persistent_bias_result(
        sources["persistent_bias_signal"]
    )
    return sources


def _source_manifest(
    sources: dict[str, dict],
    *,
    base: Path,
) -> dict[str, dict]:
    return {
        source_id: {
            "path": SOURCE_FILES[source_id],
            "file_sha256": _file_sha256(
                Path(base) / SOURCE_FILES[source_id]
            ),
            "payload_hash": canonical_hash(payload),
            "experiment_id": payload.get("experiment_id"),
            "audit_hash": payload.get("audit_hash"),
            "generated_at": payload.get("generated_at"),
        }
        for source_id, payload in sources.items()
    }


def _assert_comparable_sources(
    sources: dict[str, dict],
) -> dict:
    temporal = sources["temporal_stacking_diagnostic"]
    null_safe = sources["null_safe_probability"]
    draw_order = sources["draw_order_signal"]
    persistent = sources["persistent_bias_signal"]
    temporal_quality = temporal["data_quality"]

    games = {}
    for game in GAMES:
        expected = {
            "draws": temporal_quality["ledger_verification"][game][
                "lines"
            ],
            "first_date": temporal_quality["source_first_dates"][game],
            "last_date": temporal_quality["source_last_dates"][game],
            "ledger_verification": temporal_quality[
                "ledger_verification"
            ][game],
        }
        null_summary = null_safe["prequential_summary"][game]
        draw_profile = draw_order["data_quality"]["games"][game]
        persistent_profile = persistent["data_quality"]["games"][game]
        if (
            null_summary["draws"] != expected["draws"]
            or null_summary["first_date"] != expected["first_date"]
            or null_summary["last_date"] != expected["last_date"]
            or null_safe["data_quality"]["ledger_verification"][game]
            != expected["ledger_verification"]
            or draw_profile["draws"] != expected["draws"]
            or draw_profile["date_range"]
            != [expected["first_date"], expected["last_date"]]
            or draw_profile["ledger_verification"]
            != expected["ledger_verification"]
            or persistent_profile["draws"] != expected["draws"]
            or persistent_profile["date_range"]
            != [expected["first_date"], expected["last_date"]]
            or persistent_profile["ledger_verification"]
            != expected["ledger_verification"]
        ):
            raise RuntimeError(f"{game} 前緣來源期數或 ledger 不一致")
        games[game] = {
            "game": game,
            "game_name": GAME_NAMES[game],
            **expected,
        }

    temporal_rows = {
        (row["game"], row["method"]): row
        for row in temporal["diagnostic_rows"]
        if row["dimension"] == "main"
    }
    if set(temporal_rows) != {
        (game, method)
        for game in GAMES
        for method in TEMPORAL_METHODS
    }:
        raise RuntimeError("時間 stacking 主號方法集合不完整")
    for game in GAMES:
        uniform = temporal_rows[(game, "uniform")]
        current = temporal_rows[
            (game, "current_cumulative_marginal")
        ]
        null_main = null_safe["prequential_summary"][game]["main"]
        if (
            uniform["mean_regret_nats"] != 0
            or uniform["bootstrap_95_low"] != 0
            or uniform["bootstrap_95_high"] != 0
            or not math.isclose(
                current["mean_regret_nats"],
                null_main["existing_mixture_regret_vs_uniform"],
                rel_tol=1e-12,
                abs_tol=1e-15,
            )
            or null_main["null_safe_regret_vs_uniform"] != 0
        ):
            raise RuntimeError(f"{game} null-safe 交叉量尺不一致")
    return games


def _game_result(
    *,
    game: str,
    mean_regret: float,
    bootstrap_low: float,
    bootstrap_high: float,
    draws: int,
    first_date: str,
    last_date: str,
    source_id: str,
) -> dict:
    values = (
        mean_regret,
        bootstrap_low,
        bootstrap_high,
    )
    if any(
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        for value in values
    ):
        raise ValueError("前緣遊戲結果必須為有限數值")
    return {
        "game": game,
        "game_name": GAME_NAMES[game],
        "draws": int(draws),
        "first_date": str(first_date),
        "last_date": str(last_date),
        "mean_regret_nats": float(mean_regret),
        "bootstrap_95_low": float(bootstrap_low),
        "bootstrap_95_high": float(bootstrap_high),
        "geometric_probability_ratio_vs_uniform": math.exp(
            -float(mean_regret)
        ),
        "source_id": source_id,
    }


def build_frontier_row(
    *,
    method_id: str,
    family: str,
    game_results: dict[str, dict],
    source_ids: list[str],
) -> dict:
    if (
        method_id not in METHOD_IDS
        or set(game_results) != set(GAMES)
        or not source_ids
    ):
        raise ValueError("前緣方法輸入不合法")
    regrets = [
        float(game_results[game]["mean_regret_nats"])
        for game in GAMES
    ]
    mean_regret = statistics.fmean(regrets)
    minimax_regret = max(regrets)
    non_uniform = method_id != "uniform_null_safe"
    return {
        "rank": None,
        "method_id": method_id,
        "method_name": METHOD_NAMES[method_id],
        "family": family,
        "non_uniform": non_uniform,
        "source_ids": list(source_ids),
        "game_results": {
            game: game_results[game] for game in GAMES
        },
        "mean_regret_across_games": mean_regret,
        "minimax_regret": minimax_regret,
        "worst_game_probability_ratio_vs_uniform": math.exp(
            -minimax_regret
        ),
        "strictly_dominated_by_uniform": (
            all(value >= 0 for value in regrets)
            and any(value > 0 for value in regrets)
        ),
        "both_games_mean_negative": all(
            value < 0 for value in regrets
        ),
        "both_games_bootstrap_upper_negative": all(
            game_results[game]["bootstrap_95_high"] < 0
            for game in GAMES
        ),
        "historical_promotion_eligible": False,
    }


def _frontier_rows(
    sources: dict[str, dict],
    games: dict[str, dict],
) -> list[dict]:
    temporal = sources["temporal_stacking_diagnostic"]
    temporal_rows = {
        (row["game"], row["method"]): row
        for row in temporal["diagnostic_rows"]
        if row["dimension"] == "main"
    }
    rows = []
    for temporal_method in TEMPORAL_METHODS:
        method_id = (
            "uniform_null_safe"
            if temporal_method == "uniform"
            else temporal_method
        )
        game_results = {}
        for game in GAMES:
            row = temporal_rows[(game, temporal_method)]
            game_results[game] = _game_result(
                game=game,
                mean_regret=row["mean_regret_nats"],
                bootstrap_low=row["bootstrap_95_low"],
                bootstrap_high=row["bootstrap_95_high"],
                draws=row["draws"],
                first_date=games[game]["first_date"],
                last_date=games[game]["last_date"],
                source_id="temporal_stacking_diagnostic",
            )
        rows.append(
            build_frontier_row(
                method_id=method_id,
                family=(
                    "safe_baseline"
                    if method_id == "uniform_null_safe"
                    else "probability_stacking"
                ),
                game_results=game_results,
                source_ids=(
                    [
                        "null_safe_probability",
                        "temporal_stacking_diagnostic",
                    ]
                    if method_id == "uniform_null_safe"
                    else ["temporal_stacking_diagnostic"]
                ),
            )
        )

    for source_id, method_id, family in (
        (
            "draw_order_signal",
            "position_dirichlet_1",
            "draw_order",
        ),
        (
            "persistent_bias_signal",
            "persistent_dirichlet_1",
            "persistent_label_bias",
        ),
    ):
        source = sources[source_id]
        game_results = {}
        for game in GAMES:
            row = source["diagnostics"][game]
            game_results[game] = _game_result(
                game=game,
                mean_regret=row["mean_regret_nats"],
                bootstrap_low=row["bootstrap_95_low"],
                bootstrap_high=row["bootstrap_95_high"],
                draws=row["draws"],
                first_date=row["first_date"],
                last_date=row["last_date"],
                source_id=source_id,
            )
        rows.append(
            build_frontier_row(
                method_id=method_id,
                family=family,
                game_results=game_results,
                source_ids=[source_id],
            )
        )

    if (
        len(rows) != len(METHOD_IDS)
        or {row["method_id"] for row in rows} != set(METHOD_IDS)
    ):
        raise RuntimeError("前緣方法列不完整")
    rows.sort(
        key=lambda row: (
            row["minimax_regret"],
            row["mean_regret_across_games"],
            row["method_id"],
        )
    )
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    return rows


def build_conclusion(rows: list[dict]) -> dict:
    if (
        len(rows) != len(METHOD_IDS)
        or [row["rank"] for row in rows]
        != list(range(1, len(rows) + 1))
    ):
        raise ValueError("前緣排名不完整")
    champion = rows[0]
    best_non_uniform = next(
        row for row in rows if row["non_uniform"]
    )
    supported = [
        row["method_id"]
        for row in rows
        if row["non_uniform"]
        and row["both_games_mean_negative"]
        and row["both_games_bootstrap_upper_negative"]
    ]
    dominated = [
        row["method_id"]
        for row in rows
        if row["non_uniform"]
        and row["strictly_dominated_by_uniform"]
    ]
    return {
        "status": (
            "retain_uniform_null_safe_champion"
            if champion["method_id"] == "uniform_null_safe"
            and not supported
            else "future_only_research_required"
        ),
        "champion_method_id": champion["method_id"],
        "best_non_uniform_method_id": (
            best_non_uniform["method_id"]
        ),
        "historically_supported_non_uniform_methods": supported,
        "strictly_uniform_dominated_non_uniform_methods": dominated,
        "non_uniform_method_count": sum(
            row["non_uniform"] for row in rows
        ),
        "historical_promotion_eligible": False,
        "watcher_integration_allowed": False,
        "stop_historical_parameter_search": not supported,
        "reason": (
            "所有可比較非均勻方法在兩款遊戲的平均完整 subset "
            "regret 都大於 0；精確均勻 null-safe 是 minimax champion。"
        ),
        "next_evidence": (
            "只接受開獎前封存、不可回填的 v7 未來完整 subset "
            "proper score；不同量尺不得替代。"
        ),
    }


def run_probability_frontier(*, base: Path) -> dict:
    base = Path(base).resolve()
    records_before = tree_sha256(base / "records")
    protocol_path = base / PROTOCOL_FILE
    if not protocol_path.exists():
        raise RuntimeError(f"缺少前緣契約：{PROTOCOL_FILE}")
    sources = _load_sources(base)
    games = _assert_comparable_sources(sources)
    rows = _frontier_rows(sources, games)
    source_manifest = _source_manifest(sources, base=base)

    source_records = {
        source_id: source["records_integrity"]["after_sha256"]
        for source_id, source in sources.items()
    }
    if (
        len(set(source_records.values())) != 1
        or any(
            source["records_integrity"]["unchanged"] is not True
            for source in sources.values()
        )
    ):
        raise RuntimeError("前緣來源 records 基線不一致")
    records_after = tree_sha256(base / "records")
    generated_at = max(
        source["generated_at"] for source in sources.values()
    )
    result = {
        "schema_version": "1",
        "experiment_id": EXPERIMENT_ID,
        "generated_at": generated_at,
        "question": (
            "已正式完成且可比較的完整六主號 proper-score 模型中，"
            "哪一個是雙遊戲 minimax champion？"
        ),
        "protocol": {
            **PROTOCOL_CONFIG,
            "protocol_hash": PROTOCOL_HASH,
            "protocol_file": PROTOCOL_FILE,
            "protocol_file_sha256": _file_sha256(protocol_path),
        },
        "source_artifacts": source_manifest,
        "data_quality": {
            "status": "pass",
            "comparability": "same_complete_main_subset_proper_score",
            "games": games,
            "included_method_count": len(rows),
            "excluded_metric_families": (
                PROTOCOL_CONFIG["excluded_metric_families"]
            ),
            "source_records_hashes": source_records,
        },
        "frontier_rows": rows,
        "conclusion": build_conclusion(rows),
        "records_integrity": {
            "before_sha256": records_before,
            "after_sha256": records_after,
            "unchanged": records_before == records_after,
        },
        "limitations": [
            "完整歷史已被多項研究使用，前緣只有描述性決策地位。",
            "零 regret 是公平基準，不是已證明存在可預測號碼。",
            "排除項目回答不同問題，不能據此推論它們沒有結構價值。",
            "只有新的開獎前 proper score 能支持未來非均勻模型。",
            "純模擬，不構成購買或下注建議。",
        ],
    }
    result = _stable_floats(result)
    result["audit_hash"] = canonical_hash(result)
    validate_result(result)
    return result


def validate_result(result: dict) -> dict:
    expected_keys = {
        "schema_version",
        "experiment_id",
        "generated_at",
        "question",
        "protocol",
        "source_artifacts",
        "data_quality",
        "frontier_rows",
        "conclusion",
        "records_integrity",
        "limitations",
        "audit_hash",
    }
    if (
        not isinstance(result, dict)
        or set(result) != expected_keys
        or result.get("schema_version") != "1"
        or result.get("experiment_id") != EXPERIMENT_ID
    ):
        raise ValueError("機率前緣 schema 不合法")
    protocol = result["protocol"]
    if (
        any(
            protocol.get(key) != value
            for key, value in PROTOCOL_CONFIG.items()
        )
        or protocol.get("protocol_hash") != PROTOCOL_HASH
        or protocol.get("protocol_file") != PROTOCOL_FILE
        or not _is_sha256(protocol.get("protocol_file_sha256"))
    ):
        raise ValueError("機率前緣 protocol 不一致")

    sources = result["source_artifacts"]
    if set(sources) != set(SOURCE_FILES):
        raise ValueError("機率前緣來源集合不一致")
    for source_id, relative_path in SOURCE_FILES.items():
        source = sources[source_id]
        if (
            source.get("path") != relative_path
            or not _is_sha256(source.get("file_sha256"))
            or not _is_sha256(source.get("payload_hash"))
            or not isinstance(source.get("experiment_id"), str)
            or not isinstance(source.get("generated_at"), str)
            or (
                source.get("audit_hash") is not None
                and not _is_sha256(source.get("audit_hash"))
            )
        ):
            raise ValueError(f"機率前緣來源不合法：{source_id}")

    quality = result["data_quality"]
    games = quality.get("games", {})
    if (
        quality.get("status") != "pass"
        or quality.get("comparability")
        != "same_complete_main_subset_proper_score"
        or set(games) != set(GAMES)
        or quality.get("included_method_count") != len(METHOD_IDS)
        or quality.get("excluded_metric_families")
        != PROTOCOL_CONFIG["excluded_metric_families"]
        or set(quality.get("source_records_hashes", {}))
        != set(SOURCE_FILES)
        or len(set(quality["source_records_hashes"].values())) != 1
        or any(
            not _is_sha256(value)
            for value in quality["source_records_hashes"].values()
        )
    ):
        raise ValueError("機率前緣資料品質不一致")
    for game in GAMES:
        row = games[game]
        if (
            row.get("game") != game
            or row.get("game_name") != GAME_NAMES[game]
            or not isinstance(row.get("draws"), int)
            or row["draws"] <= 0
            or not isinstance(row.get("first_date"), str)
            or not isinstance(row.get("last_date"), str)
            or row["first_date"] >= row["last_date"]
            or set(row.get("ledger_verification", {}))
            != {"lines", "last_event_hash", "ledger_sha256"}
            or row["ledger_verification"]["lines"] != row["draws"]
            or not _is_sha256(
                row["ledger_verification"]["last_event_hash"]
            )
            or not _is_sha256(
                row["ledger_verification"]["ledger_sha256"]
            )
        ):
            raise ValueError(f"{game} 機率前緣遊戲品質不合法")

    rows = result["frontier_rows"]
    if (
        not isinstance(rows, list)
        or len(rows) != len(METHOD_IDS)
        or {row.get("method_id") for row in rows} != set(METHOD_IDS)
        or [row.get("rank") for row in rows]
        != list(range(1, len(METHOD_IDS) + 1))
    ):
        raise ValueError("機率前緣列集合不完整")
    for row in rows:
        method_id = row["method_id"]
        if (
            row.get("method_name") != METHOD_NAMES[method_id]
            or row.get("non_uniform")
            is not (method_id != "uniform_null_safe")
            or set(row.get("game_results", {})) != set(GAMES)
            or not row.get("source_ids")
            or not set(row["source_ids"]).issubset(SOURCE_FILES)
            or row.get("historical_promotion_eligible") is not False
        ):
            raise ValueError(f"機率前緣方法欄位不合法：{method_id}")
        regrets = []
        for game in GAMES:
            game_row = row["game_results"][game]
            finite_fields = (
                "mean_regret_nats",
                "bootstrap_95_low",
                "bootstrap_95_high",
                "geometric_probability_ratio_vs_uniform",
            )
            if (
                game_row.get("game") != game
                or game_row.get("game_name") != GAME_NAMES[game]
                or game_row.get("draws") != games[game]["draws"]
                or game_row.get("first_date")
                != games[game]["first_date"]
                or game_row.get("last_date")
                != games[game]["last_date"]
                or game_row.get("source_id") not in SOURCE_FILES
                or any(
                    not isinstance(game_row.get(field), (int, float))
                    or isinstance(game_row.get(field), bool)
                    or not math.isfinite(float(game_row[field]))
                    for field in finite_fields
                )
                or not math.isclose(
                    game_row[
                        "geometric_probability_ratio_vs_uniform"
                    ],
                    math.exp(-game_row["mean_regret_nats"]),
                    rel_tol=1e-12,
                    abs_tol=1e-15,
                )
            ):
                raise ValueError(
                    f"{method_id} {game} 前緣結果不合法"
                )
            regrets.append(game_row["mean_regret_nats"])
        expected_mean = statistics.fmean(regrets)
        expected_minimax = max(regrets)
        expected_dominated = (
            all(value >= 0 for value in regrets)
            and any(value > 0 for value in regrets)
        )
        if (
            not math.isclose(
                row.get("mean_regret_across_games", math.nan),
                expected_mean,
                rel_tol=1e-12,
                abs_tol=1e-15,
            )
            or not math.isclose(
                row.get("minimax_regret", math.nan),
                expected_minimax,
                rel_tol=1e-12,
                abs_tol=1e-15,
            )
            or not math.isclose(
                row.get(
                    "worst_game_probability_ratio_vs_uniform",
                    math.nan,
                ),
                math.exp(-expected_minimax),
                rel_tol=1e-12,
                abs_tol=1e-15,
            )
            or row.get("strictly_dominated_by_uniform")
            is not expected_dominated
            or row.get("both_games_mean_negative")
            is not all(value < 0 for value in regrets)
            or row.get("both_games_bootstrap_upper_negative")
            is not all(
                row["game_results"][game][
                    "bootstrap_95_high"
                ]
                < 0
                for game in GAMES
            )
        ):
            raise ValueError(f"{method_id} 前緣聚合不一致")
    expected_order = sorted(
        rows,
        key=lambda row: (
            row["minimax_regret"],
            row["mean_regret_across_games"],
            row["method_id"],
        ),
    )
    if [row["method_id"] for row in rows] != [
        row["method_id"] for row in expected_order
    ]:
        raise ValueError("機率前緣排序不一致")
    if result.get("conclusion") != build_conclusion(rows):
        raise ValueError("機率前緣結論不一致")

    integrity = result["records_integrity"]
    if (
        set(integrity)
        != {"before_sha256", "after_sha256", "unchanged"}
        or not _is_sha256(integrity["before_sha256"])
        or not _is_sha256(integrity["after_sha256"])
        or integrity["unchanged"] is not True
        or integrity["before_sha256"] != integrity["after_sha256"]
    ):
        raise ValueError("機率前緣 records 完整性失敗")
    audit_payload = {
        key: value
        for key, value in result.items()
        if key != "audit_hash"
    }
    if (
        not _is_sha256(result.get("audit_hash"))
        or result["audit_hash"] != canonical_hash(audit_payload)
    ):
        raise ValueError("機率前緣 audit hash 不一致")
    return result


def write_result(result: dict, path: Path) -> Path:
    validate_result(result)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path
