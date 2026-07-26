"""前線 —— 尚未實作的能力。轉綠即為進展。

這個檔案是驗收基準的一部分,**不可修改**。任何改動都會被自動還原並記為違規。
若你認為某條測試寫錯了,在回覆裡說明理由由人類裁決,不要自己動手。

## 為什麼這個檔案有防作弊設計

模型檢查器最容易犯的錯是「宣稱檢查過但其實沒檢查到」。所以凡是牽涉反例的測試,
都用 `_replay` 把軌跡**重走一遍**再確認 —— 而 `_replay` 只使用模型自己宣告的
action 語意(`enabled` / `successors`),**不呼叫 crucible 的任何重播程式碼**。

假的軌跡、特判出來的漂亮字串、憑空捏造的步驟,都會在重播時被拆穿。

## 為什麼所有 import 都寫在測試內部

模組層級的 `from crucible import X` 會在 X 還不存在時讓**整個檔案**收集失敗,
那樣計分板就數不出個別進展。把取用延後到測試內部,缺什麼就只有那一條紅。
"""

import importlib
import unittest

from crucible import Action, Invariant, Model, State


# --------------------------------------------------------------------------
# 取用尚未存在的 API 的輔助工具
# --------------------------------------------------------------------------


def api(name):
    """取 `crucible.<name>`,不存在就讓這一條(而且只有這一條)紅。"""
    module = importlib.import_module("crucible")
    obj = getattr(module, name, None)
    if obj is None:
        raise AssertionError("crucible.%s is not implemented yet" % name)
    return obj


def submodule(path):
    """匯入子模組,不存在就讓這一條紅。"""
    try:
        return importlib.import_module(path)
    except ImportError as exc:
        raise AssertionError("%s is not implemented yet (%s)" % (path, exc))


def member(path, name):
    mod = submodule(path)
    obj = getattr(mod, name, None)
    if obj is None:
        raise AssertionError("%s.%s is not implemented yet" % (path, name))
    return obj


# --------------------------------------------------------------------------
# 獨立重播 —— 防作弊的核心
# --------------------------------------------------------------------------


def _replay(case, model, trace):
    """只用模型自己的 action 語意重走軌跡,回傳最終狀態。

    刻意不碰 crucible 的重播程式碼:這裡自己查 guard、自己算後繼、自己比對。
    """
    initials = list(model.init())
    case.assertIn(
        trace.initial, initials, "trace does not start from a declared initial state"
    )

    declared = list(model.actions())
    by_name = {}
    for act in declared:
        by_name[act.name] = act

    current = trace.initial
    for index, step in enumerate(trace.steps):
        name, expected = step
        action = by_name.get(name)
        case.assertIsNotNone(action, "step %d names unknown action %r" % (index, name))
        case.assertTrue(
            action.enabled(current),
            "step %d: action %r is not enabled in %r" % (index, name, current),
        )
        successors = list(action.successors(current))
        case.assertIn(
            expected,
            successors,
            "step %d: %r is not a successor of %r under %r"
            % (index, expected, current, name),
        )
        current = expected
    return current


def _confirm_violation(case, model, invariants, violation):
    """重播反例並確認它真的違反了它宣稱的那個不變量。"""
    final = _replay(case, model, violation.trace)
    case.assertEqual(final, violation.trace.final, "trace.final disagrees with replay")

    named = {inv.name: inv for inv in invariants}
    case.assertIn(violation.invariant, named, "violation names an unknown invariant")
    case.assertFalse(
        named[violation.invariant].holds(final),
        "replayed final state does not actually violate %r" % violation.invariant,
    )


# --------------------------------------------------------------------------
# 測試用模型
# --------------------------------------------------------------------------


class Counter(Model):
    def __init__(self, limit=10):
        self.limit = limit

    def init(self):
        yield State({"n": 0})

    def actions(self):
        yield Action(
            "inc", lambda s: s["n"] < self.limit, lambda s: [s.set("n", s["n"] + 1)]
        )


class Grid(Model):
    """在 size x size 的格子上走動 —— 狀態數可控地成長。"""

    def __init__(self, size=4):
        self.size = size

    def init(self):
        yield State({"x": 0, "y": 0})

    def actions(self):
        yield Action(
            "right", lambda s: s["x"] < self.size - 1, lambda s: [s.set("x", s["x"] + 1)]
        )
        yield Action(
            "up", lambda s: s["y"] < self.size - 1, lambda s: [s.set("y", s["y"] + 1)]
        )


class Deadlocking(Model):
    """走到 n == 2 就再也沒有啟用動作。"""

    def init(self):
        yield State({"n": 0})

    def actions(self):
        yield Action("step", lambda s: s["n"] < 2, lambda s: [s.set("n", s["n"] + 1)])


class Ping(Model):
    """在 a / b 之間永遠來回 —— 沒有終止狀態,永遠到不了 c。"""

    def init(self):
        yield State({"at": "a"})

    def actions(self):
        yield Action("to_b", lambda s: s["at"] == "a", lambda s: [s.set("at", "b")])
        yield Action("to_a", lambda s: s["at"] == "b", lambda s: [s.set("at", "a")])


class LazyCounter(Model):
    """有一個永遠啟用的閒置動作 —— 沒有公平性假設時 `inc` 可能被永遠餓死。

    這是公平性測試的關鍵:一直挑 `idle` 的那條無限執行永遠到不了 n == 2,
    但弱公平性說「持續啟用的動作不得被永遠忽略」,於是那條執行被排除。
    """

    def init(self):
        yield State({"n": 0, "tick": 0})

    def actions(self):
        yield Action("inc", lambda s: s["n"] < 2, lambda s: [s.set("n", s["n"] + 1)])
        yield Action("idle", lambda s: True, lambda s: [s.set("tick", 1 - s["tick"])])


class Noisy(Model):
    """一條沒用的支線 + 一條會踩雷的主線 —— 用來測軌跡最小化。"""

    def init(self):
        yield State({"n": 0, "noise": 0})

    def actions(self):
        yield Action(
            "inc", lambda s: s["n"] < 3, lambda s: [s.set("n", s["n"] + 1)]
        )
        yield Action(
            "noise", lambda s: s["noise"] < 3, lambda s: [s.set("noise", s["noise"] + 1)]
        )


def under(limit):
    return Invariant("under_%d" % limit, lambda s: s["n"] < limit)


# ==========================================================================
# L1 —— 探索核心:邊界、死結、搜尋策略、決定性
# ==========================================================================


class TestL1Bounds(unittest.TestCase):
    def test_max_depth_truncates_exploration(self):
        Checker = api("Checker")
        result = Checker(Counter(limit=10), max_depth=3).check()
        self.assertEqual(result.states_explored, 4)

    def test_max_depth_reports_incomplete(self):
        Checker = api("Checker")
        self.assertFalse(Checker(Counter(limit=10), max_depth=3).check().complete)

    def test_exhausted_search_reports_complete(self):
        Checker = api("Checker")
        self.assertTrue(Checker(Counter(limit=3)).check().complete)

    def test_max_depth_zero_explores_only_initial_states(self):
        Checker = api("Checker")
        self.assertEqual(Checker(Counter(limit=10), max_depth=0).check().states_explored, 1)

    def test_max_states_caps_the_search(self):
        Checker = api("Checker")
        result = Checker(Counter(limit=1000), max_states=5).check()
        self.assertLessEqual(result.states_explored, 5)

    def test_max_states_reports_incomplete(self):
        Checker = api("Checker")
        self.assertFalse(Checker(Counter(limit=1000), max_states=5).check().complete)

    def test_max_depth_still_reports_reached_depth(self):
        Checker = api("Checker")
        self.assertEqual(Checker(Counter(limit=10), max_depth=3).check().max_depth_reached, 3)

    def test_bounds_do_not_hide_a_violation_within_range(self):
        Checker = api("Checker")
        result = Checker(Counter(limit=10), [under(2)], max_depth=5).check()
        self.assertFalse(result.ok)

    def test_bounds_can_leave_a_deep_violation_unfound(self):
        Checker = api("Checker")
        result = Checker(Counter(limit=10), [under(9)], max_depth=3).check()
        self.assertTrue(result.ok)
        self.assertFalse(result.complete, "an unfinished search must not claim completeness")

    def test_negative_max_depth_is_rejected(self):
        Checker = api("Checker")
        with self.assertRaises(ValueError):
            Checker(Counter(), max_depth=-1).check()

    def test_zero_max_states_is_rejected(self):
        Checker = api("Checker")
        with self.assertRaises(ValueError):
            Checker(Counter(), max_states=0).check()


class TestL1Deadlocks(unittest.TestCase):
    def test_deadlock_states_are_reported(self):
        Checker = api("Checker")
        self.assertEqual(Checker(Deadlocking()).check().deadlocks, (State({"n": 2}),))

    def test_model_without_deadlock_reports_none(self):
        Checker = api("Checker")
        self.assertEqual(Checker(Ping()).check().deadlocks, ())

    def test_deadlocks_are_deterministically_ordered(self):
        Checker = api("Checker")

        class ManyEnds(Model):
            def init(self):
                yield State({"n": 0})

            def actions(self):
                yield Action(
                    "split",
                    lambda s: s["n"] == 0,
                    lambda s: [s.set("n", 3), s.set("n", 1), s.set("n", 2)],
                )

        runs = {Checker(ManyEnds()).check().deadlocks for _ in range(5)}
        self.assertEqual(len(runs), 1)

    def test_truncated_search_does_not_claim_deadlocks(self):
        Checker = api("Checker")
        result = Checker(Counter(limit=10), max_depth=2).check()
        self.assertEqual(result.deadlocks, ())


class TestL1Search(unittest.TestCase):
    def test_bfs_is_the_default(self):
        Checker = api("Checker")
        self.assertEqual(Checker(Counter(limit=5)).check().search, "bfs")

    def test_dfs_is_selectable(self):
        Checker = api("Checker")
        self.assertEqual(Checker(Counter(limit=5), search="dfs").check().search, "dfs")

    def test_dfs_explores_the_same_state_space(self):
        Checker = api("Checker")
        bfs = Checker(Grid(size=4)).check().states_explored
        dfs = Checker(Grid(size=4), search="dfs").check().states_explored
        self.assertEqual(bfs, dfs)

    def test_dfs_agrees_with_bfs_on_the_verdict(self):
        Checker = api("Checker")
        inv = [Invariant("no_corner", lambda s: not (s["x"] == 3 and s["y"] == 3))]
        self.assertEqual(
            Checker(Grid(size=4), inv).check().ok,
            Checker(Grid(size=4), inv, search="dfs").check().ok,
        )

    def test_unknown_search_strategy_is_rejected(self):
        Checker = api("Checker")
        with self.assertRaises(ValueError):
            Checker(Counter(), search="astral-projection").check()

    def test_dfs_counterexample_is_replayable(self):
        Checker = api("Checker")
        model, invs = Counter(limit=10), [under(4)]
        violation = Checker(model, invs, search="dfs").check().violation
        _confirm_violation(self, model, invs, violation)


class TestL1Determinism(unittest.TestCase):
    def test_dfs_is_deterministic(self):
        Checker = api("Checker")
        traces = {
            Checker(Noisy(), [under(3)], search="dfs").check().violation.trace.format()
            for _ in range(5)
        }
        self.assertEqual(len(traces), 1)

    def test_bounded_runs_are_deterministic(self):
        Checker = api("Checker")
        counts = {
            Checker(Grid(size=6), max_states=17).check().states_explored for _ in range(5)
        }
        self.assertEqual(len(counts), 1)

    def test_state_count_is_independent_of_hash_seed(self):
        # PYTHONHASHSEED 會改變 str 的雜湊值。探索順序若洩漏了 set/dict 的迭代序,
        # 這條就會抖。同一程序內測不到種子差異,但可以測「不看雜湊值也該一致」。
        Checker = api("Checker")
        grid = Grid(size=5)
        self.assertEqual(
            Checker(grid).check().states_explored, Checker(Grid(size=5)).check().states_explored
        )


class TestL1Scale(unittest.TestCase):
    def test_handles_a_few_thousand_states(self):
        Checker = api("Checker")
        result = Checker(Grid(size=40)).check()
        self.assertEqual(result.states_explored, 1600)

    def test_reports_progress_counters(self):
        Checker = api("Checker")
        result = Checker(Grid(size=10)).check()
        self.assertEqual(result.states_explored, 100)
        self.assertEqual(result.max_depth_reached, 18)


# ==========================================================================
# L2 —— 安全性質與反例品質
# ==========================================================================


class TestL2ShortestCounterexample(unittest.TestCase):
    def test_bfs_finds_the_shortest_counterexample(self):
        Checker = api("Checker")
        result = Checker(Noisy(), [under(3)]).check()
        self.assertEqual(len(result.violation.trace), 3)

    def test_shortest_counterexample_contains_no_irrelevant_action(self):
        Checker = api("Checker")
        names = [n for n, _ in Checker(Noisy(), [under(3)]).check().violation.trace.steps]
        self.assertEqual(names, ["inc", "inc", "inc"])

    def test_shortest_counterexample_is_replayable(self):
        Checker = api("Checker")
        model, invs = Noisy(), [under(3)]
        _confirm_violation(self, model, invs, Checker(model, invs).check().violation)

    def test_grid_counterexample_is_shortest(self):
        Checker = api("Checker")
        inv = [Invariant("not_far", lambda s: s["x"] + s["y"] < 4)]
        self.assertEqual(len(Checker(Grid(size=5), inv).check().violation.trace), 4)


class TestL2MultipleInvariants(unittest.TestCase):
    def test_first_declared_invariant_wins_at_the_same_state(self):
        Checker = api("Checker")
        invs = [under(3), Invariant("also_under_3", lambda s: s["n"] < 3)]
        self.assertEqual(Checker(Counter(), invs).check().violation.invariant, "under_3")

    def test_shallower_violation_wins_over_declaration_order(self):
        Checker = api("Checker")
        invs = [under(5), under(2)]
        self.assertEqual(Checker(Counter(), invs).check().violation.invariant, "under_2")

    def test_all_violations_can_be_collected(self):
        Checker = api("Checker")
        invs = [under(2), under(4)]
        result = Checker(Counter(), invs, stop_on_first=False).check()
        self.assertEqual(
            sorted({v.invariant for v in result.violations}), ["under_2", "under_4"]
        )

    def test_violations_is_empty_when_all_hold(self):
        Checker = api("Checker")
        result = Checker(Counter(limit=2), [under(9)], stop_on_first=False).check()
        self.assertEqual(result.violations, ())

    def test_violations_has_one_entry_in_stop_on_first_mode(self):
        Checker = api("Checker")
        result = Checker(Counter(), [under(2), under(4)]).check()
        self.assertEqual(len(result.violations), 1)

    def test_every_collected_violation_is_replayable(self):
        Checker = api("Checker")
        model, invs = Counter(), [under(2), under(4)]
        result = Checker(model, invs, stop_on_first=False).check()
        for violation in result.violations:
            _confirm_violation(self, model, invs, violation)


class TestL2PredicateFailure(unittest.TestCase):
    def _exploding(self):
        def boom(state):
            raise RuntimeError("predicate exploded")

        return Invariant("explodes", boom)

    def test_raising_predicate_is_reported_as_a_violation(self):
        Checker = api("Checker")
        self.assertFalse(Checker(Counter(limit=2), [self._exploding()]).check().ok)

    def test_raising_predicate_names_the_invariant(self):
        Checker = api("Checker")
        result = Checker(Counter(limit=2), [self._exploding()]).check()
        self.assertEqual(result.violation.invariant, "explodes")

    def test_raising_predicate_records_the_error(self):
        Checker = api("Checker")
        result = Checker(Counter(limit=2), [self._exploding()]).check()
        self.assertIsInstance(result.violation.error, RuntimeError)

    def test_clean_violation_records_no_error(self):
        Checker = api("Checker")
        result = Checker(Counter(), [under(2)]).check()
        self.assertIsNone(result.violation.error)

    def test_error_appears_in_the_formatted_report(self):
        Checker = api("Checker")
        result = Checker(Counter(limit=2), [self._exploding()]).check()
        self.assertIn("predicate exploded", result.violation.format())


# ==========================================================================
# L3 —— 建模語言
# ==========================================================================


def _mutex_spec():
    """回傳一個用 DSL 宣告的兩節點互斥模型類別。"""
    dsl = submodule("crucible.dsl")
    Spec, action = dsl.Spec, dsl.action

    class Mutex(Spec):
        nodes = ("n1", "n2")

        def init(self):
            return State({"pc.n1": "idle", "pc.n2": "idle"})

        @action(params="nodes")
        def enter(self, s, node):
            if s["pc." + node] != "idle":
                return []
            return [s.set("pc." + node, "critical")]

        @action(params="nodes")
        def leave(self, s, node):
            if s["pc." + node] != "critical":
                return []
            return [s.set("pc." + node, "idle")]

    return Mutex


class TestL3Spec(unittest.TestCase):
    def test_spec_is_a_model(self):
        self.assertIsInstance(_mutex_spec()(), Model)

    def test_init_may_return_a_single_state(self):
        spec = _mutex_spec()()
        self.assertEqual(spec.initial_states(), (State({"pc.n1": "idle", "pc.n2": "idle"}),))

    def test_parametrized_actions_expand_per_parameter(self):
        names = sorted(a.name for a in _mutex_spec()().action_list())
        self.assertEqual(names, ["enter(n1)", "enter(n2)", "leave(n1)", "leave(n2)"])

    def test_empty_successor_list_means_disabled(self):
        spec = _mutex_spec()()
        enter_n1 = [a for a in spec.action_list() if a.name == "enter(n1)"][0]
        busy = State({"pc.n1": "critical", "pc.n2": "idle"})
        self.assertFalse(enter_n1.enabled(busy))

    def test_action_without_params_keeps_its_method_name(self):
        dsl = submodule("crucible.dsl")

        class Simple(dsl.Spec):
            def init(self):
                return State({"n": 0})

            @dsl.action()
            def bump(self, s):
                return [s.set("n", s["n"] + 1)] if s["n"] < 2 else []

        self.assertEqual([a.name for a in Simple().action_list()], ["bump"])

    def test_spec_explores_correctly(self):
        Checker = api("Checker")
        self.assertEqual(Checker(_mutex_spec()()).check().states_explored, 4)

    def test_spec_supports_multiple_initial_states(self):
        dsl = submodule("crucible.dsl")

        class Multi(dsl.Spec):
            def init(self):
                return [State({"n": 0}), State({"n": 5})]

            @dsl.action()
            def noop(self, s):
                return []

        self.assertEqual(len(Multi().initial_states()), 2)

    def test_spec_rejects_a_params_attribute_that_is_missing(self):
        dsl = submodule("crucible.dsl")

        class Broken(dsl.Spec):
            def init(self):
                return State({"n": 0})

            @dsl.action(params="nowhere")
            def go(self, s, x):
                return []

        with self.assertRaises(Exception):
            Broken().action_list()

    def test_spec_finds_a_mutex_violation(self):
        Checker = api("Checker")
        model = _mutex_spec()()
        invs = [
            Invariant(
                "mutual_exclusion",
                lambda s: not (s["pc.n1"] == "critical" and s["pc.n2"] == "critical"),
            )
        ]
        result = Checker(model, invs).check()
        self.assertFalse(result.ok)
        _confirm_violation(self, model, invs, result.violation)


class TestL3Network(unittest.TestCase):
    def test_network_module_exists(self):
        submodule("crucible.net")

    def test_messages_can_be_put_and_read(self):
        net = submodule("crucible.net")
        s = State({"net": net.empty()})
        s2 = net.send(s, "net", ("m1", "n1", "n2"))
        self.assertEqual(net.pending(s2, "net"), (("m1", "n1", "n2"),))

    def test_empty_network_has_no_pending_messages(self):
        net = submodule("crucible.net")
        self.assertEqual(net.pending(State({"net": net.empty()}), "net"), ())

    def test_delivering_removes_the_message(self):
        net = submodule("crucible.net")
        s = net.send(State({"net": net.empty()}), "net", ("m1", "n1", "n2"))
        self.assertEqual(net.pending(net.deliver(s, "net", ("m1", "n1", "n2")), "net"), ())

    def test_network_value_is_hashable_so_it_can_live_in_a_state(self):
        net = submodule("crucible.net")
        s = net.send(State({"net": net.empty()}), "net", ("m1", "n1", "n2"))
        self.assertEqual(hash(s), hash(s))

    def test_network_is_order_insensitive(self):
        net = submodule("crucible.net")
        base = State({"net": net.empty()})
        a = net.send(net.send(base, "net", ("x",)), "net", ("y",))
        b = net.send(net.send(base, "net", ("y",)), "net", ("x",))
        self.assertEqual(a, b, "a message bag must not depend on send order")

    def test_duplicate_messages_are_counted(self):
        net = submodule("crucible.net")
        base = State({"net": net.empty()})
        twice = net.send(net.send(base, "net", ("x",)), "net", ("x",))
        self.assertEqual(len(net.pending(twice, "net")), 2)

    def test_delivering_an_absent_message_is_rejected(self):
        net = submodule("crucible.net")
        with self.assertRaises(Exception):
            net.deliver(State({"net": net.empty()}), "net", ("ghost",))


# ==========================================================================
# L4 —— 反例最小化
# ==========================================================================


class TestL4Minimize(unittest.TestCase):
    """最小化用一條**手工編出來的**冗長軌跡當輸入。

    刻意不從 DFS 拿軌跡:那樣 L4 就綁死在 L1 上,而且 DFS 剛好吐出短軌跡時
    這些測試會變成什麼都沒驗到。手工軌跡讓「該被砍掉的步驟」是已知的。
    """

    def _long_trace(self):
        Trace = api("Trace")
        model, invs = Noisy(), [under(3)]
        # noise 與 inc 交錯:六步走到 n == 3,其中三步的 noise 與違反完全無關。
        steps = (
            ("noise", State({"n": 0, "noise": 1})),
            ("inc", State({"n": 1, "noise": 1})),
            ("noise", State({"n": 1, "noise": 2})),
            ("inc", State({"n": 2, "noise": 2})),
            ("noise", State({"n": 2, "noise": 3})),
            ("inc", State({"n": 3, "noise": 3})),
        )
        return model, invs, Trace(State({"n": 0, "noise": 0}), steps)

    def test_the_input_trace_is_itself_valid(self):
        # 先確認測資本身沒寫錯 —— 否則後面每一條都在驗假的東西。
        model, invs, trace = self._long_trace()
        final = _replay(self, model, trace)
        self.assertFalse(invs[0].holds(final))
        self.assertEqual(len(trace), 6)

    def test_minimize_module_exists(self):
        submodule("crucible.minimize")

    def test_shrink_returns_a_trace(self):
        Trace = api("Trace")
        shrink = member("crucible.minimize", "shrink")
        model, invs, trace = self._long_trace()
        self.assertIsInstance(shrink(model, invs, trace), Trace)

    def test_shrink_never_lengthens_a_trace(self):
        shrink = member("crucible.minimize", "shrink")
        model, invs, trace = self._long_trace()
        self.assertLessEqual(len(shrink(model, invs, trace)), len(trace))

    def test_shrunk_trace_is_still_replayable(self):
        shrink = member("crucible.minimize", "shrink")
        model, invs, trace = self._long_trace()
        _replay(self, model, shrink(model, invs, trace))

    def test_shrunk_trace_still_violates(self):
        shrink = member("crucible.minimize", "shrink")
        model, invs, trace = self._long_trace()
        final = _replay(self, model, shrink(model, invs, trace))
        self.assertFalse(invs[0].holds(final), "shrunk trace no longer violates")

    def test_shrink_removes_irrelevant_actions(self):
        shrink = member("crucible.minimize", "shrink")
        model, invs, trace = self._long_trace()
        names = [n for n, _ in shrink(model, invs, trace).steps]
        self.assertNotIn("noise", names)

    def test_shrink_reaches_the_optimum_on_this_model(self):
        shrink = member("crucible.minimize", "shrink")
        model, invs, trace = self._long_trace()
        self.assertEqual(len(shrink(model, invs, trace)), 3)

    def test_shrink_is_idempotent(self):
        shrink = member("crucible.minimize", "shrink")
        model, invs, trace = self._long_trace()
        once = shrink(model, invs, trace)
        self.assertEqual(len(shrink(model, invs, once)), len(once))

    def test_shrink_is_deterministic(self):
        shrink = member("crucible.minimize", "shrink")
        model, invs, trace = self._long_trace()
        shapes = {tuple(n for n, _ in shrink(model, invs, trace).steps) for _ in range(3)}
        self.assertEqual(len(shapes), 1)

    def test_shrink_leaves_an_already_minimal_trace_alone(self):
        Checker = api("Checker")
        shrink = member("crucible.minimize", "shrink")
        model, invs = Noisy(), [under(3)]
        trace = Checker(model, invs).check().violation.trace
        self.assertEqual(len(shrink(model, invs, trace)), len(trace))


# ==========================================================================
# L5 —— 時序性質
# ==========================================================================


class TestL5Properties(unittest.TestCase):
    def test_temporal_module_exists(self):
        submodule("crucible.temporal")

    def test_always_holds_on_a_safe_model(self):
        Checker = api("Checker")
        Always = member("crucible.temporal", "Always")
        prop = Always("bounded", lambda s: s["n"] <= 3)
        self.assertTrue(Checker(Counter(limit=3), properties=[prop]).check().ok)

    def test_always_is_violated_like_an_invariant(self):
        Checker = api("Checker")
        Always = member("crucible.temporal", "Always")
        prop = Always("small", lambda s: s["n"] < 2)
        result = Checker(Counter(limit=5), properties=[prop]).check()
        self.assertFalse(result.ok)
        self.assertEqual(result.violation.invariant, "small")

    def test_eventually_holds_when_every_run_reaches_the_goal(self):
        Checker = api("Checker")
        Eventually = member("crucible.temporal", "Eventually")
        prop = Eventually("reaches_two", lambda s: s["n"] == 2)
        self.assertTrue(Checker(Deadlocking(), properties=[prop]).check().ok)

    def test_eventually_fails_when_the_goal_is_unreachable(self):
        Checker = api("Checker")
        Eventually = member("crucible.temporal", "Eventually")
        prop = Eventually("reaches_c", lambda s: s["at"] == "c")
        self.assertFalse(Checker(Ping(), properties=[prop]).check().ok)

    def test_leads_to_relates_two_predicates(self):
        Checker = api("Checker")
        LeadsTo = member("crucible.temporal", "LeadsTo")
        prop = LeadsTo("start_then_end", lambda s: s["n"] == 0, lambda s: s["n"] == 2)
        self.assertTrue(Checker(Deadlocking(), properties=[prop]).check().ok)


class TestL5Lasso(unittest.TestCase):
    def _stuck(self):
        Checker = api("Checker")
        Eventually = member("crucible.temporal", "Eventually")
        prop = Eventually("reaches_c", lambda s: s["at"] == "c")
        return Ping(), Checker(Ping(), properties=[prop]).check()

    def test_liveness_violation_reports_a_cycle(self):
        _, result = self._stuck()
        self.assertIsNotNone(result.violation.cycle_start)

    def test_cycle_start_indexes_into_the_trace(self):
        _, result = self._stuck()
        trace = result.violation.trace
        self.assertLessEqual(result.violation.cycle_start, len(trace))

    def test_lasso_prefix_and_cycle_are_replayable(self):
        model, result = self._stuck()
        _replay(self, model, result.violation.trace)

    def test_lasso_cycle_actually_returns_to_a_visited_state(self):
        _, result = self._stuck()
        trace = result.violation.trace
        states = trace.states
        self.assertEqual(states[result.violation.cycle_start], states[-1])

    def test_safety_violation_has_no_cycle(self):
        Checker = api("Checker")
        self.assertIsNone(Checker(Counter(), [under(2)]).check().violation.cycle_start)


class TestL5Fairness(unittest.TestCase):
    def test_weak_fairness_is_declarable(self):
        weak_fair = member("crucible.temporal", "weak_fair")
        self.assertIsNotNone(weak_fair("inc"))

    def test_without_fairness_a_starvable_property_fails(self):
        # 一直挑 idle 的那條無限執行永遠到不了 n == 2。
        Checker = api("Checker")
        Eventually = member("crucible.temporal", "Eventually")
        prop = Eventually("counts_up", lambda s: s["n"] == 2)
        self.assertFalse(Checker(LazyCounter(), properties=[prop]).check().ok)

    def test_weak_fairness_rescues_the_same_property(self):
        # inc 在 n < 2 時持續啟用,弱公平性排除了「永遠忽略 inc」的那條執行。
        Checker = api("Checker")
        Eventually = member("crucible.temporal", "Eventually")
        weak_fair = member("crucible.temporal", "weak_fair")
        prop = Eventually("counts_up", lambda s: s["n"] == 2)
        result = Checker(
            LazyCounter(), properties=[prop], fairness=[weak_fair("inc")]
        ).check()
        self.assertTrue(result.ok, "under weak fairness inc cannot be starved forever")

    def test_starvation_counterexample_is_a_lasso(self):
        Checker = api("Checker")
        Eventually = member("crucible.temporal", "Eventually")
        prop = Eventually("counts_up", lambda s: s["n"] == 2)
        violation = Checker(LazyCounter(), properties=[prop]).check().violation
        self.assertIsNotNone(violation.cycle_start)

    def test_fairness_on_an_unknown_action_is_rejected(self):
        Checker = api("Checker")
        Eventually = member("crucible.temporal", "Eventually")
        weak_fair = member("crucible.temporal", "weak_fair")
        prop = Eventually("x", lambda s: s["n"] == 1)
        with self.assertRaises(Exception):
            Checker(
                Counter(), properties=[prop], fairness=[weak_fair("no_such_action")]
            ).check()


# ==========================================================================
# L6 —— 狀態爆炸歸約
# ==========================================================================


def _symmetric_model(node_count=3):
    """node 之間完全對稱 —— 對稱性歸約應該能大幅砍掉狀態數。"""

    nodes = tuple("n%d" % i for i in range(node_count))

    class Sym(Model):
        def init(self):
            yield State({"pc." + n: "idle" for n in nodes})

        def actions(self):
            for node in nodes:
                yield Action(
                    "enter(%s)" % node,
                    lambda s, n=node: s["pc." + n] == "idle",
                    lambda s, n=node: [s.set("pc." + n, "critical")],
                )
                yield Action(
                    "leave(%s)" % node,
                    lambda s, n=node: s["pc." + n] == "critical",
                    lambda s, n=node: [s.set("pc." + n, "idle")],
                )

    return Sym(), nodes


class TestL6Symmetry(unittest.TestCase):
    def test_reduce_module_exists(self):
        submodule("crucible.reduce")

    def test_symmetry_returns_a_model(self):
        symmetry = member("crucible.reduce", "symmetry")
        model, nodes = _symmetric_model()
        self.assertIsInstance(symmetry(model, groups=[nodes]), Model)

    def test_symmetry_reduces_the_state_count(self):
        Checker = api("Checker")
        symmetry = member("crucible.reduce", "symmetry")
        model, nodes = _symmetric_model(3)
        plain = Checker(model).check().states_explored
        reduced = Checker(symmetry(model, groups=[nodes])).check().states_explored
        self.assertLess(reduced, plain)

    def test_symmetry_preserves_a_safe_verdict(self):
        Checker = api("Checker")
        symmetry = member("crucible.reduce", "symmetry")
        model, nodes = _symmetric_model(3)
        inv = [Invariant("never_four", lambda s: True)]
        self.assertTrue(Checker(symmetry(model, groups=[nodes]), inv).check().ok)

    def test_symmetry_preserves_a_violation(self):
        Checker = api("Checker")
        symmetry = member("crucible.reduce", "symmetry")
        model, nodes = _symmetric_model(3)
        # 只數 pc.* —— 歸約若加了自己的記帳欄位,不該影響這個不變量的語意。
        inv = [
            Invariant(
                "at_most_one_critical",
                lambda s: sum(
                    1 for k in s.keys() if k.startswith("pc.") and s[k] == "critical"
                )
                <= 1,
            )
        ]
        self.assertFalse(Checker(symmetry(model, groups=[nodes]), inv).check().ok)

    def test_symmetry_verdict_matches_the_unreduced_model(self):
        Checker = api("Checker")
        symmetry = member("crucible.reduce", "symmetry")
        model, nodes = _symmetric_model(3)
        # 只數 pc.* —— 歸約若加了自己的記帳欄位,不該影響這個不變量的語意。
        inv = [
            Invariant(
                "at_most_one_critical",
                lambda s: sum(
                    1 for k in s.keys() if k.startswith("pc.") and s[k] == "critical"
                )
                <= 1,
            )
        ]
        self.assertEqual(
            Checker(model, inv).check().ok,
            Checker(symmetry(model, groups=[nodes]), inv).check().ok,
        )

    def test_symmetry_is_deterministic(self):
        Checker = api("Checker")
        symmetry = member("crucible.reduce", "symmetry")
        model, nodes = _symmetric_model(3)
        counts = {
            Checker(symmetry(model, groups=[nodes])).check().states_explored for _ in range(3)
        }
        self.assertEqual(len(counts), 1)


class TestL6PartialOrder(unittest.TestCase):
    def test_partial_order_returns_a_model(self):
        partial_order = member("crucible.reduce", "partial_order")
        self.assertIsInstance(partial_order(Grid(size=4)), Model)

    def test_partial_order_reduces_the_state_count(self):
        Checker = api("Checker")
        partial_order = member("crucible.reduce", "partial_order")
        plain = Checker(Grid(size=6)).check().states_explored
        reduced = Checker(partial_order(Grid(size=6))).check().states_explored
        self.assertLess(reduced, plain)

    def test_partial_order_preserves_a_safe_verdict(self):
        Checker = api("Checker")
        partial_order = member("crucible.reduce", "partial_order")
        inv = [Invariant("in_bounds", lambda s: s["x"] < 6 and s["y"] < 6)]
        self.assertTrue(Checker(partial_order(Grid(size=6)), inv).check().ok)

    def test_partial_order_preserves_a_violation(self):
        Checker = api("Checker")
        partial_order = member("crucible.reduce", "partial_order")
        inv = [Invariant("not_corner", lambda s: not (s["x"] == 5 and s["y"] == 5))]
        self.assertFalse(Checker(partial_order(Grid(size=6)), inv).check().ok)

    def test_partial_order_verdict_matches_the_unreduced_model(self):
        Checker = api("Checker")
        partial_order = member("crucible.reduce", "partial_order")
        inv = [Invariant("not_corner", lambda s: not (s["x"] == 5 and s["y"] == 5))]
        self.assertEqual(
            Checker(Grid(size=6), inv).check().ok,
            Checker(partial_order(Grid(size=6)), inv).check().ok,
        )


# ==========================================================================
# L7 —— 故障注入
# ==========================================================================


def _relay_model():
    """n1 送一則訊息給 n2;n2 收到就標記完成。"""
    net = submodule("crucible.net")

    class Relay(Model):
        def init(self):
            yield State({"net": net.empty(), "sent": False, "done": False})

        def actions(self):
            yield Action(
                "send",
                lambda s: not s["sent"],
                lambda s: [net.send(s, "net", ("hello",)).set("sent", True)],
            )
            yield Action(
                "recv",
                lambda s: ("hello",) in net.pending(s, "net"),
                lambda s: [net.deliver(s, "net", ("hello",)).set("done", True)],
            )

    return Relay()


def _no_silent_loss():
    """訊息不得憑空消失:送出後若尚未收到,它必須還在網路裡。

    **人類裁決（2026-07-26）**：這三條原本用的是
    `Invariant("eventually_done", lambda s: not s["sent"] or s["done"])`，
    那是把 liveness 誤當成 safety —— 它在**完全沒有故障注入**的模型上就會被違反，
    因為「送出後、收到前」那個 `sent=True / done=False` 的中間狀態必然存在。
    於是 `test_zero_budget_disables_the_fault` 斷言 `ok=True` 永遠不可能成立，
    而 `test_message_loss_breaks_delivery` 雖然過了卻是為了錯的理由過的。

    codex 在第 9 輪正確診斷出這件事並依 `MISSION.md` 交付人類裁決，沒有加特判。
    這是裁判本身的缺陷，由我修正。改成真正的安全性質後，三條才各自驗到該驗的東西。
    """
    net = submodule("crucible.net")
    return Invariant(
        "no_silent_loss",
        lambda s: (not s["sent"]) or s["done"] or ("hello",) in net.pending(s, "net"),
    )


class TestL7Faults(unittest.TestCase):
    def test_faults_module_exists(self):
        submodule("crucible.faults")

    def test_with_faults_returns_a_model(self):
        faults = submodule("crucible.faults")
        self.assertIsInstance(
            faults.with_faults(_relay_model(), [faults.MessageLoss(budget=1)]), Model
        )

    def test_message_loss_breaks_delivery(self):
        Checker = api("Checker")
        faults = submodule("crucible.faults")
        model = faults.with_faults(_relay_model(), [faults.MessageLoss(budget=1)])
        inv = [_no_silent_loss()]
        self.assertFalse(Checker(model, inv).check().ok)

    def test_without_faults_delivery_is_reliable(self):
        # 沒有故障時,唯一走不動的狀態就是已送達的那個。
        Checker = api("Checker")
        result = Checker(_relay_model()).check()
        self.assertTrue(all(s["done"] for s in result.deadlocks))
        self.assertEqual(len(result.deadlocks), 1)

    def test_fault_budget_is_respected(self):
        Checker = api("Checker")
        faults = submodule("crucible.faults")
        model = faults.with_faults(_relay_model(), [faults.MessageLoss(budget=1)])
        result = Checker(model).check()
        for state in result.deadlocks:
            self.assertLessEqual(state.get("faults.used", 0), 1)

    def test_zero_budget_disables_the_fault(self):
        Checker = api("Checker")
        faults = submodule("crucible.faults")
        model = faults.with_faults(_relay_model(), [faults.MessageLoss(budget=0)])
        inv = [_no_silent_loss()]
        self.assertTrue(Checker(model, inv).check().ok)

    def test_duplication_can_deliver_twice(self):
        faults = submodule("crucible.faults")
        self.assertIsNotNone(faults.MessageDuplication(budget=1))

    def test_crash_fault_exists(self):
        faults = submodule("crucible.faults")
        self.assertIsNotNone(faults.Crash(nodes=("n1",), budget=1))

    def test_partition_fault_exists(self):
        faults = submodule("crucible.faults")
        self.assertIsNotNone(faults.Partition(groups=(("n1",), ("n2",)), budget=1))

    def test_fault_counterexample_is_replayable(self):
        Checker = api("Checker")
        faults = submodule("crucible.faults")
        model = faults.with_faults(_relay_model(), [faults.MessageLoss(budget=1)])
        invs = [_no_silent_loss()]
        _confirm_violation(self, model, invs, Checker(model, invs).check().violation)

    def test_negative_budget_is_rejected(self):
        faults = submodule("crucible.faults")
        with self.assertRaises(Exception):
            faults.MessageLoss(budget=-1)


# ==========================================================================
# L8 —— 協定庫。正確版不得誤報,錯誤版必須被抓到且反例可重播。
# ==========================================================================


CORRECT = ["peterson", "dekker", "two_phase_commit", "raft_election", "bank_transfer"]
BROKEN = [name + "_broken" for name in CORRECT]


def _protocol(name):
    build = member("crucible.protocols", name)
    model, invariants = build()
    return model, list(invariants)


class TestL8Correct(unittest.TestCase):
    """正確版協定不得誤報。"""

    def _assert_clean(self, name):
        Checker = api("Checker")
        model, invs = _protocol(name)
        result = Checker(model, invs).check()
        self.assertTrue(
            result.ok,
            "false positive on %s: %s"
            % (name, result.violation.format() if result.violation else ""),
        )
        self.assertTrue(result.complete, "%s was not exhaustively checked" % name)

    def test_peterson_is_clean(self):
        self._assert_clean("peterson")

    def test_dekker_is_clean(self):
        self._assert_clean("dekker")

    def test_two_phase_commit_is_clean(self):
        self._assert_clean("two_phase_commit")

    def test_raft_election_is_clean(self):
        self._assert_clean("raft_election")

    def test_bank_transfer_is_clean(self):
        self._assert_clean("bank_transfer")


class TestL8Broken(unittest.TestCase):
    """故意有 bug 的變體必須被抓到,而且反例要能獨立重播。"""

    def _assert_caught(self, name):
        Checker = api("Checker")
        model, invs = _protocol(name)
        result = Checker(model, invs).check()
        self.assertFalse(result.ok, "%s should have been caught but was not" % name)
        _confirm_violation(self, model, invs, result.violation)

    def test_peterson_broken_is_caught(self):
        self._assert_caught("peterson_broken")

    def test_dekker_broken_is_caught(self):
        self._assert_caught("dekker_broken")

    def test_two_phase_commit_broken_is_caught(self):
        self._assert_caught("two_phase_commit_broken")

    def test_raft_election_broken_is_caught(self):
        self._assert_caught("raft_election_broken")

    def test_bank_transfer_broken_is_caught(self):
        self._assert_caught("bank_transfer_broken")


class TestL8Registry(unittest.TestCase):
    def test_catalog_lists_every_protocol(self):
        catalog = member("crucible.protocols", "catalog")
        self.assertEqual(sorted(catalog()), sorted(CORRECT + BROKEN))

    def test_every_protocol_declares_at_least_one_invariant(self):
        for name in CORRECT:
            _, invs = _protocol(name)
            self.assertTrue(invs, "%s declares no invariant" % name)

    def test_broken_variants_share_the_invariants_of_their_correct_twin(self):
        for name in CORRECT:
            _, good = _protocol(name)
            _, bad = _protocol(name + "_broken")
            self.assertEqual(
                sorted(i.name for i in good),
                sorted(i.name for i in bad),
                "%s and its broken twin must be judged by the same yardstick" % name,
            )

    def test_protocols_are_deterministic(self):
        Checker = api("Checker")
        model, invs = _protocol("peterson_broken")
        traces = {Checker(model, invs).check().violation.trace.format() for _ in range(3)}
        self.assertEqual(len(traces), 1)

    def test_broken_counterexamples_are_short_enough_to_read(self):
        Checker = api("Checker")
        for name in BROKEN:
            model, invs = _protocol(name)
            trace = Checker(model, invs).check().violation.trace
            self.assertLessEqual(
                len(trace), 20, "%s counterexample is too long to be useful" % name
            )


if __name__ == "__main__":
    unittest.main()
