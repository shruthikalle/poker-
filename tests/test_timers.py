import unittest

from poker.engine import new_game
from server.clock import SECOND
from server.timers import DISCONNECT_GRACE, TURN_DURATION, MatchResult, Timing


class TimingStateTests(unittest.TestCase):
    def setUp(self):
        self.hand = new_game(ruleset="legacy")

    def presence(self, state, seats, seconds):
        return state.with_presence(
            seats, self.hand, seconds * SECOND, TURN_DURATION, DISCONNECT_GRACE
        )

    def test_turn_pauses_and_repeated_resume_preserves_active_time(self):
        initial = self.presence(Timing(), (True, False), 0)
        self.assertIsNone(initial.next_deadline)
        running = self.presence(initial, (True, True), 0)
        self.assertEqual(running.turn_deadline, 30 * SECOND)
        paused = self.presence(running, (False, True), 10)
        self.assertEqual(
            (paused.saved_turn, paused.next_deadline), (20 * SECOND, 30 * SECOND)
        )
        self.assertEqual(
            self.presence(paused, (True, True), 15).turn_deadline, 35 * SECOND
        )
        running = self.presence(paused, (True, True), 15)
        paused = self.presence(running, (True, False), 22)
        self.assertEqual(paused.saved_turn, 13 * SECOND)
        self.assertEqual(
            self.presence(paused, (True, True), 30).turn_deadline, 43 * SECOND
        )

    def test_earliest_absence_and_terminal_clock_cleanup(self):
        running = self.presence(Timing(), (True, True), 0)
        paused = self.presence(running, (False, True), 10)
        both = self.presence(paused, (False, False), 17)
        self.assertEqual(both.grace, (30 * SECOND, 37 * SECOND))
        self.assertIsNone(both.disconnect_result(30 * SECOND - 1))
        result = both.disconnect_result(30 * SECOND)
        self.assertEqual(result, MatchResult("both_absent", None))
        closed = both.finish(result, 30 * SECOND)
        self.assertEqual(closed.terminal_at, 30 * SECOND)
        self.assertIsNone(closed.next_deadline)
        self.assertEqual(closed.grace, (None, None))
        self.assertIs(self.presence(closed, (True, True), 31), closed)
        a_returns = self.presence(both, (True, False), 25)
        self.assertEqual(a_returns.grace, (None, 37 * SECOND))
        self.assertEqual(
            a_returns.disconnect_result(37 * SECOND), MatchResult("forfeit", "A")
        )
        b_returns = self.presence(both, (False, True), 25)
        self.assertEqual(
            b_returns.disconnect_result(30 * SECOND), MatchResult("forfeit", "B")
        )
