"""執行抽出順序子集合訊號正式研究。"""
from __future__ import annotations

import argparse
from pathlib import Path

from research.draw_order_signal import (
    run_draw_order_signal,
    write_result,
)


BASE = Path(__file__).resolve().parent
DEFAULT_OUTPUT = (
    BASE / "research" / "results" / "draw_order_signal.json"
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="檢驗過去抽出位置能否改善完整無序六號子集合機率",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
    )
    args = parser.parse_args()
    result = run_draw_order_signal(base=BASE)
    output = write_result(result, args.output)
    print(f"result={output}")
    print(f"status={result['conclusion']['status']}")
    for game, row in result["diagnostics"].items():
        print(
            f"{game}: regret={row['mean_regret_nats']:.12f} "
            f"ci_high={row['bootstrap_95_high']:.12f} "
            f"final_e={row['final_e_value']:.6g}"
        )
    print(f"audit_hash={result['audit_hash']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
