"""執行 AI 辯論逐期信心的條件式校準稽核。"""
from __future__ import annotations

import argparse
from pathlib import Path

from engine.games import LOTTO649, SUPER
from research.debate_confidence import (
    DebateConfidenceConfig,
    run_debate_confidence_study,
    write_results,
)


BASE = Path(__file__).resolve().parent


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="稽核高信心期的辯論主號排名"
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
    result = run_debate_confidence_study(
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
        config=DebateConfidenceConfig(
            bootstrap_samples=args.bootstrap_samples,
            bootstrap_block=args.bootstrap_block,
        ),
    )
    path = write_results(result, BASE / args.output)
    for game, game_result in result["games"].items():
        for cutoff in (10, 30):
            row = game_result["holdout"][
                f"top_{cutoff}_hits"
            ]
            safe = row["sequential_safe"]
            print(
                f"{game} top-{cutoff}: "
                f"high-null={row['high_delta_vs_null']:.6f}; "
                f"high-low={row['high_minus_low']:.6f}; "
                f"fixed-group Holm="
                f"{row['holm_high_vs_null_one_sided_p_value']:.6f}/"
                f"{row['holm_high_minus_low_one_sided_p_value']:.6f}; "
                f"safe Holm="
                f"{safe['high_vs_null']['holm_anytime_valid_p_value']:.6f}/"
                f"{safe['high_minus_low']['holm_anytime_valid_p_value']:.6f}; "
                f"gate={row['candidate_gate_passed']}"
            )
    print(f"conclusion: {result['conclusion']['status']}")
    print(f"json: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
