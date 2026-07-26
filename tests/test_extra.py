import unittest

from crucible import Action, Checker, Invariant, Model, State
from crucible.faults import MessageLoss, with_faults


class Counter(Model):
    def init(self):
        yield State({"n": 0})

    def actions(self):
        yield Action(
            "inc",
            lambda state: state["n"] < 1000,
            lambda state: [state.set("n", state["n"] + 1)],
        )


class TestCheckerSemantics(unittest.TestCase):
    def test_stop_on_first_violation_is_not_complete(self):
        result = Checker(
            Counter(),
            [Invariant("under_2", lambda state: state["n"] < 2)],
        ).check()

        self.assertFalse(result.ok)
        self.assertEqual(result.states_explored, 3)
        self.assertFalse(result.complete)


class TestFaultSemantics(unittest.TestCase):
    def test_disabled_faults_leave_model_shape_unchanged(self):
        base = Counter()
        wrapped = with_faults(base, [MessageLoss(budget=0)])

        self.assertIs(wrapped, base)
        self.assertEqual(wrapped.initial_states(), base.initial_states())
        self.assertEqual(
            tuple(action.name for action in wrapped.action_list()),
            tuple(action.name for action in base.action_list()),
        )

    def test_mixed_faults_only_expose_active_declarations(self):
        base = Counter()
        wrapped = with_faults(
            base,
            [MessageLoss(budget=0), MessageLoss(budget=1)],
        )

        self.assertEqual(
            tuple(action.name for action in wrapped.action_list()),
            ("fault.message_loss", "inc"),
        )


if __name__ == "__main__":
    unittest.main()
