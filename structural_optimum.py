"""產生五注完整中獎聯集機率的全域結構最優證明。"""
from __future__ import annotations

import argparse
from pathlib import Path

from research.structural_optimum import (
    build_structural_optimum_certificate,
    write_results,
)


BASE = Path(__file__).resolve().parent


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="精確驗證五注完全分散結構的全域最優性"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=(
            Path("research")
            / "results"
            / "structural_optimum.json"
        ),
    )
    args = parser.parse_args(argv)
    result = build_structural_optimum_certificate(BASE)
    output = write_results(result, BASE / args.output)
    print("結論：五注完全分散為完整任一獎級的全域最優結構")
    for game in ("super", "lotto649"):
        probability = result["games"][game]["any_prize"][
            "global_maximum_probability"
        ]
        print(f"{game}: {probability:.12%}")
    print(f"certificate: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
