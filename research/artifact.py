"""把歷史策略研究輸出整理成 Data Analytics 報告 artifact。

輸出只是一份可驗證的 manifest/snapshot JSON；實際桌面報告仍由
Data Analytics artifact reader 驗證與呈現。
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import date
from pathlib import Path

from engine.games import GAME_NAMES
from engine.picker import GAMES


POLICY_LABELS = {
    "random_5": "五注純隨機",
    "current_ensemble": "現行五人格",
    "trained_family_ensemble": "訓練家族組合",
    "trained_best_5": "訓練冠軍五注",
    "trained_blend": "訓練混合",
}


def _load_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _number(row: dict, field: str) -> float:
    return float(row[field])


def _build_policy_rows(summary_rows: list[dict]) -> list[dict]:
    output = []
    order = {
        policy_id: index
        for index, policy_id in enumerate(POLICY_LABELS)
    }
    for row in summary_rows:
        if row["stage"] != "final_policy" or row["split"] != "holdout":
            continue
        output.append(
            {
                "game": row["game"],
                "game_name": row["game_name"],
                "policy_id": row["policy_id"],
                "policy_label": POLICY_LABELS[row["policy_id"]],
                "policy_order": order[row["policy_id"]],
                "weeks": int(row["weeks"]),
                "draws": int(row["draws"]),
                "replicates": int(row["replicates"]),
                "raw_roi": _number(row, "raw_roi_mean"),
                "robust_roi": _number(row, "robust_roi_mean"),
                "delta_robust_roi": _number(row, "delta_robust_roi_mean"),
                "delta_ci_low": _number(row, "delta_ci_low"),
                "delta_ci_high": _number(row, "delta_ci_high"),
                "delta_fixed_roi": _number(row, "delta_fixed_roi_mean"),
                "active_week_win_rate": _number(row, "active_week_win_rate"),
                "positive_replicate_rate": _number(
                    row, "positive_replicate_rate"
                ),
            }
        )
    return sorted(output, key=lambda row: (row["policy_order"], row["game"]))


def _build_decision_rows(study: dict) -> list[dict]:
    rows = []
    for game in GAMES:
        selected = study["selected"][game]
        holdout = selected["holdout"]
        rows.append(
            {
                "game": game,
                "game_name": GAME_NAMES[game],
                "selected_policy": selected["policy_id"],
                "selected_policy_label": POLICY_LABELS[selected["policy_id"]],
                "holdout_weeks": holdout["weeks"],
                "holdout_draws": holdout["draws"],
                "raw_roi": holdout["raw_roi_mean"],
                "delta_robust_roi": holdout["delta_robust_roi_mean"],
                "delta_ci_low": holdout["delta_ci_low"],
                "delta_ci_high": holdout["delta_ci_high"],
                "delta_fixed_roi": holdout["delta_fixed_roi_mean"],
                "active_week_win_rate": holdout["active_week_win_rate"],
                "positive_replicate_rate": holdout["positive_replicate_rate"],
                "edge_proven": (
                    "已證明" if selected["edge_proven"] else "未證明"
                ),
                "conditional_decision": selected["conditional_decision"],
                "conditional_decision_label": POLICY_LABELS[
                    selected["conditional_decision"]
                ],
            }
        )
    return rows


def _build_cumulative_rows(study: dict, weekly_rows: list[dict]) -> list[dict]:
    selected_ids = {
        game: study["selected"][game]["policy_id"] for game in GAMES
    }
    filtered = []
    for row in weekly_rows:
        if row["split"] != "holdout":
            continue
        selected = selected_ids[row["game"]]
        if row["policy_id"] not in {"random_5", selected}:
            continue
        filtered.append(row)

    by_series: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in filtered:
        by_series[(row["game"], row["policy_id"])].append(row)
    output = []
    for (game, policy_id), rows in sorted(by_series.items()):
        cumulative_cost = cumulative_prize = cumulative_robust = 0.0
        ordered_rows = sorted(rows, key=lambda item: item["week"])
        for index, row in enumerate(ordered_rows):
            cumulative_cost += float(row["cost_mean"])
            cumulative_prize += float(row["raw_prize_mean"])
            cumulative_robust += float(row["robust_prize_mean"])
            # 報告只保留約每半年一點與最後一點；計算本身仍累積所有週。
            if index % 26 != 0 and index != len(ordered_rows) - 1:
                continue
            is_baseline = policy_id == "random_5"
            year, week_number = row["week"].split("-W")
            output.append(
                {
                    "game": game,
                    "game_name": GAME_NAMES[game],
                    "week": row["week"],
                    "week_start": date.fromisocalendar(
                        int(year), int(week_number), 1
                    ).isoformat(),
                    "policy_id": policy_id,
                    "policy_label": POLICY_LABELS[policy_id],
                    "series": (
                        f"{GAME_NAMES[game]}｜{POLICY_LABELS[policy_id]}"
                    ),
                    "line_style": "dashed" if is_baseline else "solid",
                    "role": "baseline" if is_baseline else "selected",
                    "draws": int(row["draws"]),
                    "cumulative_cost": cumulative_cost,
                    "cumulative_prize": cumulative_prize,
                    "cumulative_robust_prize": cumulative_robust,
                    "cumulative_roi": cumulative_prize / cumulative_cost - 1,
                    "cumulative_robust_roi": (
                        cumulative_robust / cumulative_cost - 1
                    ),
                }
            )
    return output


def build_artifact(results_dir: Path) -> dict:
    study = json.loads(
        (results_dir / "strategy_research.json").read_text(encoding="utf-8")
    )
    summary_rows = _load_csv(results_dir / "strategy_summary.csv")
    policy_rows = _build_policy_rows(summary_rows)
    decision_rows = _build_decision_rows(study)

    selected_summary = []
    for row in decision_rows:
        selected_summary.append(
            f"**{row['game_name']}**：驗證集選到{row['selected_policy_label']}，"
            f"holdout 相對隨機為 {row['delta_robust_roi']:+.2%}，"
            f"95% 區間 [{row['delta_ci_low']:+.2%}, "
            f"{row['delta_ci_high']:+.2%}]，因此外驗優勢{row['edge_proven']}。"
        )
    selected_filter = " OR ".join(
        (
            f"(game = '{game}' AND "
            f"policy_id = '{result['policy_id']}')"
        )
        for game, result in study["selected"].items()
    )
    policy_label_sql = (
        "CASE policy_id "
        "WHEN 'random_5' THEN '五注純隨機' "
        "WHEN 'current_ensemble' THEN '現行五人格' "
        "WHEN 'trained_family_ensemble' THEN '訓練家族組合' "
        "WHEN 'trained_best_5' THEN '訓練冠軍五注' "
        "WHEN 'trained_blend' THEN '訓練混合' END"
    )
    edge_gate_sql = (
        "delta_ci_low > 0 AND delta_fixed_roi_mean >= 0 "
        "AND positive_replicate_rate >= 0.75 "
        "AND active_week_win_rate > 0.5"
    )

    metric_definitions = [
        "原始 ROI = 全獎級虛擬獎金 / 模擬成本 - 1",
        "穩健 ROI = 排除頭獎與貳獎後獎金 / 模擬成本 - 1",
        "相對隨機穩健 ROI 差 = 政策穩健獎金與同週 random_5 穩健獎金之差 / 成本",
        "95% 區間 = 13 週區塊 bootstrap 1,000 次",
    ]
    source_study = {
        "id": "strategy-study",
        "label": "Holdout 政策比較",
        "path": "research/results/strategy_summary.csv",
        "query": {
            "engine": "duckdb",
            "language": "sql",
            "sql": (
                "SELECT game, game_name, policy_id,\n"
                "  CASE policy_id\n"
                "    WHEN 'random_5' THEN '五注純隨機'\n"
                "    WHEN 'current_ensemble' THEN '現行五人格'\n"
                "    WHEN 'trained_family_ensemble' THEN '訓練家族組合'\n"
                "    WHEN 'trained_best_5' THEN '訓練冠軍五注'\n"
                "    WHEN 'trained_blend' THEN '訓練混合' END AS policy_label,\n"
                "  CASE policy_id\n"
                "    WHEN 'random_5' THEN 0 WHEN 'current_ensemble' THEN 1\n"
                "    WHEN 'trained_family_ensemble' THEN 2\n"
                "    WHEN 'trained_best_5' THEN 3 ELSE 4 END AS policy_order,\n"
                "  weeks, draws, replicates, raw_roi_mean AS raw_roi,\n"
                "  robust_roi_mean AS robust_roi,\n"
                "  delta_robust_roi_mean AS delta_robust_roi,\n"
                "  delta_ci_low, delta_ci_high,\n"
                "  delta_fixed_roi_mean AS delta_fixed_roi,\n"
                "  active_week_win_rate, positive_replicate_rate\n"
                "FROM read_csv_auto('research/results/strategy_summary.csv')\n"
                "WHERE stage = 'final_policy' AND split = 'holdout'\n"
                "ORDER BY policy_order, game"
            ),
            "description": (
                "讀取走步回測輸出，整理五個最終政策在 sealed holdout "
                "的配對比較。"
            ),
            "tables_used": ["research/results/strategy_summary.csv"],
            "filters": [
                "stage = final_policy",
                "split = holdout",
            ],
            "metric_definitions": metric_definitions,
        },
    }
    source_decision = {
        "id": "decision-study",
        "label": "封存測試決策",
        "path": "research/results/strategy_summary.csv",
        "query": {
            "engine": "duckdb",
            "language": "sql",
            "sql": (
                "SELECT game, game_name, policy_id AS selected_policy,\n"
                f"  {policy_label_sql} AS selected_policy_label,\n"
                "  weeks AS holdout_weeks, draws AS holdout_draws,\n"
                "  raw_roi_mean AS raw_roi,\n"
                "  delta_robust_roi_mean AS delta_robust_roi,\n"
                "  delta_ci_low, delta_ci_high,\n"
                "  delta_fixed_roi_mean AS delta_fixed_roi,\n"
                "  active_week_win_rate, positive_replicate_rate,\n"
                f"  CASE WHEN {edge_gate_sql} THEN '已證明' "
                "ELSE '未證明' END AS edge_proven,\n"
                f"  CASE WHEN {edge_gate_sql} THEN policy_id "
                "ELSE 'random_5' END AS conditional_decision,\n"
                f"  CASE WHEN {edge_gate_sql} THEN {policy_label_sql} "
                "ELSE '五注純隨機' END AS conditional_decision_label\n"
                "FROM read_csv_auto('research/results/strategy_summary.csv')\n"
                "WHERE stage = 'final_policy' AND split = 'holdout'\n"
                f"  AND ({selected_filter})\n"
                "ORDER BY game_name"
            ),
            "description": "讀取 validation 選定政策的一次性 holdout 外驗結果。",
            "tables_used": ["research/results/strategy_summary.csv"],
            "filters": [
                "stage = final_policy",
                "split = holdout",
                "各遊戲 policy_id = 本次 validation 選擇",
            ],
            "metric_definitions": metric_definitions,
        },
    }
    title = "台彩策略歷史外驗決策"
    manifest = {
        "version": 1,
        "surface": "report",
        "title": title,
        "description": "全歷史走步回測、兩階段調參與封存測試集決策。",
        "generatedAt": study["generated_at"],
        "sources": [source_study, source_decision],
        "blocks": [
            {
                "id": "report-title",
                "type": "markdown",
                "body": f"# {title}",
                "layout": "full",
            },
            {
                "id": "executive-summary",
                "type": "markdown",
                "body": (
                    "## Executive Summary\n\n"
                    "- **最佳經濟決策是不參與。** 所有合法號碼組合等機率，"
                    "任何購票政策都有正成本；回測沒有改變這個前提。\n"
                    "- **兩款遊戲都未證明策略優於純隨機。** "
                    + " ".join(selected_summary)
                    + "\n"
                    "- **條件式模擬維持五注純隨機。** 訓練冠軍與現行五人格"
                    "可以作研究對照，但不得升格為可用優勢。"
                ),
                "layout": "full",
                "sourceId": "strategy-study",
            },
            {
                "id": "holdout-finding",
                "type": "markdown",
                "body": (
                    "## 封存測試沒有留下可重複優勢\n\n"
                    "下圖比較所有最終政策在 holdout 的相對隨機穩健 ROI。"
                    "0 代表和五注純隨機相同；正值只有在區間、一致性與固定獎級"
                    "護欄同時通過時才可採用。結果顯示驗證集第一名沒有在未見資料"
                    "形成可信且穩定的正差。"
                ),
                "layout": "full",
                "sourceId": "strategy-study",
            },
            {
                "id": "holdout-policy-chart-block",
                "type": "chart",
                "chartId": "holdout-policy-chart",
                "layout": "full",
            },
            {
                "id": "economics-finding",
                "type": "markdown",
                "body": (
                    "## 負期望值仍然主導經濟結果\n\n"
                    "決策表中的 holdout 原始 ROI 全為負；個別策略即使短暫"
                    "領先隨機，也沒有形成可信且持續的正差。這表示歷史排名"
                    "主要是抽樣噪音，不應用加碼或追隨權重來回應。"
                ),
                "layout": "full",
                "sourceId": "strategy-study",
            },
            {
                "id": "decision-detail",
                "type": "markdown",
                "body": (
                    "## 決策門檻與最終狀態\n\n"
                    "決策表保留驗證集選擇、封存測試區間、固定獎級敏感度與"
                    "一致性。任一門檻失敗，條件式政策就回到純隨機。"
                ),
                "layout": "full",
                "sourceId": "strategy-study",
            },
            {
                "id": "decision-table-block",
                "type": "table",
                "tableId": "decision-table",
                "layout": "full",
            },
            {
                "id": "recommended-actions",
                "type": "markdown",
                "body": (
                    "## 建議下一步\n\n"
                    "1. 保留 v1 與 W30 凍結票，不用歷史回測結果改寫正式帳本。\n"
                    "2. 經濟決策維持不參與；條件式研究維持 `random_5`。\n"
                    "3. 將這次 holdout 永久封存。若要研究新特徵，建立新的研究"
                    "版本與新的未見資料，不得再拿同一 holdout 調參。\n"
                    "4. 每週正式流程只做預註冊、結算與資料品質監控。"
                ),
                "layout": "full",
            },
            {
                "id": "further-questions",
                "type": "markdown",
                "body": (
                    "## Further Questions\n\n"
                    "- 若未來取得可靠的玩家選號分布，反熱門策略可否只改善"
                    "中獎後的分彩，而非命中率？\n"
                    "- 新研究版本要累積多少真正未見週，才足以重新檢驗目前的"
                    "無優勢結論？"
                ),
                "layout": "full",
            },
            {
                "id": "caveats",
                "type": "markdown",
                "body": (
                    "## Caveats and Assumptions\n\n"
                    "- 這是純模擬，不含真實下注、稅、交易摩擦或個人效用。\n"
                    "- 浮動獎級採當時可得歷史的保守估值；主要選擇指標排除"
                    "頭獎與貳獎，並另看固定獎級敏感度。\n"
                    "- 大樂透春節加開期按實際開獎數與成本納入。\n"
                    "- 參數搜尋會製造訓練集冠軍，因此只有 validation 與一次性"
                    "holdout 能支撐決策。"
                ),
                "layout": "full",
            },
        ],
        "charts": [
            {
                "id": "holdout-policy-chart",
                "title": "Holdout 相對隨機穩健 ROI",
                "subtitle": "五種政策、兩款遊戲；0 代表與五注純隨機相同",
                "intent": "comparison",
                "type": "bar",
                "dataset": "policy_holdout",
                "sourceId": "strategy-study",
                "source": source_study,
                "encodings": {
                    "x": {
                        "field": "policy_label",
                        "type": "nominal",
                        "label": "政策",
                    },
                    "y": {
                        "field": "delta_robust_roi",
                        "type": "quantitative",
                        "format": "percent",
                        "label": "相對隨機穩健 ROI 差",
                    },
                    "color": {
                        "field": "game_name",
                        "type": "nominal",
                        "label": "遊戲",
                    },
                    "tooltip": [
                        {"field": "raw_roi", "format": "percent"},
                        {"field": "delta_ci_low", "format": "percent"},
                        {"field": "delta_ci_high", "format": "percent"},
                        {"field": "delta_fixed_roi", "format": "percent"},
                        {"field": "weeks", "format": "number"},
                    ],
                },
                "valueFormat": "percent",
                "layout": "full",
                "palette": {"kind": "categorical"},
                "settings": {
                    "orientation": "vertical",
                    "groupMode": "grouped",
                    "showValues": True,
                    "sort": "custom",
                },
                "legend": {"position": "bottom", "title": "遊戲"},
                "referenceLines": [
                    {
                        "axis": "y",
                        "value": 0,
                        "label": "純隨機基準",
                        "lineStyle": "dashed",
                        "color": "neutral",
                    }
                ],
                "surface": {"viewMode": "both", "showControls": True},
            },
        ],
        "tables": [
            {
                "id": "decision-table",
                "title": "封存測試決策表",
                "subtitle": "每款遊戲的 validation 選擇與 holdout 外驗",
                "dataset": "decision_rows",
                "sourceId": "decision-study",
                "source": source_decision,
                "layout": "full",
                "density": "spacious",
                "defaultSort": {"field": "game_name", "direction": "asc"},
                "columns": [
                    {"field": "game_name", "label": "遊戲", "type": "text"},
                    {
                        "field": "selected_policy_label",
                        "label": "驗證集選定政策",
                        "type": "text",
                    },
                    {
                        "field": "raw_roi",
                        "label": "Holdout 原始 ROI",
                        "format": "percent",
                    },
                    {
                        "field": "delta_robust_roi",
                        "label": "相對隨機穩健差",
                        "format": "percent",
                        "movement": True,
                    },
                    {
                        "field": "delta_ci_low",
                        "label": "95% 下界",
                        "format": "percent",
                    },
                    {
                        "field": "delta_ci_high",
                        "label": "95% 上界",
                        "format": "percent",
                    },
                    {
                        "field": "delta_fixed_roi",
                        "label": "固定獎級差",
                        "format": "percent",
                    },
                    {
                        "field": "edge_proven",
                        "label": "外驗優勢",
                        "type": "text",
                    },
                    {
                        "field": "conditional_decision_label",
                        "label": "條件式決策",
                        "type": "text",
                    },
                ],
            }
        ],
    }
    snapshot = {
        "version": 1,
        "generatedAt": study["generated_at"],
        "status": "ready",
        "datasets": {
            "policy_holdout": policy_rows,
            "decision_rows": decision_rows,
        },
    }
    return {
        "surface": "report",
        "manifest": manifest,
        "snapshot": snapshot,
    }


def write_artifact(results_dir: Path) -> Path:
    artifact = build_artifact(results_dir)
    output = results_dir / "artifact.json"
    output.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return output
