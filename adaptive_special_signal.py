"""執行威力彩共同第二區的時間自適應訊號稽核。"""
from __future__ import annotations

import argparse
from pathlib import Path

from research.adaptive_special_signal import (
    AdaptiveSpecialConfig,
    run_adaptive_special_study,
    write_results,
)


BASE = Path(__file__).resolve().parent


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="稽核共同第二區的時間自適應方法"
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
    result = run_adaptive_special_study(
        BASE / "simulation" / "results" / "super.jsonl",
        base=BASE,
        config=AdaptiveSpecialConfig(
            bootstrap_samples=args.bootstrap_samples,
            bootstrap_block=args.bootstrap_block,
        ),
    )
    path = write_results(result, BASE / args.output)
    inner = result["inner_validation"]
    print(f"inner status: {inner['status']}")
    print(f"selected method: {inner['selected_method']}")
    print(f"holdout status: {result['holdout']['status']}")
    print(f"conclusion: {result['conclusion']['status']}")
    print(f"json: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
