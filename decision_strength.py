"""執行 stacking 軟機率到 top-k 硬決策的強度稽核。"""
from __future__ import annotations

from pathlib import Path

from research.decision_strength import (
    run_decision_strength_audit,
    write_results,
)


BASE = Path(__file__).resolve().parent


def main() -> int:
    result = run_decision_strength_audit(BASE)
    path = write_results(
        result,
        BASE / "research" / "results",
    )
    print(f"診斷：{result['diagnosis']['interpretation']}")
    for game, row in result["games"].items():
        main = row["main"]
        print(
            f"{game}: nonuniform weight="
            f"{row['nonuniform_main_weight']:.10g}; "
            f"expected hit lift="
            f"{main['model_implied_expected_hit_lift']:.10g}; "
            f"pairs for 80% power="
            f"{main['approx_pairs_for_80pct_power']}"
        )
    print(f"決策：{result['decision']['status']}")
    print(f"JSON：{path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
