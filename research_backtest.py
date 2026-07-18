"""執行 lotto-lab 的獨立歷史策略研究。"""
from __future__ import annotations

import argparse
from pathlib import Path

from engine.env import Env
from engine.games import GAME_NAMES
from engine.picker import GAMES
from research.backtest import run_study


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="全歷史走步回測：training 調參、validation 選政策、holdout 決勝"
    )
    parser.add_argument("--replicates", type=int, default=8)
    parser.add_argument("--bootstrap-samples", type=int, default=1_000)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("research") / "results",
    )
    args = parser.parse_args(argv)
    env = Env()
    study = run_study(
        env.store,
        env.base,
        args.output,
        replicates=args.replicates,
        bootstrap_samples=args.bootstrap_samples,
    )
    print(f"研究結果：{args.output.resolve()}")
    print("經濟決策：不參與（純模擬）")
    for game in GAMES:
        result = study["selected"][game]
        holdout = result["holdout"]
        print(
            f"{GAME_NAMES[game]}：驗證集選 {result['policy_id']}；"
            f"holdout 相對隨機 {holdout['delta_robust_roi_mean']:+.2%}，"
            f"95% CI [{holdout['delta_ci_low']:+.2%}, "
            f"{holdout['delta_ci_high']:+.2%}]；"
            f"條件式決策 {result['conditional_decision']}"
        )


if __name__ == "__main__":
    main()
