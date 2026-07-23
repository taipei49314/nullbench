"""產生實體開獎中介資料可用性 artifact。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from research.physical_metadata_audit import (
    run_physical_metadata_audit,
    write_result,
)


BASE = Path(__file__).resolve().parent
DEFAULT_OUTPUT = (
    BASE / "research" / "results" / "physical_metadata_audit.json"
)


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="稽核實體開獎資料能否在投注截止前合法用於選號"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
    )
    args = parser.parse_args(argv)
    result = run_physical_metadata_audit(base=BASE)
    output = write_result(result, args.output)
    summary = {
        "output": str(output),
        "experiment_id": result["experiment_id"],
        "audit_hash": result["audit_hash"],
        "status": result["conclusion"]["status"],
        "raw_files": result["raw_schema_audit"]["files_total"],
        "raw_rows": result["raw_schema_audit"]["rows_total"],
        "raw_physical_metadata_rows": result[
            "raw_schema_audit"
        ]["physical_metadata_rows_total"],
        "observations": result["observation_audit"][
            "total_observations"
        ],
        "pre_cutoff_eligible_observations": result[
            "observation_audit"
        ]["pre_cutoff_eligible_observations"],
        "number_probability_model_allowed": result["conclusion"][
            "number_probability_model_allowed"
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
