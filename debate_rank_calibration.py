"""執行 AI 辯論主號排名的時間校準稽核。"""
from __future__ import annotations

import argparse
from pathlib import Path

from engine.games import LOTTO649, SUPER
from research.debate_rank_calibration import (
    DebateRankCalibrationConfig,
    run_debate_rank_calibration,
    write_results,
)


BASE = Path(__file__).resolve().parent


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="稽核辯論主號 top-10／20／30 排名"
    )
    parser.add_argument(
        "--bootstrap-samples", type=int, default=2_000
    )
    parser.add_argument(
        "--bootstrap-block", type=int, default=13
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("research") / "results",
    )
    args = parser.parse_args(argv)
    result = run_debate_rank_calibration(
        {
            SUPER: BASE
            / "simulation"
            / "results"
            / "super.jsonl",
            LOTTO649: BASE
            / "simulation"
            / "results"
            / "lotto649.jsonl",
        },
        base=BASE,
        config=DebateRankCalibrationConfig(
            bootstrap_samples=args.bootstrap_samples,
            bootstrap_block=args.bootstrap_block,
        ),
    )
    path = write_results(result, BASE / args.output)
    for game, game_result in result["games"].items():
        top_10 = game_result["holdout"]["top_10_hits"]
        print(
            f"{game}: top-10 delta="
            f"{top_10['mean_delta_vs_exact_null']:.6f}; "
            f"Holm p="
            f"{top_10['holm_adjusted_two_sided_p_value']:.6f}; "
            f"{top_10['calibration']}"
        )
    print(f"mapping: {result['mapping_decision']['decision']}")
    print(f"json: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
