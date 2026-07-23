"""把 lag-overlap 完整 subset 模型加入 immutable 機率前緣 v2。"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import statistics

from engine.agent_loop import canonical_hash
from engine.games import GAME_NAMES, LOTTO649, SUPER
from research.gates import tree_sha256
from research.lag_overlap_signal import (
    MODEL_ID as LAG_OVERLAP_MODEL_ID,
    validate_result as validate_lag_overlap_result,
)
from research.probability_frontier import (
    METHOD_IDS as V1_METHOD_IDS,
    validate_result as validate_v1_frontier,
)


EXPERIMENT_ID = "main-subset-probability-frontier-v2"
PROTOCOL_FILE = "PROBABILITY_FRONTIER_V2_PROTOCOL.md"
GAMES = (SUPER, LOTTO649)
SOURCE_FILES = {
    "probability_frontier_v1": (
        "research/results/probability_frontier.json"
    ),
    "lag_overlap_signal": (
        "research/results/lag_overlap_signal.json"
    ),
}
METHOD_IDS = (*V1_METHOD_IDS, LAG_OVERLAP_MODEL_ID)
METHOD_NAMES = {
    LAG_OVERLAP_MODEL_ID: "相鄰期重複數 Dirichlet null 1",
}
EXCLUDED_METRIC_FAMILIES = [
    "marginal_mass_log_loss",
    "top_k_or_ticket_hits",
    "prize_or_profit_event_probability",
    "second_zone_or_bonus_probability",
    "duplicate_null_safe_lag_overlap",
]
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
    "v1_policy": "immutable_source_rows",
    "lag_overlap_policy": "unconditional_raw_model_inclusion",
    "historical_use": "descriptive_frontier_only",
    "promotion_evidence": "new_future_preregistered_scores_only",
    "excluded_metric_families": EXCLUDED_METRIC_FAMILIES,
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
            raise ValueError("前緣 v2 不得包含非有限浮點數")
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


def _load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"前緣 v2 來源無法解析：{path}") from error
    if not isinstance(value, dict):
        raise RuntimeError(f"前緣 v2 來源根節點不合法：{path}")
    return value


def _load_sources(base: Path) -> dict[str, dict]:
    sources = {}
    for source_id, relative_path in SOURCE_FILES.items():
        path = Path(base) / relative_path
        if not path.exists():
            raise RuntimeError(f"缺少前緣 v2 來源：{relative_path}")
        sources[source_id] = _load_json(path)
    validate_v1_frontier(sources["probability_frontier_v1"])
    validate_lag_overlap_result(sources["lag_overlap_signal"])
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
            "canonical_payload_hash": canonical_hash(source),
            "experiment_id": source["experiment_id"],
            "audit_hash": source["audit_hash"],
        }
        for source_id, source in sources.items()
    }


def _assert_comparable_sources(
    sources: dict[str, dict],
) -> dict[str, dict]:
    v1 = sources["probability_frontier_v1"]
    lag = sources["lag_overlap_signal"]
    games = deepcopy(v1["data_quality"]["games"])
    for game in GAMES:
        v1_game = games[game]
        lag_game = lag["data_quality"]["games"][game]
        date_range = lag_game["date_range"]
        if (
            lag_game["draws"] != v1_game["draws"]
            or date_range[0] != v1_game["first_date"]
            or date_range[1] != v1_game["last_date"]
            or lag_game["ledger_verification"]
            != v1_game["ledger_verification"]
        ):
            raise RuntimeError(
                f"{game} 前緣 v2 歷史或 ledger 不一致"
            )
    v1_records = v1["records_integrity"]
    lag_records = lag["records_integrity"]
    if (
        v1_records["unchanged"] is not True
        or lag_records["unchanged"] is not True
        or v1_records["after_sha256"]
        != lag_records["after_sha256"]
    ):
        raise RuntimeError("前緣 v2 records 基線不一致")
    return games


def _map_v1_row(row: dict) -> dict:
    mapped = deepcopy(row)
    mapped["rank"] = None
    mapped["source_ids"] = ["probability_frontier_v1"]
    for game in GAMES:
        mapped["game_results"][game]["source_id"] = (
            "probability_frontier_v1"
        )
    return mapped


def _game_result_from_lag(
    game: str,
    row: dict,
) -> dict:
    return {
        "game": game,
        "game_name": GAME_NAMES[game],
        "draws": row["draws"],
        "first_date": row["first_date"],
        "last_date": row["last_date"],
        "mean_regret_nats": row["raw_mean_regret_nats"],
        "bootstrap_95_low": row["raw_bootstrap_95_low"],
        "bootstrap_95_high": row["raw_bootstrap_95_high"],
        "geometric_probability_ratio_vs_uniform": math.exp(
            -row["raw_mean_regret_nats"]
        ),
        "source_id": "lag_overlap_signal",
    }


def _lag_overlap_row(source: dict) -> dict:
    game_results = {
        game: _game_result_from_lag(
            game,
            source["diagnostics"][game],
        )
        for game in GAMES
    }
    regrets = [
        game_results[game]["mean_regret_nats"] for game in GAMES
    ]
    mean_regret = statistics.fmean(regrets)
    minimax_regret = max(regrets)
    return {
        "rank": None,
        "method_id": LAG_OVERLAP_MODEL_ID,
        "method_name": METHOD_NAMES[LAG_OVERLAP_MODEL_ID],
        "family": "lag_overlap",
        "non_uniform": True,
        "source_ids": ["lag_overlap_signal"],
        "game_results": game_results,
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


def build_frontier_rows(sources: dict[str, dict]) -> list[dict]:
    v1_rows = sources["probability_frontier_v1"]["frontier_rows"]
    rows = [_map_v1_row(row) for row in v1_rows]
    rows.append(_lag_overlap_row(sources["lag_overlap_signal"]))
    if (
        len(rows) != len(METHOD_IDS)
        or {row["method_id"] for row in rows} != set(METHOD_IDS)
    ):
        raise RuntimeError("前緣 v2 方法列不完整")
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
        raise ValueError("前緣 v2 排名不完整")
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
        "v1_immutable": True,
        "reason": (
            "新增 lag-overlap 後，所有可比較非均勻方法在兩款遊戲"
            "平均完整 subset regret 仍大於 0；精確均勻 null-safe "
            "維持 minimax champion。"
        ),
        "next_evidence": (
            "只接受開獎前封存、不可回填的 v7 未來完整 subset "
            "proper score；不同量尺不得替代。"
        ),
    }


def run_probability_frontier_v2(*, base: Path) -> dict:
    base = Path(base).resolve()
    records_before = tree_sha256(base / "records")
    protocol_path = base / PROTOCOL_FILE
    if not protocol_path.exists():
        raise RuntimeError(f"缺少前緣 v2 契約：{PROTOCOL_FILE}")
    sources = _load_sources(base)
    games = _assert_comparable_sources(sources)
    rows = build_frontier_rows(sources)
    source_manifest = _source_manifest(sources, base=base)
    source_records = {
        source_id: source["records_integrity"]["after_sha256"]
        for source_id, source in sources.items()
    }
    records_after = tree_sha256(base / "records")
    result = {
        "schema_version": "1",
        "experiment_id": EXPERIMENT_ID,
        "generated_at": max(
            source["generated_at"] for source in sources.values()
        ),
        "question": (
            "加入預先指定 lag-overlap 模型後，12 個完整六主號 "
            "proper-score 方法的 minimax champion 是否改變？"
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
            "excluded_metric_families": EXCLUDED_METRIC_FAMILIES,
            "source_records_hashes": source_records,
            "v1_method_count": len(V1_METHOD_IDS),
            "new_method_count": 1,
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
            "lag-overlap 是預先指定的單一低維候選，不代表已搜尋所有機制。",
            "零 regret 是公平基準，不是已證明存在可預測號碼。",
            "只有新的開獎前 proper score 能支持未來非均勻模型。",
            "純模擬，不構成購買或下注建議。",
        ],
    }
    result = _stable_floats(result)
    result["audit_hash"] = canonical_hash(result)
    validate_result(result)
    return result


def _require_finite(record: dict, field: str) -> float:
    value = record.get(field)
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
    ):
        raise ValueError(f"前緣 v2 欄位非有限：{field}")
    return float(value)


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
        raise ValueError("前緣 v2 schema 不合法")
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
        raise ValueError("前緣 v2 protocol 不一致")

    sources = result["source_artifacts"]
    if set(sources) != set(SOURCE_FILES):
        raise ValueError("前緣 v2 來源集合不一致")
    expected_experiments = {
        "probability_frontier_v1": "main-subset-probability-frontier-v1",
        "lag_overlap_signal": (
            "lag-overlap-subset-probability-audit-v1"
        ),
    }
    for source_id, relative_path in SOURCE_FILES.items():
        source = sources[source_id]
        if (
            set(source)
            != {
                "path",
                "file_sha256",
                "canonical_payload_hash",
                "experiment_id",
                "audit_hash",
            }
            or source.get("path") != relative_path
            or source.get("experiment_id")
            != expected_experiments[source_id]
            or any(
                not _is_sha256(source.get(field))
                for field in (
                    "file_sha256",
                    "canonical_payload_hash",
                    "audit_hash",
                )
            )
        ):
            raise ValueError(f"前緣 v2 來源不合法：{source_id}")

    quality = result["data_quality"]
    games = quality.get("games", {})
    if (
        quality.get("status") != "pass"
        or quality.get("comparability")
        != "same_complete_main_subset_proper_score"
        or quality.get("included_method_count") != len(METHOD_IDS)
        or quality.get("excluded_metric_families")
        != EXCLUDED_METRIC_FAMILIES
        or set(quality.get("source_records_hashes", {}))
        != set(SOURCE_FILES)
        or len(set(quality["source_records_hashes"].values())) != 1
        or quality.get("v1_method_count") != len(V1_METHOD_IDS)
        or quality.get("new_method_count") != 1
        or set(games) != set(GAMES)
    ):
        raise ValueError("前緣 v2 資料品質不一致")
    for game in GAMES:
        game_row = games[game]
        if (
            game_row.get("game") != game
            or game_row.get("game_name") != GAME_NAMES[game]
            or not isinstance(game_row.get("draws"), int)
            or game_row["draws"] <= 0
            or not isinstance(game_row.get("first_date"), str)
            or not isinstance(game_row.get("last_date"), str)
            or game_row["first_date"] > game_row["last_date"]
            or set(game_row.get("ledger_verification", {}))
            != {"lines", "last_event_hash", "ledger_sha256"}
            or game_row["ledger_verification"]["lines"]
            != game_row["draws"]
        ):
            raise ValueError(f"{game} 前緣 v2 遊戲品質不合法")

    rows = result["frontier_rows"]
    if (
        not isinstance(rows, list)
        or len(rows) != len(METHOD_IDS)
        or {row.get("method_id") for row in rows} != set(METHOD_IDS)
        or [row.get("rank") for row in rows]
        != list(range(1, len(METHOD_IDS) + 1))
    ):
        raise ValueError("前緣 v2 列集合不完整")
    for row in rows:
        method_id = row["method_id"]
        expected_source = (
            "lag_overlap_signal"
            if method_id == LAG_OVERLAP_MODEL_ID
            else "probability_frontier_v1"
        )
        if (
            set(row)
            != {
                "rank",
                "method_id",
                "method_name",
                "family",
                "non_uniform",
                "source_ids",
                "game_results",
                "mean_regret_across_games",
                "minimax_regret",
                "worst_game_probability_ratio_vs_uniform",
                "strictly_dominated_by_uniform",
                "both_games_mean_negative",
                "both_games_bootstrap_upper_negative",
                "historical_promotion_eligible",
            }
            or row["source_ids"] != [expected_source]
            or set(row["game_results"]) != set(GAMES)
            or row["non_uniform"]
            is not (method_id != "uniform_null_safe")
            or row["historical_promotion_eligible"] is not False
        ):
            raise ValueError(f"前緣 v2 方法欄位不合法：{method_id}")
        regrets = []
        upper_bounds = []
        for game in GAMES:
            game_result = row["game_results"][game]
            if (
                set(game_result)
                != {
                    "game",
                    "game_name",
                    "draws",
                    "first_date",
                    "last_date",
                    "mean_regret_nats",
                    "bootstrap_95_low",
                    "bootstrap_95_high",
                    "geometric_probability_ratio_vs_uniform",
                    "source_id",
                }
                or game_result["game"] != game
                or game_result["game_name"] != GAME_NAMES[game]
                or game_result["draws"] != games[game]["draws"]
                or game_result["first_date"] != games[game]["first_date"]
                or game_result["last_date"] != games[game]["last_date"]
                or game_result["source_id"] != expected_source
            ):
                raise ValueError(
                    f"{game} 前緣 v2 方法結果不合法：{method_id}"
                )
            regret = _require_finite(
                game_result,
                "mean_regret_nats",
            )
            _require_finite(game_result, "bootstrap_95_low")
            upper = _require_finite(
                game_result,
                "bootstrap_95_high",
            )
            ratio = _require_finite(
                game_result,
                "geometric_probability_ratio_vs_uniform",
            )
            if not math.isclose(
                ratio,
                math.exp(-regret),
                rel_tol=5e-13,
                abs_tol=1e-15,
            ):
                raise ValueError("前緣 v2 遊戲機率倍數不一致")
            regrets.append(regret)
            upper_bounds.append(upper)
        mean_regret = statistics.fmean(regrets)
        minimax_regret = max(regrets)
        expected_dominated = (
            all(value >= 0 for value in regrets)
            and any(value > 0 for value in regrets)
        )
        if (
            not math.isclose(
                _require_finite(row, "mean_regret_across_games"),
                mean_regret,
                rel_tol=5e-13,
                abs_tol=1e-15,
            )
            or not math.isclose(
                _require_finite(row, "minimax_regret"),
                minimax_regret,
                rel_tol=5e-13,
                abs_tol=1e-15,
            )
            or not math.isclose(
                _require_finite(
                    row,
                    "worst_game_probability_ratio_vs_uniform",
                ),
                math.exp(-minimax_regret),
                rel_tol=5e-13,
                abs_tol=1e-15,
            )
            or row["strictly_dominated_by_uniform"]
            is not expected_dominated
            or row["both_games_mean_negative"]
            is not all(value < 0 for value in regrets)
            or row["both_games_bootstrap_upper_negative"]
            is not all(value < 0 for value in upper_bounds)
        ):
            raise ValueError(f"前緣 v2 衍生值不一致：{method_id}")

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
        raise ValueError("前緣 v2 排序不一致")
    if result["conclusion"] != build_conclusion(rows):
        raise ValueError("前緣 v2 結論不一致")
    integrity = result["records_integrity"]
    if (
        set(integrity)
        != {"before_sha256", "after_sha256", "unchanged"}
        or not _is_sha256(integrity.get("before_sha256"))
        or not _is_sha256(integrity.get("after_sha256"))
        or integrity.get("before_sha256")
        != integrity.get("after_sha256")
        or integrity.get("unchanged") is not True
    ):
        raise ValueError("前緣 v2 records 完整性失敗")
    if (
        not isinstance(result.get("limitations"), list)
        or len(result["limitations"]) < 4
        or not _is_sha256(result.get("audit_hash"))
    ):
        raise ValueError("前緣 v2 限制或 audit hash 不合法")
    payload = dict(result)
    observed = payload.pop("audit_hash")
    if observed != canonical_hash(payload):
        raise ValueError("前緣 v2 audit hash 不一致")
    return result


def write_result(result: dict, path: Path) -> Path:
    validate_result(result)
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output
