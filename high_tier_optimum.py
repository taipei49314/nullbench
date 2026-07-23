"""重算五注高獎級 Pareto 最優補充證書。"""
from pathlib import Path

from research.high_tier_optimum import (
    build_high_tier_optimum_certificate,
    write_results,
)


BASE = Path(__file__).resolve().parent


def main() -> int:
    result = build_high_tier_optimum_certificate(BASE)
    path = write_results(
        result,
        BASE / "research" / "results" / "high_tier_optimum.json",
    )
    print(f"certificate_hash: {result['certificate_hash']}")
    for game, row in result["games"].items():
        cutoff = row["cumulative_high_tier_union_bounds"][-1]
        print(
            f"{game}: 頭獎至{row['high_tier_cutoff_label']} "
            f"{cutoff['disjoint_probability']:.12%}"
        )
    print(f"json: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
