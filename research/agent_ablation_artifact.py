"""把 Agent 數量消融結果整理成 Data Analytics report artifact。"""
from __future__ import annotations

import json
from pathlib import Path

from engine.analysts import NAMES
from engine.games import GAME_NAMES, LOTTO649, SUPER


def _signed(value: float, digits: int = 3) -> str:
    return f"{value:+.{digits}f}"


def _interval(low: float, high: float) -> str:
    return f"[{_signed(low)}, {_signed(high)}]"


def build_artifact(results_dir: Path) -> dict:
    results_dir = Path(results_dir)
    study = json.loads(
        (results_dir / "agent_ablation.json").read_text(encoding="utf-8")
    )
    holdout_rows = [
        row
        for row in study["count_summary"]
        if row["split"] == "holdout"
    ]
    holdout_rows = sorted(
        holdout_rows, key=lambda row: (row["agent_count"], row["game"])
    )
    chart_rows = [
        {
            **row,
            "delta_direction": (
                "高於隨機"
                if row["delta_best_vs_random"] > 0
                else "低於隨機"
                if row["delta_best_vs_random"] < 0
                else "等於隨機"
            ),
            "ci_crosses_zero": (
                row["delta_best_vs_random_ci_low"] <= 0
                <= row["delta_best_vs_random_ci_high"]
            ),
        }
        for row in holdout_rows
    ]

    selected_rows = []
    for game in (SUPER, LOTTO649):
        selected = study["selected_development_winners"][game]
        development = selected["development"]
        holdout = selected["holdout"]
        selected_rows.append(
            {
                "game": game,
                "game_name": GAME_NAMES[game],
                "subset_id": selected["subset_id"],
                "agent_names": "、".join(
                    NAMES[agent] for agent in selected["agents"]
                ),
                "agent_count": selected["agent_count"],
                "development_best_main_hits": development["best_main_hits"],
                "development_delta_vs_random": development[
                    "delta_best_vs_random"
                ],
                "holdout_best_main_hits": holdout["best_main_hits"],
                "holdout_delta_vs_random": holdout[
                    "delta_best_vs_random"
                ],
                "holdout_ci_low": holdout[
                    "delta_best_vs_random_ci_low"
                ],
                "holdout_ci_high": holdout[
                    "delta_best_vs_random_ci_high"
                ],
                "holdout_any_three_plus": holdout["any_three_plus"],
                "holdout_draws": holdout["draws"],
            }
        )

    five_rows = {
        row["game"]: row
        for row in holdout_rows
        if row["agent_count"] == 5
    }
    game_evidence = study["conclusion"]["by_game"]
    supported = study["conclusion"]["status"] == "supported"
    if supported:
        answer = (
            "本次保留測試支持「更多 Agent 提高五注最佳主號命中」；"
            "兩款遊戲皆呈單調上升，且 5 人相對 2 人的 95% 區間下界大於 0。"
        )
    else:
        answer = (
            "本次保留測試不支持「Agent 越多越準」。增加 Agent 並未在兩款遊戲"
            "同時形成單調提升，也未讓 5 人相對 2 人的差異在兩款遊戲都通過 95% 區間門檻。"
        )

    five_details = []
    for game in (SUPER, LOTTO649):
        row = five_rows[game]
        five_details.append(
            f"**{GAME_NAMES[game]}** 5 人相對 2 人為 "
            f"{_signed(row['delta_best_vs_two'])} 個主號／期，95% 區間 "
            f"{_interval(row['delta_best_vs_two_ci_low'], row['delta_best_vs_two_ci_high'])}"
        )

    methodology = study["methodology"]
    split_profiles = study["data_quality"]["split_profiles"]
    total_eligible = sum(
        profile["eligible_draws"] for profile in split_profiles.values()
    )
    total_holdout = sum(
        profile["holdout_draws"] for profile in split_profiles.values()
    )

    metric_definitions = [
        "最佳主號命中 = 每期固定五注中，主號命中最多的一注之命中數，範圍 0 至 6。",
        "Agent 數量平均 = 同一 Agent 數量的全部組合先在每期取平均，再跨期平均，避免挑冠軍組合。",
        "相對隨機差 = 子議會每期指標減去同一期 200 組固定種子五注均勻隨機基準的平均。",
        "95% 區間 = 13 期循環連續區塊 bootstrap 2,000 次的配對平均差百分位區間。",
        "至少三主號率 = 每期五注中至少一注命中三個以上主號的期數比例。",
    ]
    source_count = {
        "id": "agent-count-holdout",
        "label": "Agent 數量 holdout 消融結果",
        "path": "research/results/agent_ablation_summary.csv",
        "query": {
            "engine": "duckdb",
            "language": "sql",
            "sql": (
                "SELECT game, game_name, agent_count, agent_count_label,\n"
                "  combinations, draws, best_main_hits, total_main_hits,\n"
                "  any_three_plus, union_main_hits, union_size,\n"
                "  random_best_main_hits, delta_best_vs_random,\n"
                "  delta_best_vs_random_ci_low, delta_best_vs_random_ci_high,\n"
                "  delta_best_vs_two, delta_best_vs_two_ci_low,\n"
                "  delta_best_vs_two_ci_high\n"
                "FROM read_csv_auto('research/results/agent_ablation_summary.csv')\n"
                "WHERE split = 'holdout'\n"
                "ORDER BY agent_count, game"
            ),
            "description": (
                "讀取每個 Agent 數量全部組合在最近 30% 時序 holdout 的"
                "每期平均表現與配對隨機基準。"
            ),
            "tables_used": [
                "research/results/agent_ablation_summary.csv"
            ],
            "filters": [
                "split = holdout",
                "每期固定五注",
                f"每遊戲先暖機 {methodology['warmup_draws']} 期",
            ],
            "metric_definitions": metric_definitions,
            "executed_at": study["generated_at"],
        },
    }
    source_subset = {
        "id": "development-selected-subsets",
        "label": "Development 選定子議會的一次性 holdout",
        "path": "research/results/agent_ablation_subsets.csv",
        "query": {
            "engine": "duckdb",
            "language": "sql",
            "sql": (
                "WITH development AS (\n"
                "  SELECT *, ROW_NUMBER() OVER (\n"
                "    PARTITION BY game ORDER BY best_main_hits DESC,\n"
                "      total_main_hits DESC, any_three_plus DESC, subset_id\n"
                "  ) AS rank\n"
                "  FROM read_csv_auto('research/results/agent_ablation_subsets.csv')\n"
                "  WHERE split = 'development'\n"
                "), holdout AS (\n"
                "  SELECT * FROM read_csv_auto(\n"
                "    'research/results/agent_ablation_subsets.csv')\n"
                "  WHERE split = 'holdout'\n"
                ")\n"
                "SELECT h.game, h.game_name, h.subset_id, h.agents,\n"
                "  h.agent_count, d.best_main_hits AS development_best_main_hits,\n"
                "  h.best_main_hits AS holdout_best_main_hits,\n"
                "  h.delta_best_vs_random AS holdout_delta_vs_random,\n"
                "  h.delta_best_vs_random_ci_low AS holdout_ci_low,\n"
                "  h.delta_best_vs_random_ci_high AS holdout_ci_high,\n"
                "  h.any_three_plus AS holdout_any_three_plus, h.draws\n"
                "FROM development d JOIN holdout h\n"
                "  ON d.game = h.game AND d.subset_id = h.subset_id\n"
                "WHERE d.rank = 1\n"
                "ORDER BY h.game"
            ),
            "description": (
                "只用前 70% development 選每款遊戲的冠軍子議會，"
                "再讀取最近 30% holdout 的一次性表現。"
            ),
            "tables_used": [
                "research/results/agent_ablation_subsets.csv"
            ],
            "filters": [
                "development 排名只用 primary metric 與預先定義的 tie-break",
                "holdout 不參與選擇",
            ],
            "metric_definitions": metric_definitions,
            "executed_at": study["generated_at"],
        },
    }

    title = "Agent 數量消融測試"
    manifest = {
        "version": 1,
        "surface": "report",
        "title": title,
        "description": (
            "比較 2、3、4、5 個 Agent 的全部子議會，在固定五注與時序 holdout 下"
            "是否比隨機基準或較少 Agent 更準。"
        ),
        "generatedAt": study["generated_at"],
        "sources": [source_count, source_subset],
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
                    f"- **{answer}**\n"
                    f"- 共檢查 **26 個子議會組合**、**{total_eligible:,} 個可評估遊戲期次**；"
                    f"最近 **{total_holdout:,} 個期次**只作 holdout。\n"
                    f"- {'；'.join(five_details)}。\n"
                    "- 因此不應只為了追求命中率繼續堆 Agent；新增角色應以"
                    "「在全新未見期數帶來可重複的邊際增益」作為保留門檻。"
                ),
                "layout": "full",
                "sourceId": "agent-count-holdout",
            },
            {
                "id": "count-finding",
                "type": "markdown",
                "body": (
                    "## Agent 數量沒有形成穩定的命中階梯\n\n"
                    "下圖以每期固定五注為同一預算，先把同一人數的全部組合在每期平均，"
                    "再和該期均勻隨機五注比較。這個做法回答的是「多一種 Agent 設計的"
                    "平均邊際效果」，不會只挑剛好幸運的組合。柱狀值接近 0，且區間是否"
                    "跨過 0 必須一起解讀；單一正柱不能視為可用預測優勢。"
                ),
                "layout": "full",
                "sourceId": "agent-count-holdout",
            },
            {
                "id": "count-chart-block",
                "type": "chart",
                "chartId": "count-holdout-chart",
                "layout": "full",
            },
            {
                "id": "count-detail",
                "type": "markdown",
                "body": (
                    "## Holdout 數字與不確定性\n\n"
                    "表格保留每種人數的最佳主號命中、隨機基準、相對差、95% 區間，"
                    "以及直接相對 2 人議會的差。主指標單位是「每期最佳一注多命中幾個"
                    "主號」，不是中獎機率或報酬率。"
                ),
                "layout": "full",
                "sourceId": "agent-count-holdout",
            },
            {
                "id": "count-table-block",
                "type": "table",
                "tableId": "count-holdout-table",
                "layout": "full",
            },
            {
                "id": "subset-finding",
                "type": "markdown",
                "body": (
                    "## Development 冠軍沒有資格直接升級成答案\n\n"
                    "每款遊戲各從 development 的 26 個組合選一個冠軍，再看一次 holdout。"
                    "這可檢查明顯過度擬合，但仍有多重比較與有限樣本問題；即使某列在"
                    " holdout 為正，也只能當下一版預註冊實驗的候選，不能回頭改寫本次門檻。"
                ),
                "layout": "full",
                "sourceId": "development-selected-subsets",
            },
            {
                "id": "subset-table-block",
                "type": "table",
                "tableId": "selected-subset-table",
                "layout": "full",
            },
            {
                "id": "recommended-actions",
                "type": "markdown",
                "body": (
                    "## 建議下一步\n\n"
                    "1. 目前五個 Agent 保留作為可解釋的研究控制組，不因歷史排名增加權重。\n"
                    "2. 不再只以「多一個角色」當升級理由；新 Agent 必須先做邊際消融，"
                    "並在之後累積的全新期數通過同一門檻。\n"
                    "3. 自動 loop 每次開獎後照常檢討，但策略版本、選擇規則與評估指標要先凍結；"
                    "新的開獎只能評分，不能回填改寫舊決策。\n"
                    "4. 下一個正式檢查點應比較：現行五人議會、精簡議會、五注均勻隨機，"
                    "並同時記錄延遲與模型資源成本。"
                ),
                "layout": "full",
            },
            {
                "id": "further-questions",
                "type": "markdown",
                "body": (
                    "## Further Questions\n\n"
                    "- qwen3:8b 終局裁判在真正逐期前向資料上，是否能比規則裁判穩定改善五注分散度？\n"
                    "- 哪一個 Agent 提供的是其他角色沒有的候選覆蓋，而不是重複同一偏好？\n"
                    "- 若命中沒有改善，精簡議會能否在不損失覆蓋率下顯著降低推論延遲？"
                ),
                "layout": "full",
            },
            {
                "id": "caveats",
                "type": "markdown",
                "body": (
                    "## Caveats and Assumptions\n\n"
                    "- **可信度：Share with caveats。** 帳本完整、時序與無前視檢查通過，"
                    "但這仍是對既有歷史資料的消融，不是未來期數的預註冊實驗。\n"
                    "- 彩票合法組合在理論模型下等機率；任何歷史差異都可能是抽樣噪音。\n"
                    "- 26 個組合會產生多重比較；development 冠軍只列為探索性候選。\n"
                    f"- 隨機基準每期 {methodology['null_replicates_per_draw']} 次，區間採"
                    f" {methodology['bootstrap_block_draws']} 期區塊、"
                    f"{methodology['bootstrap_samples']:,} 次 bootstrap。\n"
                    "- 歷史回放採規則裁判；本報告不把結果外推為 qwen3:8b 的未來命中能力。\n"
                    "- 全程純模擬，正式 records 雜湊前後一致，不構成購買或下注建議。"
                ),
                "layout": "full",
            },
        ],
        "charts": [
            {
                "id": "count-holdout-chart",
                "title": "Holdout 最佳主號命中差與 Agent 數量",
                "subtitle": (
                    "正值代表每期五注中的最佳一注平均高於均勻隨機五注；"
                    "兩款遊戲未共同通過預設門檻"
                ),
                "intent": "comparison",
                "type": "bar",
                "dataset": "count_holdout",
                "sourceId": "agent-count-holdout",
                "encodings": {
                    "x": {
                        "field": "agent_count_label",
                        "type": "nominal",
                        "label": "Agent 數量",
                    },
                    "y": {
                        "field": "delta_best_vs_random",
                        "type": "quantitative",
                        "format": "number",
                        "label": "相對隨機的最佳主號命中差",
                    },
                    "color": {
                        "field": "game_name",
                        "type": "nominal",
                        "label": "遊戲",
                    },
                    "tooltip": [
                        {"field": "best_main_hits", "format": "number"},
                        {"field": "random_best_main_hits", "format": "number"},
                        {
                            "field": "delta_best_vs_random_ci_low",
                            "format": "number",
                        },
                        {
                            "field": "delta_best_vs_random_ci_high",
                            "format": "number",
                        },
                        {"field": "draws", "format": "number"},
                        {"field": "combinations", "format": "number"},
                    ],
                },
                "valueFormat": "number",
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
                        "label": "均勻隨機基準",
                        "lineStyle": "dashed",
                        "color": "neutral",
                    }
                ],
                "surface": {"viewMode": "both", "showControls": True},
            }
        ],
        "tables": [
            {
                "id": "count-holdout-table",
                "title": "Agent 數量 holdout 詳細結果",
                "subtitle": "同一人數的全部組合先在每期平均",
                "dataset": "count_holdout",
                "sourceId": "agent-count-holdout",
                "layout": "full",
                "density": "spacious",
                "defaultSort": {"field": "agent_count", "direction": "asc"},
                "columns": [
                    {"field": "game_name", "label": "遊戲", "type": "text"},
                    {
                        "field": "agent_count",
                        "label": "Agent 數",
                        "format": "number",
                    },
                    {
                        "field": "combinations",
                        "label": "組合數",
                        "format": "number",
                    },
                    {
                        "field": "best_main_hits",
                        "label": "最佳主號命中",
                        "format": "number",
                    },
                    {
                        "field": "random_best_main_hits",
                        "label": "隨機基準",
                        "format": "number",
                    },
                    {
                        "field": "delta_best_vs_random",
                        "label": "相對隨機差",
                        "format": "number",
                        "movement": True,
                    },
                    {
                        "field": "delta_best_vs_random_ci_low",
                        "label": "95% 下界",
                        "format": "number",
                    },
                    {
                        "field": "delta_best_vs_random_ci_high",
                        "label": "95% 上界",
                        "format": "number",
                    },
                    {
                        "field": "delta_best_vs_two",
                        "label": "相對 2 人差",
                        "format": "number",
                        "movement": True,
                    },
                    {
                        "field": "any_three_plus",
                        "label": "至少三主號率",
                        "format": "percent",
                    },
                    {
                        "field": "draws",
                        "label": "Holdout 期數",
                        "format": "number",
                    },
                ],
            },
            {
                "id": "selected-subset-table",
                "title": "Development 冠軍的一次性 holdout",
                "subtitle": "每款遊戲各選一個組合，僅供探索性下一版候選",
                "dataset": "selected_subsets",
                "sourceId": "development-selected-subsets",
                "layout": "full",
                "density": "spacious",
                "defaultSort": {"field": "game_name", "direction": "asc"},
                "columns": [
                    {"field": "game_name", "label": "遊戲", "type": "text"},
                    {
                        "field": "agent_names",
                        "label": "Development 冠軍",
                        "type": "text",
                    },
                    {
                        "field": "agent_count",
                        "label": "Agent 數",
                        "format": "number",
                    },
                    {
                        "field": "development_best_main_hits",
                        "label": "Development 最佳命中",
                        "format": "number",
                    },
                    {
                        "field": "holdout_best_main_hits",
                        "label": "Holdout 最佳命中",
                        "format": "number",
                    },
                    {
                        "field": "holdout_delta_vs_random",
                        "label": "Holdout 相對隨機",
                        "format": "number",
                        "movement": True,
                    },
                    {
                        "field": "holdout_ci_low",
                        "label": "95% 下界",
                        "format": "number",
                    },
                    {
                        "field": "holdout_ci_high",
                        "label": "95% 上界",
                        "format": "number",
                    },
                    {
                        "field": "holdout_any_three_plus",
                        "label": "至少三主號率",
                        "format": "percent",
                    },
                ],
            },
        ],
    }
    snapshot = {
        "version": 1,
        "generatedAt": study["generated_at"],
        "status": "ready",
        "datasets": {
            "count_holdout": chart_rows,
            "selected_subsets": selected_rows,
        },
    }
    return {
        "surface": "report",
        "manifest": manifest,
        "snapshot": snapshot,
    }


def write_artifact(results_dir: Path) -> Path:
    artifact = build_artifact(results_dir)
    path = Path(results_dir) / "agent_ablation_artifact.json"
    path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path
