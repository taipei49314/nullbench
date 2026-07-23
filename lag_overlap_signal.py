"""產生相鄰期重複數完整 subset proper-score artifact。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from research.lag_overlap_signal import (
    run_lag_overlap_signal,
    write_result,
)


BASE = Path(__file__).resolve().parent
DEFAULT_OUTPUT = (
    BASE / "research" / "results" / "lag_overlap_signal.json"
)


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="稽核相鄰期重複數的完整六主號機率"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
    )
    args = parser.parse_args(argv)
    result = run_lag_overlap_signal(base=BASE)
    output = write_result(result, args.output)
    summary = {
        "output": str(output),
        "experiment_id": result["experiment_id"],
        "audit_hash": result["audit_hash"],
        "status": result["conclusion"]["status"],
        "diagnostics": {
            game: {
                "raw_mean_regret_nats": row[
                    "raw_mean_regret_nats"
                ],
                "raw_bootstrap_95": [
                    row["raw_bootstrap_95_low"],
                    row["raw_bootstrap_95_high"],
                ],
                "safe_mean_regret_nats": row[
                    "safe_mean_regret_nats"
                ],
                "final_e_value": row["final_e_value"],
                "maximum_e_value": row["maximum_e_value"],
                "future_challenger_qualified": row[
                    "future_challenger_qualified"
                ],
            }
            for game, row in result["diagnostics"].items()
        },
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
