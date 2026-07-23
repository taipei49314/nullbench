"""產生五注完全分散結構的精確獎級與邊際機率報告。"""
from __future__ import annotations

import argparse
from pathlib import Path

from research.prize_tier_profile import (
    build_prize_tier_certificate,
    write_results,
)


BASE = Path(__file__).resolve().parent


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="精確分解五注完全分散的獎級與邊際機率"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=(
            Path("research")
            / "results"
            / "prize_tier_profile.json"
        ),
    )
    args = parser.parse_args(argv)
    result = build_prize_tier_certificate(BASE)
    output = write_results(result, BASE / args.output)
    print("結論：任一獎機率已拆成最高獎級、多注同中與逐注邊際")
    for game in ("super", "lotto649"):
        row = result["games"][game]
        profile = row["five_ticket_profile"]
        jackpot = row["jackpot_probability_five_tickets"]
        print(
            f"{game}: 任一獎={profile['any_prize']['probability']:.12%}, "
            f"頭獎={jackpot['probability']:.12%}"
        )
    print(f"certificate: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
