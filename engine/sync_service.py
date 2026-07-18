"""官方開獎偵測與 agent 閉環結果同步。

只重抓當月官方 API。若偵測到新期數，才重建完整逐期回放與下一期決策；
沒有新資料時保持既有可稽核產物不變。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import agent_loop, forward_lab, qwen_judge
from .env import Env
from .fetch import ingest
from .games import GAME_NAMES, LOTTO649, SUPER
from .ledger import TAIPEI

GAMES = (SUPER, LOTTO649)
Progress = Callable[[str, str, dict | None], None]


def _run_with_qwen(store, output_dir: Path) -> dict:
    return agent_loop.run_all(
        store,
        output_dir,
        final_judge=qwen_judge.adjudicate,
    )


def _read_manifest(output_dir: Path) -> dict | None:
    path = output_dir / "manifest.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


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
    forward_syncer=forward_lab.reconcile_forward_registry,
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

    if needs_rebuild:
        emit(
            "reviewing",
            f"偵測到 {new_total} 期新開獎，正在執行揭曉後檢討",
            {"new_draws": changes},
        )
        emit(
            "optimizing",
            "正在重建完整回放、更新 Agent 評分與下一期候選",
            None,
        )
        manifest = runner(fresh_env.store, output_dir)
    else:
        manifest = previous_manifest

    emit(
        "preregistering",
        "正在結算終局裁判 A/B 並凍結下一期三組對照",
        None,
    )
    forward_experiment = forward_syncer(
        base,
        fresh_env.store,
        manifest,
    )

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
        "forward_experiment": {
            "settlements_created": forward_experiment[
                "settlements_created"
            ],
            "registrations": forward_experiment["registrations"],
            "evidence_status": forward_experiment["summary"][
                "evidence_status"
            ],
            "recommendation": forward_experiment["summary"][
                "recommendation"
            ],
            "verification": forward_experiment["summary"]["verification"],
        },
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
