"""稽核實體開獎中介資料是否能在投注截止前合法用於選號。"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime
import hashlib
import json
import math
from pathlib import Path
import re

from engine.agent_loop import canonical_hash
from engine.games import GAME_NAMES, LOTTO649, SUPER
from research.gates import tree_sha256


EXPERIMENT_ID = "physical-draw-metadata-availability-audit-v1"
PROTOCOL_FILE = "PHYSICAL_METADATA_PROTOCOL.md"
SCHEMA_VERSION = "1"
GENERATED_AT = "2026-07-19T15:30:00+08:00"
GAMES = (SUPER, LOTTO649)
RESULT_KEYS = {
    SUPER: "superLotto638Res",
    LOTTO649: "lotto649Res",
}
MINIMUM_FUTURE_PERIODS_PER_GAME = 104
MINIMUM_FIELD_COMPLETENESS = 0.95

PHYSICAL_FIELD_TERMS = {
    "machine": (
        "machine",
        "machine_id",
        "draw_machine",
        "開獎機",
    ),
    "ball_set": (
        "ball_set",
        "ballset",
        "球組",
    ),
    "equipment": (
        "equipment",
        "device",
        "設備",
    ),
    "location": (
        "studio",
    ),
    "loading_order": (
        "loading_order",
        "drop_order",
        "落球",
    ),
    "anomaly": (
        "anomaly",
        "異常",
    ),
}

OBSERVATION_INPUT_FIELDS = (
    "schema_version",
    "game",
    "period",
    "draw_date",
    "registration_cutoff_at",
    "public_observed_at",
    "video_id",
    "archive_url",
    "evidence_frame_timestamp",
    "machine_id",
    "ball_set_id",
    "loading_order",
    "anomaly_flags",
    "source_scope",
    "extraction_method",
    "extraction_confidence",
    "human_verified",
)
OBSERVATION_FIELDS = OBSERVATION_INPUT_FIELDS + (
    "eligible_for_forecast",
    "eligibility_reason",
)
ALLOWED_SOURCE_SCOPES = {
    "target_main_draw",
    "special_bonus",
    "other_game",
}

SOURCE_EVIDENCE = {
    "retrieved_on": "2026-07-19",
    "official_draw_process": {
        "url": "https://www.taiwanlottery.com/run_lottery/info/",
        "facts": [
            "computerized lottery draws occur after betting closes",
            (
                "a draw guest selects the draw machine, ball set, "
                "and ball-loading order"
            ),
            "the live draw recording starts after those selections",
        ],
    },
    "official_faq": {
        "url": "https://www.taiwanlottery.com/customer_service/faq/",
        "facts": [
            "betting cutoff is 20:00 Asia/Taipei",
            "formal drawing starts at 20:30 Asia/Taipei",
            (
                "the 30-minute gap is reserved for central sales "
                "aggregation"
            ),
            "broadcast coverage is selective rather than end-to-end",
        ],
    },
    "official_result_download": {
        "url": (
            "https://www.taiwanlottery.com/lotto/history/"
            "result_download/"
        ),
        "documented_lotto649_fields": [
            "game_name",
            "period",
            "draw_date",
            "sales_amount",
            "sales_count",
            "total_prize",
            "number_1",
            "number_2",
            "number_3",
            "number_4",
            "number_5",
            "number_6",
            "bonus_number",
        ],
        "documented_physical_fields": [],
    },
    "broadcast_sample": {
        "archive_url": (
            "https://d25vj0wbzayc6h.cloudfront.net/Live/3763/24003"
        ),
        "youtube_url": (
            "https://www.youtube.com/watch?v=pRQn_EG-AEY"
        ),
        "video_id": "pRQn_EG-AEY",
        "title": "【20260717】彩券開獎｜三立新聞網 SETN.com",
        "duration_seconds": 3665,
        "subtitle_tracks": 0,
        "automatic_caption_tracks": 0,
        "scope_note": (
            "manual visual sample only; not a historical coverage claim"
        ),
    },
}

FIXED_OBSERVATION_INPUTS = (
    {
        "schema_version": "1",
        "game": LOTTO649,
        "period": 115000071,
        "draw_date": "2026-07-17",
        "registration_cutoff_at": "2026-07-17T20:00:00+08:00",
        "public_observed_at": "2026-07-17T20:32:39+08:00",
        "video_id": "pRQn_EG-AEY",
        "archive_url": (
            "https://d25vj0wbzayc6h.cloudfront.net/Live/3763/24003"
        ),
        "evidence_frame_timestamp": "00:35:00",
        "machine_id": "2",
        "ball_set_id": None,
        "loading_order": [],
        "anomaly_flags": [],
        "source_scope": "target_main_draw",
        "extraction_method": "manual_visual_verification",
        "extraction_confidence": 1.0,
        "human_verified": True,
    },
)

PROTOCOL_CONFIG = {
    "games": list(GAMES),
    "raw_sources": [
        "data/raw/super/*.json",
        "data/raw/lotto649/*.json",
    ],
    "physical_field_terms": {
        key: list(values)
        for key, values in PHYSICAL_FIELD_TERMS.items()
    },
    "observation_fields": list(OBSERVATION_FIELDS),
    "cutoff_rule": (
        "public_observed_at_must_be_at_or_before_"
        "registration_cutoff_at"
    ),
    "missing_or_naive_timestamp_policy": "fail_closed",
    "cross_game_or_special_scope_policy": "excluded",
    "future_model_minimum_periods_per_game": (
        MINIMUM_FUTURE_PERIODS_PER_GAME
    ),
    "future_model_minimum_machine_and_ball_set_completeness": (
        MINIMUM_FIELD_COMPLETENESS
    ),
    "future_model_requires_pre_cutoff_assignment": True,
    "historical_use": "availability_and_causality_audit_only",
    "number_probability_model": "not_fitted_in_this_experiment",
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
            raise ValueError("正式結果不得包含非有限浮點數")
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


def _normalize_field_name(value: str) -> str:
    return "".join(
        character.casefold()
        for character in str(value)
        if character.isalnum()
        or "\u4e00" <= character <= "\u9fff"
    )


def nested_key_paths(value, prefix: str = "") -> set[str]:
    """列出 JSON 物件的穩定 key paths；陣列索引固定表示為 []。"""
    paths: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            paths.add(path)
            paths.update(nested_key_paths(item, path))
    elif isinstance(value, list):
        array_path = f"{prefix}[]" if prefix else "[]"
        paths.add(array_path)
        for item in value:
            if isinstance(item, (dict, list)):
                paths.update(nested_key_paths(item, array_path))
    return paths


def match_physical_paths(paths) -> dict[str, list[str]]:
    """以凍結同義詞分類可能的實體設備欄位。"""
    if not isinstance(paths, (list, tuple, set)):
        raise ValueError("key paths 必須是序列")
    normalized_terms = {
        group: tuple(
            _normalize_field_name(term)
            for term in terms
        )
        for group, terms in PHYSICAL_FIELD_TERMS.items()
    }
    matches = {group: [] for group in PHYSICAL_FIELD_TERMS}
    for raw_path in paths:
        if not isinstance(raw_path, str) or not raw_path:
            raise ValueError("key path 不合法")
        path = _normalize_field_name(raw_path)
        for group, terms in normalized_terms.items():
            if any(term and term in path for term in terms):
                matches[group].append(raw_path)
    collapsed = {}
    for group, group_paths in matches.items():
        kept: list[str] = []
        for path in sorted(
            set(group_paths),
            key=lambda value: (value.count(".") + value.count("[]"), value),
        ):
            if any(
                path.startswith(parent + ".")
                or path.startswith(parent + "[]")
                for parent in kept
            ):
                continue
            kept.append(path)
        collapsed[group] = sorted(kept)
    return collapsed


def _parse_aware_timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} 缺少具時區時間")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{field} 不是 ISO 8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} 必須包含時區")
    return parsed


def _validate_frame_timestamp(value: object) -> None:
    if (
        not isinstance(value, str)
        or re.fullmatch(r"\d{2}:\d{2}:\d{2}", value) is None
    ):
        raise ValueError("evidence_frame_timestamp 不合法")
    hours, minutes, seconds = (int(part) for part in value.split(":"))
    if minutes >= 60 or seconds >= 60 or hours >= 100:
        raise ValueError("evidence_frame_timestamp 超出範圍")


def classify_observation(observation: dict) -> dict:
    """依原始欄位重算一筆 observation 的 ticket-time 資格。"""
    if (
        not isinstance(observation, dict)
        or set(observation) != set(OBSERVATION_INPUT_FIELDS)
    ):
        raise ValueError("實體 observation schema 不合法")
    if observation["schema_version"] != "1":
        raise ValueError("實體 observation 版本不合法")
    game = observation["game"]
    period = observation["period"]
    if (
        game not in GAMES
        or not isinstance(period, int)
        or isinstance(period, bool)
        or period <= 0
    ):
        raise ValueError("實體 observation game／period 不合法")
    try:
        draw_date = date.fromisoformat(observation["draw_date"])
    except (TypeError, ValueError) as error:
        raise ValueError("draw_date 不合法") from error
    cutoff = _parse_aware_timestamp(
        observation["registration_cutoff_at"],
        "registration_cutoff_at",
    )
    public = _parse_aware_timestamp(
        observation["public_observed_at"],
        "public_observed_at",
    )
    if cutoff.date() != draw_date or public.date() != draw_date:
        raise ValueError("observation 日期與目標期不一致")
    for field in ("video_id", "archive_url", "extraction_method"):
        if (
            not isinstance(observation[field], str)
            or not observation[field]
        ):
            raise ValueError(f"{field} 不合法")
    if not observation["archive_url"].startswith("https://"):
        raise ValueError("archive_url 必須使用 https")
    _validate_frame_timestamp(
        observation["evidence_frame_timestamp"]
    )
    for field in ("machine_id", "ball_set_id"):
        value = observation[field]
        if value is not None and (
            not isinstance(value, str) or not value.strip()
        ):
            raise ValueError(f"{field} 必須是非空字串或 null")
    if (
        not isinstance(observation["loading_order"], list)
        or not isinstance(observation["anomaly_flags"], list)
        or any(
            not isinstance(value, str) or not value
            for value in observation["anomaly_flags"]
        )
    ):
        raise ValueError("loading_order／anomaly_flags 不合法")
    scope = observation["source_scope"]
    confidence = observation["extraction_confidence"]
    if (
        scope not in ALLOWED_SOURCE_SCOPES
        or not isinstance(confidence, (int, float))
        or isinstance(confidence, bool)
        or not math.isfinite(confidence)
        or not 0 <= confidence <= 1
        or not isinstance(observation["human_verified"], bool)
    ):
        raise ValueError("scope／confidence／verification 不合法")

    if scope != "target_main_draw":
        reason = "source_scope_not_target_main_draw"
    elif public > cutoff:
        reason = "published_after_registration_cutoff"
    elif not observation["human_verified"]:
        reason = "not_human_verified"
    elif (
        observation["machine_id"] is None
        or observation["ball_set_id"] is None
    ):
        reason = "machine_or_ball_set_missing"
    else:
        reason = "eligible"
    result = dict(observation)
    result["eligible_for_forecast"] = reason == "eligible"
    result["eligibility_reason"] = reason
    return result


def _schema_profile(counter: Counter[tuple[str, ...]]) -> list[dict]:
    return [
        {
            "rows": count,
            "key_count": len(keys),
            "keys": list(keys),
        }
        for keys, count in sorted(
            counter.items(),
            key=lambda item: (-item[1], item[0]),
        )
    ]


def scan_raw_game(game: str, *, base: Path) -> dict:
    """完整掃描一款遊戲的官方 raw 月檔與所有 nested key paths。"""
    if game not in GAMES:
        raise ValueError("不支援的遊戲")
    raw_dir = Path(base) / "data" / "raw" / game
    files = sorted(raw_dir.glob("*.json"))
    if not files:
        raise RuntimeError(f"{game} 沒有官方 raw 月檔")

    result_key = RESULT_KEYS[game]
    root_schemas: Counter[tuple[str, ...]] = Counter()
    content_schemas: Counter[tuple[str, ...]] = Counter()
    row_schemas: Counter[tuple[str, ...]] = Counter()
    top_level_keys: set[str] = set()
    all_paths: set[str] = set()
    period_counts: Counter[int] = Counter()
    date_counts: Counter[str] = Counter()
    physical_rows = 0
    group_rows = Counter({group: 0 for group in PHYSICAL_FIELD_TERMS})
    failures: list[str] = []
    rows = 0
    nonempty_files = 0

    for path in files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as error:
            raise RuntimeError(
                f"{game} {path.name} JSON 無法解析"
            ) from error
        if not isinstance(payload, dict):
            failures.append(f"{path.name}:root_type")
            continue
        root_schemas[tuple(sorted(str(key) for key in payload))] += 1
        if (
            set(payload) != {"rtCode", "rtMsg", "content"}
            or payload.get("rtCode") != 0
            or not isinstance(payload.get("content"), dict)
        ):
            failures.append(f"{path.name}:root_schema")
            continue
        content = payload["content"]
        content_schemas[
            tuple(sorted(str(key) for key in content))
        ] += 1
        if (
            set(content) != {"totalSize", result_key}
            or not isinstance(content[result_key], list)
            or content["totalSize"] != len(content[result_key])
        ):
            failures.append(f"{path.name}:content_schema")
            continue
        month_rows = content[result_key]
        nonempty_files += int(bool(month_rows))
        for row in month_rows:
            if not isinstance(row, dict):
                failures.append(f"{path.name}:row_type")
                continue
            rows += 1
            keys = tuple(sorted(str(key) for key in row))
            row_schemas[keys] += 1
            top_level_keys.update(keys)
            paths = nested_key_paths(row)
            all_paths.update(paths)
            matches = match_physical_paths(paths)
            matched = False
            for group, group_paths in matches.items():
                if group_paths:
                    group_rows[group] += 1
                    matched = True
            physical_rows += int(matched)
            try:
                period = int(row["period"])
                draw_date = str(row["lotteryDate"])[:10]
                date.fromisoformat(draw_date)
            except (KeyError, TypeError, ValueError):
                failures.append(f"{path.name}:identity")
                continue
            period_counts[period] += 1
            date_counts[draw_date] += 1

    duplicate_periods = sum(
        count - 1 for count in period_counts.values() if count > 1
    )
    duplicate_dates = sum(
        count - 1 for count in date_counts.values() if count > 1
    )
    if (
        failures
        or rows == 0
        or duplicate_periods
        or duplicate_dates
        or len(period_counts) != rows
        or len(date_counts) != rows
    ):
        raise RuntimeError(
            f"{game} raw metadata schema 契約失敗："
            f"{(failures + [f'duplicate_periods:{duplicate_periods}', f'duplicate_dates:{duplicate_dates}'])[:5]}"
        )
    matches = match_physical_paths(all_paths)
    matched_paths = sorted(
        {
            path
            for group_paths in matches.values()
            for path in group_paths
        }
    )
    dates = sorted(date_counts)
    return {
        "status": "pass",
        "game": game,
        "game_name": GAME_NAMES[game],
        "files": len(files),
        "nonempty_files": nonempty_files,
        "empty_files": len(files) - nonempty_files,
        "rows": rows,
        "unique_periods": len(period_counts),
        "unique_dates": len(date_counts),
        "duplicate_periods": duplicate_periods,
        "duplicate_dates": duplicate_dates,
        "date_range": [dates[0], dates[-1]],
        "root_schema_profile": _schema_profile(root_schemas),
        "content_schema_profile": _schema_profile(content_schemas),
        "row_schema_profile": _schema_profile(row_schemas),
        "top_level_row_keys": sorted(top_level_keys),
        "nested_key_paths": sorted(all_paths),
        "physical_field_matches": matches,
        "physical_field_match_count": len(matched_paths),
        "physical_metadata_rows": physical_rows,
        "physical_metadata_coverage_rate": physical_rows / rows,
        "physical_group_rows": {
            group: group_rows[group]
            for group in PHYSICAL_FIELD_TERMS
        },
        "raw_tree_sha256": tree_sha256(raw_dir),
    }


def scan_raw_metadata(*, base: Path) -> dict:
    games = {
        game: scan_raw_game(game, base=base)
        for game in GAMES
    }
    raw_hashes = {
        game: games[game]["raw_tree_sha256"]
        for game in GAMES
    }
    return {
        "status": "pass",
        "games": games,
        "files_total": sum(row["files"] for row in games.values()),
        "nonempty_files_total": sum(
            row["nonempty_files"] for row in games.values()
        ),
        "empty_files_total": sum(
            row["empty_files"] for row in games.values()
        ),
        "rows_total": sum(row["rows"] for row in games.values()),
        "physical_metadata_rows_total": sum(
            row["physical_metadata_rows"]
            for row in games.values()
        ),
        "physical_metadata_coverage_rate": (
            sum(
                row["physical_metadata_rows"]
                for row in games.values()
            )
            / sum(row["rows"] for row in games.values())
        ),
        "raw_snapshot_hashes": raw_hashes,
        "combined_raw_snapshot_hash": canonical_hash(raw_hashes),
    }


def build_observation_audit(
    observations: list[dict],
    raw_audit: dict,
) -> dict:
    classified = [
        classify_observation(observation)
        for observation in observations
    ]
    by_game = {}
    for game in GAMES:
        rows = [row for row in classified if row["game"] == game]
        raw_periods = raw_audit["games"][game]["rows"]
        machine = sum(row["machine_id"] is not None for row in rows)
        ball_set = sum(row["ball_set_id"] is not None for row in rows)
        eligible = sum(row["eligible_for_forecast"] for row in rows)
        by_game[game] = {
            "game": game,
            "historical_periods": raw_periods,
            "observations": len(rows),
            "unique_periods": len({row["period"] for row in rows}),
            "period_coverage_rate": (
                len({row["period"] for row in rows}) / raw_periods
            ),
            "machine_id_observations": machine,
            "machine_id_completeness": (
                machine / len(rows) if rows else 0.0
            ),
            "ball_set_id_observations": ball_set,
            "ball_set_id_completeness": (
                ball_set / len(rows) if rows else 0.0
            ),
            "pre_cutoff_eligible_observations": eligible,
            "pre_cutoff_eligibility_rate": (
                eligible / len(rows) if rows else 0.0
            ),
        }
    duplicate_keys = len(classified) - len(
        {(row["game"], row["period"]) for row in classified}
    )
    if duplicate_keys:
        raise ValueError("實體 observation 有重複 game／period")
    return {
        "status": "pass",
        "observations": classified,
        "observation_hash": canonical_hash(classified),
        "total_observations": len(classified),
        "unique_game_periods": len(classified),
        "duplicate_game_periods": duplicate_keys,
        "excluded_scope_observations": sum(
            row["source_scope"] != "target_main_draw"
            for row in classified
        ),
        "machine_id_observations": sum(
            row["machine_id"] is not None for row in classified
        ),
        "ball_set_id_observations": sum(
            row["ball_set_id"] is not None for row in classified
        ),
        "pre_cutoff_eligible_observations": sum(
            row["eligible_for_forecast"] for row in classified
        ),
        "games": by_game,
    }


def build_conclusion(
    raw_audit: dict,
    observation_audit: dict,
) -> dict:
    no_raw_fields = (
        raw_audit["physical_metadata_rows_total"] == 0
        and raw_audit["physical_metadata_coverage_rate"] == 0
    )
    no_pre_cutoff_assignment = (
        observation_audit["pre_cutoff_eligible_observations"] == 0
    )
    future_thresholds = {
        game: {
            "minimum_periods_met": (
                observation_audit["games"][game][
                    "pre_cutoff_eligible_observations"
                ]
                >= MINIMUM_FUTURE_PERIODS_PER_GAME
            ),
            "machine_completeness_met": (
                observation_audit["games"][game][
                    "machine_id_completeness"
                ]
                >= MINIMUM_FIELD_COMPLETENESS
            ),
            "ball_set_completeness_met": (
                observation_audit["games"][game][
                    "ball_set_id_completeness"
                ]
                >= MINIMUM_FIELD_COMPLETENESS
            ),
        }
        for game in GAMES
    }
    future_model_ready = all(
        all(checks.values())
        for checks in future_thresholds.values()
    )
    blocked = no_raw_fields and no_pre_cutoff_assignment
    return {
        "status": (
            "physical_metadata_unavailable_pre_cutoff"
            if blocked
            else "physical_metadata_requires_new_protocol"
        ),
        "official_raw_physical_fields_absent": no_raw_fields,
        "pre_cutoff_assignment_absent": no_pre_cutoff_assignment,
        "future_model_thresholds": future_thresholds,
        "future_model_ready": future_model_ready,
        "number_probability_model_allowed": False,
        "historical_promotion_eligible": False,
        "watcher_integration_allowed": False,
        "number_changes_allowed": False,
        "future_diagnostic_collection_allowed": True,
        "selected_probability_protocol": "uniform_null_safe",
        "decision_basis": [
            (
                "official historical result data contains no machine, "
                "ball-set, loading-order, or anomaly field"
            ),
            (
                "the audited main-draw machine label became public "
                "after the registration cutoff"
            ),
            (
                "the one visual sample has no reliable main-draw "
                "ball-set identifier"
            ),
        ],
    }


def run_physical_metadata_audit(*, base: Path) -> dict:
    base = Path(base)
    protocol_path = base / PROTOCOL_FILE
    if not protocol_path.exists():
        raise RuntimeError(f"缺少凍結 protocol：{protocol_path}")
    records_before = tree_sha256(base / "records")
    raw_audit = scan_raw_metadata(base=base)
    observation_audit = build_observation_audit(
        [dict(row) for row in FIXED_OBSERVATION_INPUTS],
        raw_audit,
    )
    records_after = tree_sha256(base / "records")
    result = {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": EXPERIMENT_ID,
        "generated_at": GENERATED_AT,
        "question": (
            "Can public physical draw metadata be known before the "
            "registration cutoff and legally improve next-draw subset "
            "probabilities?"
        ),
        "protocol": {
            **PROTOCOL_CONFIG,
            "protocol_hash": PROTOCOL_HASH,
            "protocol_file": PROTOCOL_FILE,
            "protocol_file_sha256": _file_sha256(protocol_path),
        },
        "source_evidence": {
            **SOURCE_EVIDENCE,
            "evidence_hash": canonical_hash(SOURCE_EVIDENCE),
        },
        "raw_schema_audit": raw_audit,
        "observation_audit": observation_audit,
        "future_collection_schema": {
            "fields": list(OBSERVATION_FIELDS),
            "eligibility_is_derived": True,
            "eligibility_function": (
                "public_observed_at <= registration_cutoff_at AND "
                "target_main_draw AND human_verified AND "
                "machine_id_present AND ball_set_id_present"
            ),
            "missing_value_policy": "fail_closed",
        },
        "conclusion": build_conclusion(
            raw_audit,
            observation_audit,
        ),
        "records_integrity": {
            "before_sha256": records_before,
            "after_sha256": records_after,
            "unchanged": records_before == records_after,
        },
        "limitations": [
            (
                "Only one broadcast period was manually verified; it "
                "is evidence of availability timing, not history coverage."
            ),
            (
                "External source pages are cited and protocol-frozen, "
                "but their HTML and video are not copied into the repo."
            ),
            (
                "An internal recording timestamp does not prove public "
                "pre-cutoff availability."
            ),
            (
                "Post-cutoff equipment observations may support mechanism "
                "diagnostics but cannot select tickets for that draw."
            ),
            (
                "This is a simulation and not purchase or betting advice."
            ),
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
        "source_evidence",
        "raw_schema_audit",
        "observation_audit",
        "future_collection_schema",
        "conclusion",
        "records_integrity",
        "limitations",
        "audit_hash",
    }
    if (
        not isinstance(result, dict)
        or set(result) != expected_keys
        or result.get("schema_version") != SCHEMA_VERSION
        or result.get("experiment_id") != EXPERIMENT_ID
        or result.get("generated_at") != GENERATED_AT
    ):
        raise ValueError("實體 metadata artifact schema 不合法")

    protocol = result["protocol"]
    for key, value in PROTOCOL_CONFIG.items():
        if protocol.get(key) != value:
            raise ValueError(f"實體 metadata protocol 不符：{key}")
    if (
        protocol.get("protocol_hash") != PROTOCOL_HASH
        or protocol.get("protocol_file") != PROTOCOL_FILE
        or not _is_sha256(protocol.get("protocol_file_sha256"))
    ):
        raise ValueError("實體 metadata protocol hash 不合法")

    evidence = result["source_evidence"]
    evidence_payload = dict(evidence)
    evidence_hash = evidence_payload.pop("evidence_hash", None)
    if (
        evidence_payload != SOURCE_EVIDENCE
        or evidence_hash != canonical_hash(SOURCE_EVIDENCE)
    ):
        raise ValueError("實體 metadata 外部來源證據不一致")

    raw = result["raw_schema_audit"]
    games = raw.get("games", {})
    if (
        raw.get("status") != "pass"
        or set(games) != set(GAMES)
        or raw.get("files_total")
        != sum(games[game].get("files", -1) for game in GAMES)
        or raw.get("nonempty_files_total")
        != sum(
            games[game].get("nonempty_files", -1)
            for game in GAMES
        )
        or raw.get("empty_files_total")
        != sum(games[game].get("empty_files", -1) for game in GAMES)
        or raw.get("rows_total")
        != sum(games[game].get("rows", -1) for game in GAMES)
        or raw.get("physical_metadata_rows_total")
        != sum(
            games[game].get("physical_metadata_rows", -1)
            for game in GAMES
        )
        or set(raw.get("raw_snapshot_hashes", {})) != set(GAMES)
        or not _is_sha256(raw.get("combined_raw_snapshot_hash"))
    ):
        raise ValueError("實體 metadata raw 摘要不合法")
    expected_raw_hashes = {
        game: games[game]["raw_tree_sha256"]
        for game in GAMES
    }
    if (
        raw["raw_snapshot_hashes"] != expected_raw_hashes
        or raw["combined_raw_snapshot_hash"]
        != canonical_hash(expected_raw_hashes)
    ):
        raise ValueError("實體 metadata raw hash 不一致")
    expected_total_coverage = (
        raw["physical_metadata_rows_total"] / raw["rows_total"]
    )
    if (
        raw["physical_metadata_coverage_rate"]
        != _stable_floats(expected_total_coverage)
    ):
        raise ValueError("實體 metadata raw 覆蓋率不一致")
    for game in GAMES:
        row = games[game]
        required_row_keys = {
            "status",
            "game",
            "game_name",
            "files",
            "nonempty_files",
            "empty_files",
            "rows",
            "unique_periods",
            "unique_dates",
            "duplicate_periods",
            "duplicate_dates",
            "date_range",
            "root_schema_profile",
            "content_schema_profile",
            "row_schema_profile",
            "top_level_row_keys",
            "nested_key_paths",
            "physical_field_matches",
            "physical_field_match_count",
            "physical_metadata_rows",
            "physical_metadata_coverage_rate",
            "physical_group_rows",
            "raw_tree_sha256",
        }
        if (
            set(row) != required_row_keys
            or row.get("status") != "pass"
            or row.get("game") != game
            or row.get("game_name") != GAME_NAMES[game]
            or row.get("rows") != row.get("unique_periods")
            or row.get("rows") != row.get("unique_dates")
            or row.get("duplicate_periods") != 0
            or row.get("duplicate_dates") != 0
            or row.get("files")
            != row.get("nonempty_files") + row.get("empty_files")
            or not _is_sha256(row.get("raw_tree_sha256"))
            or set(row.get("physical_field_matches", {}))
            != set(PHYSICAL_FIELD_TERMS)
            or set(row.get("physical_group_rows", {}))
            != set(PHYSICAL_FIELD_TERMS)
        ):
            raise ValueError(f"{game} 實體 metadata raw profile 不合法")
        flat_matches = {
            path
            for group_paths in row["physical_field_matches"].values()
            for path in group_paths
        }
        if (
            row["physical_field_match_count"] != len(flat_matches)
            or row["physical_metadata_coverage_rate"]
            != _stable_floats(
                row["physical_metadata_rows"] / row["rows"]
            )
        ):
            raise ValueError(f"{game} 實體 metadata 衍生欄位不一致")

    observation = result["observation_audit"]
    observations = observation.get("observations", [])
    if (
        observation.get("status") != "pass"
        or not isinstance(observations, list)
        or set(observation.get("games", {})) != set(GAMES)
        or observation.get("total_observations") != len(observations)
        or observation.get("unique_game_periods") != len(observations)
        or observation.get("duplicate_game_periods") != 0
        or observation.get("observation_hash")
        != canonical_hash(observations)
    ):
        raise ValueError("實體 observation 摘要不合法")
    for observed in observations:
        if (
            set(observed) != set(OBSERVATION_FIELDS)
            or classify_observation(
                {
                    key: observed[key]
                    for key in OBSERVATION_INPUT_FIELDS
                }
            )
            != observed
        ):
            raise ValueError("實體 observation 資格被竄改")
    expected_machine = sum(
        row["machine_id"] is not None for row in observations
    )
    expected_ball = sum(
        row["ball_set_id"] is not None for row in observations
    )
    expected_eligible = sum(
        row["eligible_for_forecast"] for row in observations
    )
    expected_excluded = sum(
        row["source_scope"] != "target_main_draw"
        for row in observations
    )
    if (
        observation["machine_id_observations"] != expected_machine
        or observation["ball_set_id_observations"] != expected_ball
        or observation["pre_cutoff_eligible_observations"]
        != expected_eligible
        or observation["excluded_scope_observations"]
        != expected_excluded
    ):
        raise ValueError("實體 observation 計數不一致")
    for game in GAMES:
        profile = observation["games"][game]
        rows = [row for row in observations if row["game"] == game]
        raw_periods = games[game]["rows"]
        unique = len({row["period"] for row in rows})
        machine = sum(row["machine_id"] is not None for row in rows)
        ball = sum(row["ball_set_id"] is not None for row in rows)
        eligible = sum(row["eligible_for_forecast"] for row in rows)
        expected_profile = {
            "game": game,
            "historical_periods": raw_periods,
            "observations": len(rows),
            "unique_periods": unique,
            "period_coverage_rate": _stable_floats(
                unique / raw_periods
            ),
            "machine_id_observations": machine,
            "machine_id_completeness": _stable_floats(
                machine / len(rows) if rows else 0.0
            ),
            "ball_set_id_observations": ball,
            "ball_set_id_completeness": _stable_floats(
                ball / len(rows) if rows else 0.0
            ),
            "pre_cutoff_eligible_observations": eligible,
            "pre_cutoff_eligibility_rate": _stable_floats(
                eligible / len(rows) if rows else 0.0
            ),
        }
        if profile != expected_profile:
            raise ValueError(f"{game} observation 覆蓋率不一致")

    schema = result["future_collection_schema"]
    if (
        schema.get("fields") != list(OBSERVATION_FIELDS)
        or schema.get("eligibility_is_derived") is not True
        or schema.get("missing_value_policy") != "fail_closed"
    ):
        raise ValueError("未來 observation schema 不合法")
    expected_conclusion = build_conclusion(raw, observation)
    if result["conclusion"] != expected_conclusion:
        raise ValueError("實體 metadata 結論不一致")
    integrity = result["records_integrity"]
    if (
        set(integrity)
        != {"before_sha256", "after_sha256", "unchanged"}
        or not _is_sha256(integrity.get("before_sha256"))
        or not _is_sha256(integrity.get("after_sha256"))
        or integrity.get("unchanged")
        is not (
            integrity.get("before_sha256")
            == integrity.get("after_sha256")
        )
        or integrity.get("unchanged") is not True
    ):
        raise ValueError("實體 metadata records 完整性失敗")
    if (
        not isinstance(result.get("limitations"), list)
        or len(result["limitations"]) < 4
        or not _is_sha256(result.get("audit_hash"))
    ):
        raise ValueError("實體 metadata 限制或 audit hash 不合法")
    payload = dict(result)
    observed_hash = payload.pop("audit_hash")
    if observed_hash != canonical_hash(payload):
        raise ValueError("實體 metadata audit hash 不一致")
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
