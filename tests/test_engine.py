"""Independent expected values for opening turns, raises, and folding."""

import unittest

from poker import apply_action, legal_actions, new_game


class FirstHandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = new_game(
            deck=tuple(f"{rank}{suit}" for rank in "23456789TJQKA" for suit in "cdhs")
        )

    def test_g1_initial_legal_actions_and_blinds(self) -> None:
        state = self.state
        self.assertEqual(state.stacks, (195, 190))
        self.assertEqual(state.contributions, (5, 10))
        self.assertEqual(state.pot, 15)
        self.assertEqual(state.actor, "A")
        self.assertEqual(legal_actions(state, "A"), {"fold", "call", "raise"})
        self.assertEqual(legal_actions(state, "B"), set())

    def test_r1_out_of_turn_action_leaves_every_field_unchanged(self) -> None:
        result = apply_action(self.state, "B", "check")
        self.assertFalse(result.accepted)
        self.assertIsNotNone(result.error)
        self.assertIs(result.state, self.state)

    def test_g2_call_then_check_reveals_flop(self) -> None:
        before = self.state
        called = apply_action(before, "A", "call")
        self.assertTrue(called.accepted)
        self.assertEqual(called.state.stacks, (190, 190))
        self.assertEqual(called.state.contributions, (10, 10))
        self.assertEqual(called.state.pot, 20)
        self.assertEqual(called.state.actor, "B")
        self.assertEqual(before.pot, 15)  # Input state is immutable.

        checked = apply_action(called.state, "B", "check")
        self.assertTrue(checked.accepted)
        self.assertEqual(checked.state.phase, "flop")
        self.assertEqual(checked.state.stacks, (190, 190))
        self.assertEqual(checked.state.pot, 20)
        self.assertEqual(checked.state.contributions, (0, 0))
        self.assertEqual(checked.state.board, before.deck[:3])
        self.assertEqual(checked.state.actor, "B")

    def test_g5_fold_awards_the_pot(self) -> None:
        result = apply_action(self.state, "A", "fold")
        self.assertTrue(result.accepted)
        self.assertEqual(result.state.stacks, (195, 205))
        self.assertEqual(result.state.pot, 0)
        self.assertEqual(result.state.phase, "finished")
        self.assertEqual(result.state.winner, "B")
        self.assertEqual(result.state.board, ())

    def test_g7_r3_two_raises_then_third_is_rejected(self) -> None:
        first = apply_action(self.state, "A", "raise")
        second = apply_action(first.state, "B", "raise")
        self.assertTrue(first.accepted)
        self.assertTrue(second.accepted)
        self.assertEqual(second.state.pot, 50)
        self.assertEqual(second.state.stacks, (180, 170))
        self.assertEqual(second.state.contributions, (20, 30))
        self.assertEqual(legal_actions(second.state, "A"), {"fold", "call"})
        rejected = apply_action(second.state, "A", "raise")
        self.assertFalse(rejected.accepted)
        self.assertIs(rejected.state, second.state)
        called = apply_action(second.state, "A", "call")
        self.assertTrue(called.accepted)
        self.assertEqual(called.state.pot, 60)
        self.assertEqual(called.state.stacks, (170, 170))
        self.assertEqual(called.state.phase, "flop")


if __name__ == "__main__":
    unittest.main()
