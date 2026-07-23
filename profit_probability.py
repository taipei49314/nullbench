"""重算並寫出五注獲利機率 Pareto 正式證書。"""
from __future__ import annotations

from pathlib import Path

from research.profit_probability import (
    build_profit_probability_certificate,
    write_results,
)


BASE = Path(__file__).resolve().parent
OUTPUT = (
    BASE
    / "research"
    / "results"
    / "profit_probability.json"
)


def main() -> int:
    result = build_profit_probability_certificate(BASE)
    write_results(result, OUTPUT)
    super_row = result["games"]["super"]
    baseline = super_row["coverage_optimum_baseline"]["metrics"]
    optimum = super_row["strict_profit_optimum"]["metrics"]
    print(f"獲利機率證書：{OUTPUT}")
    print(f"certificate={result['certificate_hash']}")
    print(
        "威力彩歷史最低實領嚴格獲利率："
        f"{baseline['empirical_floor_strict_profit']['probability']:.6%}"
        " -> "
        f"{optimum['empirical_floor_strict_profit']['probability']:.6%}"
    )
    print(
        "威力彩任一獎率："
        f"{baseline['any_prize']['probability']:.6%}"
        " -> "
        f"{optimum['any_prize']['probability']:.6%}"
    )
    print(
        "至少四主號機率："
        f"{optimum['at_least_four_main']['probability']:.6%}"
        "（不變）"
    )
    print("正式 records 未改動；既有前向登記未切換。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
