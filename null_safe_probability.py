"""執行公平零模型安全機率閘門研究。"""
from __future__ import annotations

import argparse
from pathlib import Path

from engine.games import GAME_NAMES, LOTTO649, SUPER
from research.null_safe_probability import (
    run_null_safe_probability,
    write_results,
)


BASE = Path(__file__).resolve().parent


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "沒有充分非均勻 likelihood 證據時，"
            "把號碼機率回退到精確均勻基準"
        )
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("research") / "results",
    )
    args = parser.parse_args(argv)
    result = run_null_safe_probability(
        {
            SUPER: BASE / "simulation" / "results" / "super.jsonl",
            LOTTO649: (
                BASE / "simulation" / "results" / "lotto649.jsonl"
            ),
        },
        base=BASE,
    )
    path = write_results(result, BASE / args.output)
    print(f"研究狀態：{result['conclusion']['status']}")
    for game in (SUPER, LOTTO649):
        row = result["prequential_summary"][game]["main"]
        print(
            f"{GAME_NAMES[game]}：既有 regret "
            f"{row['existing_mixture_regret_vs_uniform']:.12f}；"
            f"null-safe regret "
            f"{row['null_safe_regret_vs_uniform']:.12f}；"
            f"最大 e-value {row['maximum_restart_e_value']:.6f}"
        )
    print(
        "未來影子候選："
        + result["future_forward_shadow_candidate"]["candidate_hash"]
    )
    print(f"JSON：{path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
