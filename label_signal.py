"""回跑完全分散五注的 30 號標籤排序訊號。"""
from __future__ import annotations

import argparse
from pathlib import Path

from engine.games import LOTTO649, SUPER
from research.label_signal import (
    LabelSignalConfig,
    run_label_signal_study,
    write_results,
)


BASE = Path(__file__).resolve().parent


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="驗證 Agent／歷史標籤排序的封存 holdout 訊號"
    )
    parser.add_argument(
        "--warmup-draws", type=int, default=60
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
    result = run_label_signal_study(
        {
            SUPER: BASE / "simulation" / "results" / "super.jsonl",
            LOTTO649: (
                BASE / "simulation" / "results" / "lotto649.jsonl"
            ),
        },
        base=BASE,
        config=LabelSignalConfig(
            warmup_draws=args.warmup_draws,
            bootstrap_samples=args.bootstrap_samples,
            bootstrap_block=args.bootstrap_block,
        ),
    )
    paths = write_results(result, BASE / args.output)
    print(f"結論：{result['conclusion']['status']}")
    for game, decision in result[
        "development_selection_and_holdout"
    ].items():
        print(
            f"{game}: development={decision['development_selected_ranker']}, "
            f"promotion={decision['promotion_eligible']}"
        )
    for name, path in paths.items():
        print(f"{name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
