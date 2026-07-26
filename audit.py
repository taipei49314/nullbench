"""crucible 外部稽核 —— 專門查凍結的裁判查不到的事。

前線測試是預先寫死的,所以它涵蓋不到的缺陷永遠不會讓分數變紅。
2026-07-26 就靠手動探測抓到一個:`stop_on_first` 命中違反時 `Result.complete`
謊報 `True`(只探索 1001 個可達狀態中的 3 個)。這支把那類檢查變成常設的。

三個原則:

* **SKIP 不是 PASS。** 尚未實作的能力回報 SKIP,絕不併進通過數 —— 把「還沒做」
  算成「做對了」正是本專案要防的病灶。
* **跨程序才驗得到的東西要真的開子程序。** 雜湊種子在同一個程序內改不了。
* **不信任 crucible 自己的說法。** 反例重播只用模型宣告的 `enabled`/`successors`。

用法:
    python audit.py              # 全部
    python audit.py --json       # 機器可讀
"""

import argparse
import ast
import hashlib
import json
import os
import subprocess
import sys

def _find_repo():
    """定位 repo,讓這支在 loop 目錄與 repo 內、Windows 與 Linux 都能跑。

    搬進 repo 當 CI 關卡是既定計畫,所以不能寫死絕對路徑。
    """
    override = os.environ.get("CRUCIBLE_REPO")
    if override and os.path.isdir(override):
        return override
    here = os.path.dirname(os.path.abspath(__file__))
    for candidate in (here, os.getcwd()):
        if os.path.isdir(os.path.join(candidate, "crucible")) and \
                os.path.isfile(os.path.join(candidate, "scoreboard.py")):
            return candidate
    return r"C:\GitHub-Apps\crucible"


REPO = _find_repo()

# 裁判凍結的基準提交。
#
# 原本是 L0 的 `2d41729`。2026-07-26 因人類裁決重新凍結於 `23b6916`:
# 三條 L7 測試把 liveness 誤當 safety,其中一條斷言的事永遠不可能成立。
# 那是裁判本身的缺陷,由人修正後重新設基準 —— **不是**為了讓誰通過而搬動門檻。
# 往後任何再凍結都必須帶一則同樣性質的提交說明。
FREEZE_COMMIT = "23b6916"
JUDGE_FILES = ("scoreboard.py", "tests/test_core.py", "tests/test_frontier.py")

PYTHON_CANDIDATES = [
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Python", "Python39", "python.exe"),
    r"C:\Python311\python.exe",
    r"C:\Python312\python.exe",
]

STDLIB_OK = {
    "__future__", "abc", "argparse", "bisect", "collections", "copy", "dataclasses",
    "enum", "functools", "hashlib", "heapq", "io", "itertools", "json", "math",
    "os", "re", "sys", "typing", "unittest", "crucible",
}


class Report:
    def __init__(self):
        self.rows = []

    def add(self, name, status, detail=""):
        self.rows.append({"check": name, "status": status, "detail": detail})

    def passed(self, name, detail=""):
        self.add(name, "PASS", detail)

    def failed(self, name, detail=""):
        self.add(name, "FAIL", detail)

    def skipped(self, name, detail=""):
        self.add(name, "SKIP", detail)

    @property
    def failures(self):
        return [r for r in self.rows if r["status"] == "FAIL"]


def python_bin():
    for candidate in PYTHON_CANDIDATES:
        if candidate and os.path.isfile(candidate):
            return candidate
    return sys.executable


def run(cmd, timeout=300, env=None):
    merged = dict(os.environ)
    merged["PYTHONIOENCODING"] = "utf-8"
    if env:
        merged.update(env)
    return subprocess.run(cmd, cwd=REPO, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout, env=merged)


# --------------------------------------------------------------------------
# 檢查項
# --------------------------------------------------------------------------


def check_judge_integrity(report):
    """裁判三檔必須與凍結時位元相同。"""
    for path in JUDGE_FILES:
        proc = run(["git", "show", "{}:{}".format(FREEZE_COMMIT, path)])
        if proc.returncode != 0:
            # 完整性檢查「驗不了」要當成沒過,不能當成通過 —— fail-closed。
            # CI 上最可能的原因是淺層 clone:workflow 必須設 fetch-depth: 0。
            report.failed(
                "judge/" + path,
                "驗不了(取不到 {} 的原始版本;淺層 clone 需 fetch-depth: 0)".format(FREEZE_COMMIT),
            )
            continue
        frozen = proc.stdout.replace("\r\n", "\n")
        full = os.path.join(REPO, path.replace("/", os.sep))
        with open(full, "r", encoding="utf-8") as fh:
            current = fh.read().replace("\r\n", "\n")
        if hashlib.sha256(frozen.encode()).digest() == hashlib.sha256(current.encode()).digest():
            report.passed("judge/" + path, "與凍結版本相同")
        else:
            report.failed("judge/" + path, "裁判已被修改")


def _sources():
    """逐一產出 (檔名, 已解析的 AST)。

    刻意用 AST 而不是逐行正則:2026-07-26 的第一版拿
    `^\\s*(?:import|from)\\s+(\\w+)` 掃行,結果把 `reduce.py` docstring 裡的
    「from a reduced model can still be replayed...」判成 import 了模組 `a`。
    會誤報的稽核器比沒有稽核器更糟 —— 它會訓練人忽略警報。
    """
    pkg = os.path.join(REPO, "crucible")
    for name in sorted(os.listdir(pkg)):
        if not name.endswith(".py"):
            continue
        with open(os.path.join(pkg, name), "r", encoding="utf-8") as fh:
            source = fh.read()
        yield name, ast.parse(source, filename=name)


def check_purity(report):
    """crucible/ 底下不得引入第三方套件。"""
    offenders = []
    for name, tree in _sources():
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root not in STDLIB_OK:
                        offenders.append("{}:{} import {}".format(name, node.lineno, alias.name))
            elif isinstance(node, ast.ImportFrom):
                if node.level:          # 相對匯入 = 套件內部,不是第三方
                    continue
                root = (node.module or "").split(".")[0]
                if root not in STDLIB_OK:
                    offenders.append("{}:{} from {}".format(name, node.lineno, node.module))
    if offenders:
        report.failed("purity/stdlib-only", "; ".join(offenders[:5]))
    else:
        report.passed("purity/stdlib-only", "只用標準函式庫")


NONDETERMINISTIC_MODULES = {"random", "time", "datetime", "uuid", "secrets"}
NONDETERMINISTIC_CALLS = {"now", "today", "time", "random", "shuffle", "choice", "uuid4", "id"}


def check_determinism_sources(report):
    """不得依賴亂數、時間、物件位址。同樣走 AST,不掃註解與文件字串。"""
    offenders = []
    for name, tree in _sources():
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in NONDETERMINISTIC_MODULES:
                        offenders.append("{}:{} import {}".format(name, node.lineno, alias.name))
            elif isinstance(node, ast.ImportFrom):
                if not node.level and (node.module or "").split(".")[0] in NONDETERMINISTIC_MODULES:
                    offenders.append("{}:{} from {}".format(name, node.lineno, node.module))
            elif isinstance(node, ast.Call):
                func = node.func
                called = getattr(func, "attr", None) or getattr(func, "id", None)
                if called in NONDETERMINISTIC_CALLS:
                    offenders.append("{}:{} {}()".format(name, node.lineno, called))
    if offenders:
        report.failed("determinism/sources", "; ".join(offenders[:5]))
    else:
        report.passed("determinism/sources", "無亂數／時間／物件位址依賴")


def check_hash_seed_stability(report):
    """跨程序:不同 PYTHONHASHSEED 下計分板輸出必須位元相同。

    同一個程序內改不了雜湊種子,所以這條非開子程序不可 ——
    而這正是「探索順序偷偷洩漏 set/dict 迭代序」唯一驗得到的方式。
    """
    digests = {}
    for seed in ("0", "1", "42", "12345"):
        proc = run([python_bin(), "scoreboard.py"], env={"PYTHONHASHSEED": seed})
        if proc.returncode != 0:
            report.failed("determinism/hash-seed", "seed={} 計分板失敗".format(seed))
            return
        digests[seed] = hashlib.sha256(proc.stdout.encode()).hexdigest()[:16]
    unique = set(digests.values())
    if len(unique) == 1:
        report.passed("determinism/hash-seed", "四種種子輸出相同 ({})".format(unique.pop()))
    else:
        report.failed("determinism/hash-seed", json.dumps(digests))


PROBE = r'''
import sys
sys.path.insert(0, ".")
import json
from crucible import Action, Checker, Invariant, Model, State

class Chain(Model):
    """一條長度 N 的鏈:可達狀態數必定是 N+1。"""
    def __init__(self, n):
        self.n = n
    def init(self):
        yield State({"n": 0})
    def actions(self):
        yield Action("inc", lambda s: s["n"] < self.n, lambda s: [s.set("n", s["n"] + 1)])

out = []
for length, bound in ((1000, 2), (50, 10), (20, 20)):
    model = Chain(length)
    truth = Checker(model).check().states_explored          # 無不變量 -> 真的窮舉
    got = Checker(model, [Invariant("under", lambda s, b=bound: s["n"] < b)]).check()
    out.append({
        "length": length, "bound": bound,
        "reachable": truth, "explored": got.states_explored,
        "complete": got.complete, "ok": got.ok,
    })
print(json.dumps(out))
'''


def check_complete_honesty(report):
    """`complete=True` 必須真的代表看遍了所有可達狀態。

    這是 2026-07-26 手動抓到的那個缺陷:提前收工卻宣稱窮舉完畢。
    """
    probe_path = os.path.join(os.environ.get("TEMP", "."), "crucible_probe_complete.py")
    with open(probe_path, "w", encoding="utf-8") as fh:
        fh.write(PROBE)
    proc = run([python_bin(), probe_path])
    if proc.returncode != 0:
        report.failed("honesty/complete", (proc.stderr or proc.stdout).strip()[-300:])
        return
    try:
        cases = json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        report.failed("honesty/complete", "探測輸出無法解析:" + proc.stdout.strip()[-200:])
        return

    liars = [c for c in cases if c["complete"] and c["explored"] != c["reachable"]]
    if liars:
        worst = min(liars, key=lambda c: c["explored"] / float(c["reachable"]))
        report.failed(
            "honesty/complete",
            "宣稱 complete 但只探索 {}/{} 個可達狀態(bound={})".format(
                worst["explored"], worst["reachable"], worst["bound"]),
        )
    else:
        report.passed("honesty/complete", "{} 個情境下 complete 都名副其實".format(len(cases)))


REPLAY_PROBE = r'''
import sys
sys.path.insert(0, ".")
import json

try:
    from crucible import protocols
except Exception as exc:
    print(json.dumps({"available": False, "reason": str(exc)}))
    raise SystemExit(0)

from crucible import Checker

def replay(model, trace):
    """只用模型自己宣告的語意重走軌跡。不碰 crucible 的重播程式碼。"""
    if trace.initial not in list(model.init()):
        return None, "initial state not declared"
    by_name = {}
    for act in model.actions():
        by_name[act.name] = act
    current = trace.initial
    for index, (name, expected) in enumerate(trace.steps):
        act = by_name.get(name)
        if act is None:
            return None, "step %d unknown action %s" % (index, name)
        if not act.enabled(current):
            return None, "step %d action %s not enabled" % (index, name)
        if expected not in list(act.successors(current)):
            return None, "step %d not a real successor" % index
        current = expected
    return current, None

names = sorted(protocols.catalog())
results = []
for name in names:
    model, invariants = getattr(protocols, name)()
    invariants = list(invariants)
    result = Checker(model, invariants).check()
    row = {"name": name, "ok": result.ok, "complete": result.complete}
    if not result.ok:
        final, err = replay(model, result.violation.trace)
        if err:
            row["replay"] = "BROKEN: " + err
        else:
            named = dict((i.name, i) for i in invariants)
            inv = named.get(result.violation.invariant)
            row["replay"] = "ok" if (inv and not inv.holds(final)) else "BROKEN: final state does not violate"
        row["steps"] = len(result.violation.trace)
    results.append(row)
print(json.dumps({"available": True, "results": results}))
'''


def check_protocol_counterexamples(report):
    """協定庫:正確版不得誤報,錯誤版的反例必須能獨立重播。"""
    probe_path = os.path.join(os.environ.get("TEMP", "."), "crucible_probe_replay.py")
    with open(probe_path, "w", encoding="utf-8") as fh:
        fh.write(REPLAY_PROBE)
    try:
        proc = run([python_bin(), probe_path], timeout=900)
    except subprocess.TimeoutExpired:
        report.failed("protocols/replay", "探測逾時")
        return
    if proc.returncode != 0:
        report.failed("protocols/replay", (proc.stderr or "").strip()[-300:])
        return
    try:
        payload = json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        report.failed("protocols/replay", "探測輸出無法解析")
        return

    if not payload.get("available"):
        report.skipped("protocols/replay", "crucible.protocols 尚未實作(L8)")
        return

    broken, false_positive = [], []
    for row in payload["results"]:
        if row["name"].endswith("_broken"):
            if row["ok"]:
                broken.append(row["name"] + ": 沒抓到")
            elif str(row.get("replay", "")).startswith("BROKEN"):
                broken.append("{}: {}".format(row["name"], row["replay"]))
        else:
            if not row["ok"]:
                false_positive.append(row["name"] + ": 誤報")
            elif not row["complete"]:
                false_positive.append(row["name"] + ": 未窮舉完")
    problems = broken + false_positive
    if problems:
        report.failed("protocols/replay", "; ".join(problems[:6]))
    else:
        report.passed("protocols/replay",
                      "{} 個協定全部名副其實".format(len(payload["results"])))


# --------------------------------------------------------------------------


def main(argv=None):
    parser = argparse.ArgumentParser(description="crucible external audit")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    report = Report()
    check_judge_integrity(report)
    check_purity(report)
    check_determinism_sources(report)
    check_hash_seed_stability(report)
    check_complete_honesty(report)
    check_protocol_counterexamples(report)

    if args.json:
        print(json.dumps(report.rows, ensure_ascii=False, indent=2))
    else:
        width = max(len(r["check"]) for r in report.rows)
        for row in report.rows:
            print("{:4}  {:<{w}}  {}".format(row["status"], row["check"], row["detail"], w=width))
        skips = sum(1 for r in report.rows if r["status"] == "SKIP")
        print("")
        print("{} 項通過 / {} 項失敗 / {} 項尚未可測".format(
            sum(1 for r in report.rows if r["status"] == "PASS"),
            len(report.failures), skips))

    return 1 if report.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
