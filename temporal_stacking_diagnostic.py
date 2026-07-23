"""執行時間自適應機率 stacking 描述性診斷。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from engine.games import LOTTO649, SUPER
from research.temporal_stacking_diagnostic import (
    run_temporal_stacking_diagnostic,
    write_results,
)


ROOT = Path(__file__).resolve().parent


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="時間自適應機率 stacking prequential 診斷"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "research" / "results",
    )
    parser.add_argument(
        "--bootstrap-samples",
        type=int,
        default=2_000,
    )
    args = parser.parse_args(argv)
    result = run_temporal_stacking_diagnostic(
        {
            SUPER: ROOT / "simulation" / "results" / "super.jsonl",
            LOTTO649: (
                ROOT
                / "simulation"
                / "results"
                / "lotto649.jsonl"
            ),
        },
        base=ROOT,
        bootstrap_samples=args.bootstrap_samples,
    )
    path = write_results(result, args.output_dir)
    print(
        json.dumps(
            {
                "status": result["conclusion"]["status"],
                "descriptive_minimax_method": result["conclusion"][
                    "descriptive_minimax_method"
                ],
                "selected_future_challenger": result["conclusion"][
                    "selected_future_challenger"
                ],
                "audit_hash": result["audit_hash"],
                "result_file": str(path),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
