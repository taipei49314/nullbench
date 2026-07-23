"""Run the exact-outcome switching-Bayes unknown-generator audit."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from engine.games import GAME_NAMES, LOTTO649, SUPER
from research.switching_bayes import (
    run_switching_bayes_study,
    write_results,
)


BASE = Path(__file__).resolve().parent


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description=(
            "以完整六號組合 likelihood 逐期回放未知生成器假設，"
            "並保留機制切換後重新翻盤的權重。"
        )
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("research") / "results",
    )
    args = parser.parse_args(argv)
    result = run_switching_bayes_study(
        {
            SUPER: BASE / "simulation" / "results" / "super.jsonl",
            LOTTO649: (
                BASE / "simulation" / "results" / "lotto649.jsonl"
            ),
        },
        base=BASE,
    )
    path = write_results(result, BASE / args.output)
    print(f"研究狀態：{result['decision']['status']}")
    for game in (SUPER, LOTTO649):
        summary = result["prequential_summary"][game]
        regret = summary[
            "main_exact_subset_regret_vs_uniform"
        ]["holdout_mean"]
        rank = summary[
            "top_30_hit_excess_vs_label_symmetry"
        ]["debate_consensus"]["holdout_mean"]
        print(
            f"{GAME_NAMES[game]}：{summary['draws']} 期；"
            f"holdout subset regret {regret:.8f}；"
            f"共識 top-30 命中超額 {rank:+.5f}"
        )
    print(f"JSON：{path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
