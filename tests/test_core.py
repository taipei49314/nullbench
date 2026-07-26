"""回歸網 —— L0 地基的行為契約。

這個檔案是驗收基準的一部分,**不可修改**。任何改動都會被自動還原並記為違規。
若你認為某條測試寫錯了,在回覆裡說明理由由人類裁決,不要自己動手。

這裡的每一條都必須永遠是綠的。它們保護的是「已經做對的事不准被弄壞」。

純標準函式庫:測試也不依賴第三方套件。
"""

import unittest

from crucible import (
    Action,
    Checker,
    Invariant,
    Model,
    ModelError,
    State,
    StateError,
)


# --------------------------------------------------------------------------
# 測試用模型
# --------------------------------------------------------------------------


class Counter(Model):
    """從 0 數到 limit 的計數器。"""

    def __init__(self, limit=3):
        self.limit = limit

    def init(self):
        yield State({"n": 0})

    def actions(self):
        yield Action(
            "inc",
            lambda s: s["n"] < self.limit,
            lambda s: [s.set("n", s["n"] + 1)],
        )


class CoinFlip(Model):
    """單一非決定性動作:一步展開成兩個後繼。"""

    def init(self):
        yield State({"face": "none"})

    def actions(self):
        yield Action(
            "flip",
            lambda s: s["face"] == "none",
            lambda s: [s.set("face", "heads"), s.set("face", "tails")],
        )


class TwoInitials(Model):
    """兩個初始狀態,各自可前進一步。"""

    def init(self):
        yield State({"n": 0, "tag": "a"})
        yield State({"n": 0, "tag": "b"})

    def actions(self):
        yield Action("step", lambda s: s["n"] == 0, lambda s: [s.set("n", 1)])


class Terminal(Model):
    """沒有任何啟用動作的模型。"""

    def init(self):
        yield State({"done": True})

    def actions(self):
        yield Action("noop", lambda s: False, lambda s: [])


class Toggle(Model):
    """在兩個狀態間永遠來回。"""

    def init(self):
        yield State({"n": 0})

    def actions(self):
        yield Action("toggle", lambda s: True, lambda s: [s.set("n", 1 - s["n"])])


def under(limit):
    """n < limit 的不變量。"""
    return Invariant("under_%d" % limit, lambda s: s["n"] < limit)


# --------------------------------------------------------------------------
# State
# --------------------------------------------------------------------------


class TestStateReads(unittest.TestCase):
    def test_reads_values(self):
        s = State({"n": 1, "flag": True})
        self.assertEqual(s["n"], 1)
        self.assertIs(s["flag"], True)

    def test_missing_key_raises_keyerror(self):
        with self.assertRaises(KeyError):
            State({"n": 1})["nope"]

    def test_get_returns_default(self):
        s = State({"n": 1})
        self.assertEqual(s.get("n"), 1)
        self.assertIsNone(s.get("nope"))
        self.assertEqual(s.get("nope", 42), 42)

    def test_contains(self):
        s = State({"n": 1})
        self.assertIn("n", s)
        self.assertNotIn("nope", s)

    def test_len_and_iteration(self):
        s = State({"a": 1, "b": 2})
        self.assertEqual(len(s), 2)
        self.assertEqual(list(s), ["a", "b"])

    def test_to_dict_round_trip(self):
        s = State({"a": 1, "b": 2})
        self.assertEqual(State(s.to_dict()), s)


class TestStateDerivation(unittest.TestCase):
    def test_set_is_pure(self):
        s = State({"n": 0})
        t = s.set("n", 1)
        self.assertEqual(s["n"], 0, "set() must not mutate the original state")
        self.assertEqual(t["n"], 1)

    def test_set_adds_new_key(self):
        s = State({"n": 0}).set("extra", "x")
        self.assertEqual(s["extra"], "x")
        self.assertEqual(s["n"], 0)

    def test_update_applies_many_keys(self):
        s = State({"n": 0}).update({"n": 5, "m": 6})
        self.assertEqual(s["n"], 5)
        self.assertEqual(s["m"], 6)

    def test_update_accepts_kwargs(self):
        self.assertEqual(State({"n": 0}).update(n=9)["n"], 9)

    def test_kwargs_construction(self):
        self.assertEqual(State(n=1)["n"], 1)


class TestStateIdentity(unittest.TestCase):
    def test_equality_is_by_value(self):
        self.assertEqual(State({"a": 1, "b": 2}), State({"b": 2, "a": 1}))

    def test_inequality(self):
        self.assertNotEqual(State({"a": 1}), State({"a": 2}))

    def test_hashable_and_dedups_in_a_set(self):
        bag = {State({"a": 1, "b": 2}), State({"b": 2, "a": 1})}
        self.assertEqual(len(bag), 1)

    def test_hash_is_stable_across_key_order(self):
        self.assertEqual(hash(State({"a": 1, "b": 2})), hash(State({"b": 2, "a": 1})))

    def test_repr_is_deterministic_and_sorted(self):
        self.assertEqual(repr(State({"b": 2, "a": 1})), "State(a=1, b=2)")

    def test_keys_are_sorted(self):
        self.assertEqual(State({"z": 1, "a": 2, "m": 3}).keys(), ("a", "m", "z"))

    def test_items_are_sorted(self):
        self.assertEqual(State({"z": 1, "a": 2}).items(), (("a", 2), ("z", 1)))


class TestStateTypeDiscipline(unittest.TestCase):
    def test_rejects_non_string_key(self):
        with self.assertRaises(StateError):
            State({1: "x"})

    def test_rejects_unhashable_value(self):
        with self.assertRaises(StateError):
            State({"a": [1, 2]})

    def test_accepts_tuple_value(self):
        self.assertEqual(State({"a": (1, 2)})["a"], (1, 2))

    def test_can_nest_states_as_values(self):
        inner = State({"x": 1})
        self.assertEqual(State({"inner": inner})["inner"], inner)


# --------------------------------------------------------------------------
# Model / Action / Invariant
# --------------------------------------------------------------------------


class TestAction(unittest.TestCase):
    def test_exposes_name(self):
        self.assertEqual(Action("go", lambda s: True, lambda s: []).name, "go")

    def test_rejects_empty_name(self):
        with self.assertRaises(ModelError):
            Action("", lambda s: True, lambda s: [])

    def test_successors_returns_tuple(self):
        a = Action("go", lambda s: True, lambda s: [State({"n": 1})])
        self.assertEqual(a.successors(State({"n": 0})), (State({"n": 1}),))

    def test_rejects_non_state_successor(self):
        a = Action("bad", lambda s: True, lambda s: ["not a state"])
        with self.assertRaises(ModelError):
            a.successors(State({"n": 0}))


class TestModel(unittest.TestCase):
    def test_initial_states_preserve_yield_order(self):
        self.assertEqual(
            TwoInitials().initial_states(),
            (State({"n": 0, "tag": "a"}), State({"n": 0, "tag": "b"})),
        )

    def test_initial_states_dedup_without_reordering(self):
        class Dupes(Model):
            def init(self):
                yield State({"n": 1})
                yield State({"n": 0})
                yield State({"n": 1})

            def actions(self):
                return []

        self.assertEqual(Dupes().initial_states(), (State({"n": 1}), State({"n": 0})))

    def test_without_initial_state_is_rejected(self):
        class Empty(Model):
            def init(self):
                return []

            def actions(self):
                return []

        with self.assertRaises(ModelError):
            Empty().initial_states()

    def test_actions_are_sorted_by_name(self):
        class Unsorted(Model):
            def init(self):
                yield State({"n": 0})

            def actions(self):
                yield Action("zulu", lambda s: False, lambda s: [])
                yield Action("alpha", lambda s: False, lambda s: [])

        self.assertEqual([a.name for a in Unsorted().action_list()], ["alpha", "zulu"])

    def test_rejects_duplicate_action_names(self):
        class Dupes(Model):
            def init(self):
                yield State({"n": 0})

            def actions(self):
                yield Action("same", lambda s: False, lambda s: [])
                yield Action("same", lambda s: False, lambda s: [])

        with self.assertRaises(ModelError):
            Dupes().action_list()

    def test_bare_init_is_not_implemented(self):
        with self.assertRaises(NotImplementedError):
            list(Model().init())

    def test_bare_actions_is_not_implemented(self):
        with self.assertRaises(NotImplementedError):
            list(Model().actions())


class TestInvariant(unittest.TestCase):
    def test_holds_when_predicate_true(self):
        self.assertIs(Invariant("always", lambda s: True).holds(State({"n": 0})), True)

    def test_fails_when_predicate_false(self):
        self.assertIs(Invariant("never", lambda s: False).holds(State({"n": 0})), False)

    def test_rejects_empty_name(self):
        with self.assertRaises(ModelError):
            Invariant("", lambda s: True)


# --------------------------------------------------------------------------
# Checker —— 探索
# --------------------------------------------------------------------------


class TestExploration(unittest.TestCase):
    def test_explores_every_reachable_state(self):
        self.assertEqual(Checker(Counter(limit=3)).check().states_explored, 4)

    def test_dedups_states(self):
        self.assertEqual(Checker(Toggle()).check().states_explored, 2)

    def test_reports_max_depth(self):
        self.assertEqual(Checker(Counter(limit=3)).check().max_depth_reached, 3)

    def test_handles_nondeterministic_successors(self):
        self.assertEqual(Checker(CoinFlip()).check().states_explored, 3)

    def test_explores_from_all_initial_states(self):
        self.assertEqual(Checker(TwoInitials()).check().states_explored, 4)

    def test_terminates_when_no_action_is_enabled(self):
        result = Checker(Terminal()).check()
        self.assertEqual(result.states_explored, 1)
        self.assertTrue(result.ok)

    def test_treats_empty_successors_as_disabled(self):
        class Stuck(Model):
            def init(self):
                yield State({"n": 0})

            def actions(self):
                yield Action("nothing", lambda s: True, lambda s: [])

        self.assertEqual(Checker(Stuck()).check().states_explored, 1)


# --------------------------------------------------------------------------
# Checker —— 不變量與反例
# --------------------------------------------------------------------------


class TestViolations(unittest.TestCase):
    def _violation(self, limit=3, bound=2):
        return Checker(Counter(limit=limit), [under(bound)]).check()

    def test_ok_when_invariant_always_holds(self):
        result = Checker(Counter(limit=3), [Invariant("bounded", lambda s: s["n"] <= 3)]).check()
        self.assertTrue(result.ok)
        self.assertIsNone(result.violation)

    def test_finds_violation(self):
        result = self._violation()
        self.assertFalse(result.ok)
        self.assertEqual(result.violation.invariant, "under_2")

    def test_trace_ends_at_violating_state(self):
        self.assertEqual(self._violation().violation.trace.final, State({"n": 2}))

    def test_trace_starts_at_initial_state(self):
        self.assertEqual(self._violation().violation.trace.initial, State({"n": 0}))

    def test_trace_records_action_names(self):
        steps = self._violation().violation.trace.steps
        self.assertEqual([name for name, _ in steps], ["inc", "inc"])

    def test_trace_length_matches_steps(self):
        self.assertEqual(len(self._violation().violation.trace), 2)

    def test_trace_states_include_initial(self):
        self.assertEqual(
            self._violation().violation.trace.states,
            (State({"n": 0}), State({"n": 1}), State({"n": 2})),
        )

    def test_initial_state_violation_yields_empty_trace(self):
        result = Checker(Counter(limit=3), [Invariant("nonzero", lambda s: s["n"] != 0)]).check()
        self.assertFalse(result.ok)
        self.assertEqual(len(result.violation.trace), 0)
        self.assertEqual(result.violation.trace.final, State({"n": 0}))

    def test_without_invariants_never_violates(self):
        self.assertTrue(Checker(Counter(limit=3)).check().ok)

    def test_trace_format_is_readable(self):
        text = self._violation().violation.trace.format()
        self.assertIn("(init)", text)
        self.assertIn("inc", text)

    def test_violation_format_names_the_invariant(self):
        self.assertIn("under_2", self._violation().violation.format())


# --------------------------------------------------------------------------
# 決定性 —— 這個專案的立論基礎
# --------------------------------------------------------------------------


class TestDeterminism(unittest.TestCase):
    def test_repeated_checks_agree_on_state_count(self):
        counts = {Checker(Counter(limit=5)).check().states_explored for _ in range(5)}
        self.assertEqual(len(counts), 1)

    def test_repeated_checks_produce_identical_traces(self):
        def trace_repr():
            return Checker(Counter(limit=5), [under(3)]).check().violation.trace.format()

        self.assertEqual(len({trace_repr() for _ in range(5)}), 1)

    def test_declaration_order_of_actions_does_not_change_the_result(self):
        def build(order):
            class M(Model):
                def init(self):
                    yield State({"n": 0})

                def actions(self):
                    made = {
                        "a_inc": Action(
                            "a_inc", lambda s: s["n"] < 2, lambda s: [s.set("n", s["n"] + 1)]
                        ),
                        "b_tag": Action(
                            "b_tag",
                            lambda s: not s.get("tagged", False),
                            lambda s: [s.set("tagged", True)],
                        ),
                    }
                    for name in order:
                        yield made[name]

            return Checker(M()).check().states_explored

        self.assertEqual(build(["a_inc", "b_tag"]), build(["b_tag", "a_inc"]))


if __name__ == "__main__":
    unittest.main()
