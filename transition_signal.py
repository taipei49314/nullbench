"""執行 lag-1／lag-2 條件轉移訊號稽核。"""
from __future__ import annotations

import argparse
from pathlib import Path

from engine.games import LOTTO649, SUPER
from research.transition_signal import (
    TransitionSignalConfig,
    run_transition_signal_study,
    write_results,
)


BASE = Path(__file__).resolve().parent


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="檢驗前期號碼對下一期標籤的條件轉移訊號"
    )
    parser.add_argument("--warmup-draws", type=int, default=60)
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
    result = run_transition_signal_study(
        {
            SUPER: BASE / "simulation" / "results" / "super.jsonl",
            LOTTO649: (
                BASE / "simulation" / "results" / "lotto649.jsonl"
            ),
        },
        base=BASE,
        config=TransitionSignalConfig(
            warmup_draws=args.warmup_draws,
            bootstrap_samples=args.bootstrap_samples,
            bootstrap_block=args.bootstrap_block,
        ),
    )
    paths = write_results(result, BASE / args.output)
    print(f"結論：{result['conclusion']['status']}")
    for game, decision in result["decisions"].items():
        print(
            f"{game}: {decision['inner_selected_candidate']} / "
            "historical_promotion="
            f"{decision['historical_promotion_eligible']}"
        )
    for name, path in paths.items():
        print(f"{name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
