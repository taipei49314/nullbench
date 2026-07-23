"""執行開獎機制的號碼、星期、序列與第二區訊號稽核。"""
from __future__ import annotations

import argparse
from pathlib import Path

from engine.games import LOTTO649, SUPER
from research.mechanism_signal import (
    MechanismSignalConfig,
    run_mechanism_signal_study,
    write_results,
)


BASE = Path(__file__).resolve().parent


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="檢驗可跨時間重現的開獎機制偏差"
    )
    parser.add_argument("--warmup-draws", type=int, default=60)
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
    result = run_mechanism_signal_study(
        {
            SUPER: BASE / "simulation" / "results" / "super.jsonl",
            LOTTO649: (
                BASE / "simulation" / "results" / "lotto649.jsonl"
            ),
        },
        base=BASE,
        config=MechanismSignalConfig(
            warmup_draws=args.warmup_draws,
            bootstrap_samples=args.bootstrap_samples,
            bootstrap_block=args.bootstrap_block,
        ),
    )
    paths = write_results(result, BASE / args.output)
    print(f"結論：{result['conclusion']['status']}")
    for game, decision in result["main_decisions"].items():
        print(
            f"{game}: {decision['development_selected_candidate']} / "
            f"promotion={decision['promotion_eligible']}"
        )
    special = result["super_special_candidate"]
    print(
        "super specials: "
        f"{special['selected_specials']} / "
        f"promotion={special['promotion_eligible']}"
    )
    common = special["profit_common_special_candidate"]
    print(
        "super profit common special: "
        f"{common['selected_special']} / "
        f"promotion={common['promotion_eligible']}"
    )
    for name, path in paths.items():
        print(f"{name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
