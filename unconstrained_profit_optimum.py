"""重算並寫出威力彩無 overlap 守門獲利全域最優證書。"""
from __future__ import annotations

from pathlib import Path

from research.unconstrained_profit_optimum import (
    build_unconstrained_profit_certificate,
    write_results,
)


BASE = Path(__file__).resolve().parent
OUTPUT = (
    BASE
    / "research"
    / "results"
    / "unconstrained_profit_optimum.json"
)


def main() -> int:
    result = build_unconstrained_profit_certificate(BASE)
    write_results(result, OUTPUT)
    game = result["games"]["super"]
    metrics = game["metrics"]
    print(f"無守門獲利全域最優證書：{OUTPUT}")
    print(f"certificate={result['certificate_hash']}")
    print(
        "歷史最低實領嚴格獲利率："
        f"{metrics['empirical_floor_strict_profit']['probability']:.6%}"
    )
    print(
        "任一獎／至少三主號／至少四主號："
        f"{metrics['any_prize']['probability']:.6%} / "
        f"{metrics['at_least_three_main']['probability']:.6%} / "
        f"{metrics['at_least_four_main']['probability']:.6%}"
    )
    print(
        "現行名目獎金全域證明："
        f"{result['proof']['global_nominal_optimum_proved']}；"
        "proper-special 最大上界="
        f"{result['proof']['maximum_proper_special_nominal_upper_count']}"
    )
    print(
        "結構：十個三票共享主號各一次，五注第二區相同；"
        "正式 records 與既有前向登記未改動。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
