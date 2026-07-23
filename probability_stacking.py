"""執行逐期 proper-score 機率堆疊的唯前向影子研究。"""
from __future__ import annotations

import argparse
from pathlib import Path

from engine.games import GAME_NAMES, LOTTO649, SUPER
from research.probability_stacking import (
    run_probability_stacking,
    write_results,
)


BASE = Path(__file__).resolve().parent


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "用既有完整歷史逐期初始化機率專家權重；"
            "只允許未來不可回填開獎作為升級證據"
        )
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("research") / "results",
    )
    args = parser.parse_args(argv)
    result = run_probability_stacking(
        {
            SUPER: BASE / "simulation" / "results" / "super.jsonl",
            LOTTO649: (
                BASE / "simulation" / "results" / "lotto649.jsonl"
            ),
        },
        base=BASE,
    )
    path = write_results(result, BASE / args.output)
    print(f"研究狀態：{result['conclusion']['status']}")
    for game in (SUPER, LOTTO649):
        summary = result["prequential_summary"][game]
        print(
            f"{GAME_NAMES[game]}：{summary['draws']} 期；"
            f"主號 mixture log loss "
            f"{summary['mean_mixture_main_log_loss']:.8f}"
        )
    print(
        "未來影子候選："
        + result["future_forward_shadow_candidate"]["candidate_hash"]
    )
    print(f"JSON：{path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
