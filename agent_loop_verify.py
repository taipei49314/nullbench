"""逐期 agent 閉環的一鍵正式驗證。

順序：
1. 專用測試。
2. 全專案測試。
3. 完整歷史回放兩次，驗證位元級重現與 JSONL 雜湊鏈。
4. 再跑全專案測試，並確認正式 records 樹完全未變。
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

from engine.agent_loop import run_all, verify_replay
from engine.env import Env
from engine.games import LOTTO649, SUPER


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "simulation" / "results"


def tree_hash(path: Path) -> str:
    digest = hashlib.sha256()
    for file in sorted(item for item in path.rglob("*") if item.is_file()):
        digest.update(file.relative_to(path).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(file.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def run_tests(label: str, *targets: str) -> None:
    print(f"\n== {label} ==")
    command = [sys.executable, "-X", "utf8", "-m", "pytest", *targets, "-q"]
    completed = subprocess.run(command, cwd=ROOT)
    if completed.returncode:
        raise SystemExit(completed.returncode)


def main() -> None:
    env = Env(ROOT)
    records_before = tree_hash(env.records)

    run_tests("階段 1：逐期 agent 閉環專用測試", "tests/test_agent_loop.py")
    run_tests("階段 2：全專案前置回歸測試", "tests")

    print("\n== 階段 3：第一次完整歷史回放 ==")
    first = run_all(env.store, RESULTS)
    first_hashes = {
        game: first["games"][game]["ledger_sha256"] for game in (SUPER, LOTTO649)
    }

    print("\n== 階段 4：第二次完整回放與位元重現驗證 ==")
    second = run_all(env.store, RESULTS)
    second_hashes = {
        game: second["games"][game]["ledger_sha256"] for game in (SUPER, LOTTO649)
    }
    if first_hashes != second_hashes:
        raise RuntimeError("兩次完整回放的 JSONL SHA-256 不一致")
    for game in (SUPER, LOTTO649):
        expected = len(env.store.draws(game))
        verified = verify_replay(RESULTS / f"{game}.jsonl", expected)
        if verified["ledger_sha256"] != second_hashes[game]:
            raise RuntimeError(f"{game} 驗證雜湊與總表不一致")

    run_tests("階段 5：全專案後置回歸測試", "tests")
    records_after = tree_hash(env.records)
    if records_before != records_after:
        raise RuntimeError("正式 records/ 在 agent 閉環驗證期間遭到修改")

    print("\n== 全部通過 ==")
    for game in (SUPER, LOTTO649):
        result = second["games"][game]
        print(
            f"{result['game_name']}：{result['draws_replayed']} 期｜"
            f"ledger SHA-256 {result['ledger_sha256']}"
        )
    print(f"manifest_hash：{second['manifest_hash']}")
    print(f"records tree hash（前後一致）：{records_after}")


if __name__ == "__main__":
    main()
