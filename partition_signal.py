"""回跑同一批 30 個共識主號的五注分組訊號。"""
from __future__ import annotations

import argparse
from pathlib import Path

from engine.games import LOTTO649, SUPER
from research.partition_signal import (
    PartitionSignalConfig,
    run_partition_signal_study,
    write_results,
)


BASE = Path(__file__).resolve().parent


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="驗證 30 個共識主號的分組封存訊號"
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
    result = run_partition_signal_study(
        {
            SUPER: BASE / "simulation" / "results" / "super.jsonl",
            LOTTO649: (
                BASE / "simulation" / "results" / "lotto649.jsonl"
            ),
        },
        base=BASE,
        config=PartitionSignalConfig(
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
            f"{game}: "
            f"development={decision['development_selected_partitioner']}, "
            f"promotion={decision['promotion_eligible']}"
        )
    for name, path in paths.items():
        print(f"{name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
