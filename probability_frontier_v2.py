"""產生包含 lag-overlap 的完整六主號機率前緣 v2。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from research.probability_frontier_v2 import (
    run_probability_frontier_v2,
    write_result,
)


BASE = Path(__file__).resolve().parent
DEFAULT_OUTPUT = (
    BASE / "research" / "results" / "probability_frontier_v2.json"
)


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="建立包含 lag-overlap 的完整六主號機率前緣 v2"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
    )
    args = parser.parse_args(argv)
    result = run_probability_frontier_v2(base=BASE)
    output = write_result(result, args.output)
    summary = {
        "output": str(output),
        "experiment_id": result["experiment_id"],
        "audit_hash": result["audit_hash"],
        "status": result["conclusion"]["status"],
        "champion": result["conclusion"]["champion_method_id"],
        "best_non_uniform": result["conclusion"][
            "best_non_uniform_method_id"
        ],
        "method_count": len(result["frontier_rows"]),
        "ranking": [
            {
                "rank": row["rank"],
                "method_id": row["method_id"],
                "minimax_regret": row["minimax_regret"],
            }
            for row in result["frontier_rows"]
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
