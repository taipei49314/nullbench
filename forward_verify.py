"""前向終局裁判 A/B 的分階段完整驗收入口。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

from engine.env import Env
from engine.forward_lab import reconcile_forward_registry
from engine.games import LOTTO649, SUPER


ROOT = Path(__file__).resolve().parent
STAGE_TESTS = (
    (
        "forward_core",
        (
            "tests/test_forward_lab.py",
            "tests/test_qwen_judge.py",
        ),
    ),
    (
        "sync_integration",
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


def verify_forward_result(result: dict) -> None:
    failures = []
    summary = result.get("summary", {})
    verification = summary.get("verification", {})
    if verification.get("chain_valid") is not True:
        failures.append("hash_chain")
    if verification.get("registrations", 0) < 2:
        failures.append("registrations")
    if summary.get("evidence_status") not in {
        "collecting_forward_data",
        "qwen_advantage_supported",
        "qwen_advantage_not_supported",
    }:
        failures.append("evidence_status")
    registrations = result.get("registrations", {})
    if set(registrations) != {SUPER, LOTTO649}:
        failures.append("game_coverage")
    elif any(
        registration.get("status") not in {"created", "existing"}
        or not registration.get("registration_hash")
        for registration in registrations.values()
    ):
        failures.append("registration_contract")
    games = summary.get("games", {})
    if set(games) != {SUPER, LOTTO649}:
        failures.append("summary_games")
    if failures:
        raise RuntimeError(
            "前向終局裁判 A/B 驗收失敗：" + ", ".join(failures)
        )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="前向 A/B 分階段測試、目前下一期凍結與完整驗收"
    )
    parser.add_argument(
        "--tests-only",
        action="store_true",
        help="只跑階段與全套測試，不操作本地前向帳本",
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
        manifest_path = ROOT / "simulation" / "results" / "manifest.json"
        if not manifest_path.exists():
            raise RuntimeError(
                "找不到 simulation/results/manifest.json；"
                "請先執行 python lotto.py loop"
            )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        print("[formal] settle and preregister current forward targets", flush=True)
        result = reconcile_forward_registry(
            ROOT,
            env.store,
            manifest,
        )
        verify_forward_result(result)

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
        raise RuntimeError("前向 A/B 驗收期間正式 records/ 遭到修改")
    print("[gate-test] git_diff_check", flush=True)
    _run(["git", "diff", "--check"])
    print(
        "前向終局裁判 A/B 各階段、帳本、前端與完整測試均通過。",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
