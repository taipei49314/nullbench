"""產生持續球號偏差完整子集合機率正式研究產物。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from research.persistent_bias_signal import (
    run_persistent_bias_signal,
    write_result,
)


BASE = Path(__file__).resolve().parent
DEFAULT_OUTPUT = (
    BASE
    / "research"
    / "results"
    / "persistent_bias_signal.json"
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="回跑持續球號偏差的完整 subset proper score"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
    )
    args = parser.parse_args(argv)
    result = run_persistent_bias_signal(base=BASE)
    output = write_result(result, args.output)
    summary = {
        "output": str(output),
        "experiment_id": result["experiment_id"],
        "audit_hash": result["audit_hash"],
        "conclusion": result["conclusion"]["status"],
        "games": {
            game: {
                "draws": row["draws"],
                "mean_regret_nats": row["mean_regret_nats"],
                "bootstrap_95": [
                    row["bootstrap_95_low"],
                    row["bootstrap_95_high"],
                ],
                "future_challenger_qualified": (
                    row["future_challenger_qualified"]
                ),
            }
            for game, row in result["diagnostics"].items()
        },
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
