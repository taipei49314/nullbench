"""桌機無人值守 Loop 的分階段完整驗收入口。"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys

from engine.automation import read_status, verify_history
from engine.env import Env


ROOT = Path(__file__).resolve().parent
STAGE_TESTS = (
    (
        "automation_core",
        (
            "tests/test_automation.py",
            "tests/test_automation_verify.py",
        ),
    ),
    (
        "sync_and_forward_contract",
        (
            "tests/test_sync_service.py",
            "tests/test_forward_lab.py",
        ),
    ),
)


def tree_hash(path: Path) -> str:
    digest = hashlib.sha256()
    for file in sorted(item for item in path.rglob("*") if item.is_file()):
        digest.update(file.relative_to(path).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(file.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _run(command: list[str], *, cwd: Path = ROOT) -> None:
    executable = shutil.which(command[0])
    resolved = [executable or command[0], *command[1:]]
    subprocess.run(resolved, cwd=cwd, check=True)


def stage_test_commands(
    python: str = sys.executable,
) -> list[tuple[str, list[str]]]:
    return [
        (
            stage,
            [
                python,
                "-B",
                "-X",
                "utf8",
                "-m",
                "pytest",
                *targets,
                "-q",
                "-p",
                "no:cacheprovider",
            ],
        )
        for stage, targets in STAGE_TESTS
    ]


def verify_runtime(base: Path) -> dict:
    status = read_status(base)
    history = verify_history(base)
    failures = []
    if status.get("watcher_state") != "online":
        failures.append("watcher_online")
    if status.get("status") not in {"running", "done"}:
        failures.append("cycle_status")
    if not status.get("last_success_at"):
        failures.append("last_success")
    if int(status.get("consecutive_failures", 0)) != 0:
        failures.append("consecutive_failures")
    if history.get("chain_valid") is not True:
        failures.append("history_chain")
    if history.get("successes", 0) < 1:
        failures.append("history_success")
    if failures:
        raise RuntimeError("桌機背景 Loop 驗收失敗：" + ", ".join(failures))
    return {"status": status, "history": history}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="桌機背景 Loop 分階段、故障恢復、前端與帳本驗收"
    )
    parser.add_argument(
        "--tests-only",
        action="store_true",
        help="不要求本機 Vite watcher 正在線上",
    )
    args = parser.parse_args(argv)
    env = Env(ROOT)
    records_before = tree_hash(env.records)

    for stage, command in stage_test_commands():
        print(f"[gate-test] {stage}", flush=True)
        _run(command)

    full_suite = [
        sys.executable,
        "-B",
        "-X",
        "utf8",
        "-m",
        "pytest",
        "tests",
        "-q",
        "-p",
        "no:cacheprovider",
    ]
    print("[gate-test] full_suite_pre", flush=True)
    _run(full_suite)

    if not args.tests_only:
        print("[formal] verify live desktop watcher and history chain", flush=True)
        runtime = verify_runtime(ROOT)
        print(
            f"[formal] cycles={runtime['history']['cycles']} "
            f"successes={runtime['history']['successes']}",
            flush=True,
        )

    print("[gate-test] frontend_test", flush=True)
    _run(["npm", "test", "--", "--run"], cwd=ROOT / "frontend")
    print("[gate-test] frontend_lint", flush=True)
    _run(["npm", "run", "lint"], cwd=ROOT / "frontend")
    print("[gate-test] frontend_build", flush=True)
    _run(["npm", "run", "build"], cwd=ROOT / "frontend")
    print("[gate-test] full_suite_post", flush=True)
    _run(full_suite)

    records_after = tree_hash(env.records)
    if records_before != records_after:
        raise RuntimeError("背景 Loop 驗收期間正式 records/ 遭到修改")
    print("[gate-test] git_diff_check", flush=True)
    _run(["git", "diff", "--check"])
    print("桌機背景 Loop、故障恢復、前端與完整測試均通過。", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
