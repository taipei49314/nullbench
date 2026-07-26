#!/usr/bin/env python3
"""計分板 —— 唯一裁判。

這個檔案是驗收基準的一部分,**不可修改**。任何改動都會被自動還原並記為違規。

用法:

    python scoreboard.py            # 輸出 JSON
    python scoreboard.py --pretty   # 人類可讀

計分規則:

* `core_green` 為 false 時,該輪進展分直接歸零 —— 回歸網優先於一切。
* 主計分 `score` = 前線通過的測試數。
* 前線全數攻下後,`extra`(自行新增的測試)才開始計入進展。

刻意用純標準函式庫的 `unittest`:計分直接讀 `TestResult` 物件,
不解析任何文字輸出 —— 解析輸出是計分板最常見的失真來源。
"""

import argparse
import io
import json
import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
TESTS_DIR = os.path.join(REPO_ROOT, "tests")

CORE_MODULE = "tests.test_core"
FRONTIER_MODULE = "tests.test_frontier"
JUDGE_MODULES = (CORE_MODULE, FRONTIER_MODULE)


def _run(module_name):
    """跑一個測試模組,回傳 (總數, 通過數, 失敗的測試 id 清單)。"""
    loader = unittest.TestLoader()
    try:
        suite = loader.loadTestsFromName(module_name)
    except Exception as exc:  # 模組本身壞掉 —— 當成零通過,不要讓計分板自己崩掉
        return 0, 0, ["%s: import failed: %s" % (module_name, exc)]

    runner = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0)
    result = runner.run(suite)

    broken = sorted(str(case.id()) for case, _ in list(result.failures) + list(result.errors))
    skipped = len(getattr(result, "skipped", ()))
    passed = result.testsRun - len(result.failures) - len(result.errors) - skipped
    return result.testsRun, max(passed, 0), broken


def _extra_modules():
    """使用者自行新增的測試模組(除了裁判那兩個以外的 test_*.py)。"""
    if not os.path.isdir(TESTS_DIR):
        return []
    names = []
    for entry in sorted(os.listdir(TESTS_DIR)):
        if not entry.startswith("test_") or not entry.endswith(".py"):
            continue
        module = "tests." + entry[: -len(".py")]
        if module not in JUDGE_MODULES:
            names.append(module)
    return names


def collect():
    if REPO_ROOT not in sys.path:
        sys.path.insert(0, REPO_ROOT)

    core_total, core_passed, core_broken = _run(CORE_MODULE)
    core_green = core_total > 0 and core_passed == core_total

    front_total, front_passed, front_broken = _run(FRONTIER_MODULE)

    extra_total = extra_passed = 0
    extra_names = _extra_modules()
    for name in extra_names:
        total, passed, _ = _run(name)
        extra_total += total
        extra_passed += passed

    frontier_clear = front_total > 0 and front_passed == front_total

    return {
        "core": {
            "total": core_total,
            "passed": core_passed,
            "green": core_green,
            "failing": core_broken,
        },
        "frontier": {
            "total": front_total,
            "passed": front_passed,
            "remaining": front_total - front_passed,
            "failing": front_broken,
        },
        "extra": {
            "modules": extra_names,
            "total": extra_total,
            "passed": extra_passed,
            "counts_toward_score": frontier_clear,
        },
        "core_green": core_green,
        "score": front_passed + (extra_passed if frontier_clear else 0),
        "frontier_clear": frontier_clear,
    }


def _pretty(report):
    core, front, extra = report["core"], report["frontier"], report["extra"]
    lines = [
        "core     %d/%d  %s" % (core["passed"], core["total"], "GREEN" if core["green"] else "RED"),
        "frontier %d/%d  (%d remaining)" % (front["passed"], front["total"], front["remaining"]),
        "extra    %d/%d  %s"
        % (
            extra["passed"],
            extra["total"],
            "counted" if extra["counts_toward_score"] else "not counted yet",
        ),
        "score    %d" % report["score"],
    ]
    if not core["green"]:
        lines.append("")
        lines.append("CORE IS RED -- progress score is zero until this is fixed:")
        for name in core["failing"][:20]:
            lines.append("  " + name)
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="crucible scoreboard")
    parser.add_argument("--pretty", action="store_true", help="human readable output")
    parser.add_argument(
        "--require-core",
        action="store_true",
        help="exit non-zero when the regression net is red (for CI)",
    )
    args = parser.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:  # pragma: no cover - Python < 3.7
        pass

    report = collect()
    if args.pretty:
        print(_pretty(report))
    else:
        print(json.dumps(report, indent=2, sort_keys=True))

    if args.require_core and not report["core_green"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
