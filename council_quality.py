"""執行 Agent 品質、替換與辯論敏感度影子研究。"""
from __future__ import annotations

import argparse
from pathlib import Path

from engine.games import LOTTO649, SUPER
from research.council_quality import (
    QualityConfig,
    run_quality_study,
    write_results,
)


BASE = Path(__file__).resolve().parent


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="比較 Agent 移除／覆蓋稽核員替換、評論校準與裁判敏感度"
    )
    parser.add_argument(
        "--simulation-dir",
        type=Path,
        default=Path("simulation") / "results",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("research") / "results",
    )
    parser.add_argument("--warmup-draws", type=int, default=60)
    parser.add_argument("--bootstrap-samples", type=int, default=2_000)
    parser.add_argument("--bootstrap-block", type=int, default=13)
    parser.add_argument(
        "--skip-ledger-verification",
        action="store_true",
        help="僅供開發 smoke test；正式研究不得使用",
    )
    args = parser.parse_args(argv)
    simulation_dir = (
        args.simulation_dir
        if args.simulation_dir.is_absolute()
        else BASE / args.simulation_dir
    )
    output_dir = (
        args.output if args.output.is_absolute() else BASE / args.output
    )
    config = QualityConfig(
        warmup_draws=args.warmup_draws,
        bootstrap_samples=args.bootstrap_samples,
        bootstrap_block=args.bootstrap_block,
    )
    print("[data] 驗證逐期帳本與無前視欄位", flush=True)
    result = run_quality_study(
        {
            SUPER: simulation_dir / f"{SUPER}.jsonl",
            LOTTO649: simulation_dir / f"{LOTTO649}.jsonl",
        },
        base=BASE,
        config=config,
        verify_ledgers=not args.skip_ledger_verification,
    )
    print("[analysis] 寫出 Agent、評論與裁判敏感度結果", flush=True)
    paths = write_results(result, output_dir)
    print(f"結論：{result['conclusion']['status']}", flush=True)
    for name, path in paths.items():
        print(f"{name}: {path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
