"""產生開獎星期完整子集合機率正式研究產物。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from research.calendar_regime_signal import (
    run_calendar_regime_signal,
    write_result,
)


BASE = Path(__file__).resolve().parent
DEFAULT_OUTPUT = (
    BASE
    / "research"
    / "results"
    / "calendar_regime_signal.json"
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="回跑開獎星期條件的完整 subset proper score"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
    )
    args = parser.parse_args(argv)
    result = run_calendar_regime_signal(base=BASE)
    output = write_result(result, args.output)
    summary = {
        "output": str(output),
        "experiment_id": result["experiment_id"],
        "audit_hash": result["audit_hash"],
        "conclusion": result["conclusion"]["status"],
        "probability_decision": result["conclusion"][
            "probability_decision"
        ],
        "games": {
            game: {
                "draws": row["draws"],
                "off_schedule_draws": row["off_schedule_draws"],
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
