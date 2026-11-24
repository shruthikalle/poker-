"""Worked chip totals and card outcomes specified in the README."""

import unittest
from dataclasses import replace

from poker import apply_action, legal_actions, new_game

ALL_CARDS = tuple(f"{rank}{suit}" for rank in "23456789TJQKA" for suit in "cdhs")
WINNER_BOARD = ("2c", "7d", "9h", "Js", "3c")
TIE_BOARD = ("2c", "4d", "6h", "8s", "Td")


def deck_for(
    a: tuple[str, str], b: tuple[str, str], board: tuple[str, ...]
) -> tuple[str, ...]:
    """Alternate hole cards, then place the five community cards next."""

    prefix = (a[0], b[0], a[1], b[1], *board)
    return prefix + tuple(card for card in ALL_CARDS if card not in prefix)


WINNER_DECK = deck_for(("As", "Ah"), ("Kc", "Kd"), WINNER_BOARD)
TIE_DECK = deck_for(("As", "Kh"), ("Ac", "Kd"), TIE_BOARD)


def move(state, player: str, action: str):
    result = apply_action(state, player, action)
    if not result.accepted:
        raise AssertionError(f"{player} {action} rejected: {result.error}")
    assert sum(result.state.stacks) + result.state.pot == 400
    return result.state


def reach_flop(deck=WINNER_DECK):
    state = new_game(deck=deck)
    state = move(state, "A", "call")
    return move(state, "B", "check")


def reach_showdown(deck=WINNER_DECK):
    state = reach_flop(deck)
    for player in ("B", "A", "B", "A", "B", "A"):
        state = move(state, player, "check")
    return state


class BettingTests(unittest.TestCase):
    def test_big_blind_may_raise_after_small_blind_calls(self) -> None:
        state = move(new_game(deck=WINNER_DECK), "A", "call")
        self.assertEqual(legal_actions(state, "B"), {"fold", "check", "raise"})
        raised = move(state, "B", "raise")
        self.assertEqual(
            (raised.pot, raised.stacks, raised.contributions),
            (30, (190, 180), (10, 20)),
        )
        flop = move(raised, "A", "call")
        self.assertEqual((flop.phase, flop.pot, flop.stacks), ("flop", 40, (180, 180)))

    def test_postflop_bet_raise_call_closes_round(self) -> None:
        state = move(reach_flop(), "B", "bet")
        raised = move(state, "A", "raise")
        self.assertEqual(
            (raised.pot, raised.stacks, raised.contributions),
            (50, (170, 180), (20, 10)),
        )
        turn = move(raised, "B", "call")
        self.assertEqual((turn.phase, turn.pot, turn.stacks), ("turn", 60, (170, 170)))

    def test_g3_bet_call_advances_to_turn_with_correct_pot(self) -> None:
        flop = reach_flop()
        bet = move(flop, "B", "bet")
        self.assertEqual((bet.pot, bet.stacks, bet.actor), (30, (190, 180), "A"))
        turn = move(bet, "A", "call")
        self.assertEqual(turn.phase, "turn")
        self.assertEqual((turn.pot, turn.stacks), (40, (180, 180)))
        self.assertEqual(turn.contributions, (0, 0))
        self.assertEqual((len(turn.board), turn.actor), (4, "B"))

    def test_g4_turn_and_river_checks_reach_paid_showdown(self) -> None:
        state = move(reach_flop(), "B", "bet")
        state = move(state, "A", "call")
        state = move(state, "B", "check")
        river = move(state, "A", "check")
        self.assertEqual((river.phase, river.pot, len(river.board)), ("river", 40, 5))
        state = move(river, "B", "check")
        result = move(state, "A", "check")
        self.assertEqual(result.phase, "showdown")
        self.assertEqual(result.winner, "A")
        self.assertEqual((result.stacks, result.pot), ((220, 180), 0))
        self.assertEqual(result.board, WINNER_BOARD)

    def test_g6_flop_fold_awards_all_chips_in_pot(self) -> None:
        state = move(reach_flop(), "B", "bet")
        result = move(state, "A", "fold")
        self.assertEqual((result.stacks, result.pot), ((190, 210), 0))
        self.assertEqual((result.phase, result.winner), ("finished", "B"))

    def test_g8_two_checks_advance_once_then_reject_stale_check(self) -> None:
        state = move(reach_flop(), "B", "check")
        turn = move(state, "A", "check")
        self.assertEqual((turn.phase, len(turn.board), turn.actor), ("turn", 4, "B"))
        stale = apply_action(turn, "A", "check")
        self.assertFalse(stale.accepted)
        self.assertIs(stale.state, turn)

    def test_g9_call_that_would_empty_stack_is_illegal(self) -> None:
        state = move(reach_flop(), "B", "bet")
        state = replace(state, stacks=(10, 180), pot=210)
        self.assertEqual(legal_actions(state, "A"), {"fold"})
        result = apply_action(state, "A", "call")
        self.assertFalse(result.accepted)
        self.assertIs(result.state, state)

    def test_g10_match_ends_if_next_big_blind_cannot_be_posted(self) -> None:
        state = replace(new_game(deck=WINNER_DECK), stacks=(10, 375))
        result = move(state, "A", "fold")
        self.assertEqual(result.stacks, (10, 390))
        self.assertEqual(result.match_winner, "B")
        self.assertEqual(legal_actions(result, "A"), set())
        self.assertEqual(legal_actions(result, "B"), set())

    def test_g11_second_hand_alternates_button_and_blinds(self) -> None:
        finished = move(new_game(deck=WINNER_DECK), "A", "fold")
        self.assertEqual(legal_actions(finished, "A"), {"ready"})
        waiting = move(finished, "A", "ready")
        self.assertEqual(waiting.ready_players, (True, False))
        self.assertEqual(waiting.hand_number, 1)
        second_result = apply_action(waiting, "B", "ready", deck=TIE_DECK)
        self.assertTrue(second_result.accepted)
        second = second_result.state
        self.assertEqual(
            (second.hand_number, second.button, second.actor), (2, "B", "B")
        )
        self.assertEqual(
            (second.stacks, second.contributions, second.pot), ((185, 200), (10, 5), 15)
        )
        self.assertEqual(second.hole_cards[1], ("As", "Kh"))
        self.assertEqual(second.hole_cards[0], ("Ac", "Kd"))
        self.assertEqual(second.ready_players, (False, False))

    def test_r10_repeated_ready_does_not_start_a_new_hand(self) -> None:
        finished = move(new_game(deck=WINNER_DECK), "A", "fold")
        waiting = move(finished, "A", "ready")
        again = apply_action(waiting, "A", "ready")
        self.assertFalse(again.accepted)
        self.assertIs(again.state, waiting)
        self.assertEqual(waiting.hand_number, 1)

    def test_g12_raise_cap_resets_after_round(self) -> None:
        state = new_game(deck=WINNER_DECK)
        state = move(state, "A", "raise")
        state = move(state, "B", "raise")
        self.assertEqual(state.raise_count, 2)
        flop = move(state, "A", "call")
        self.assertEqual(flop.raise_count, 0)
        self.assertIn("bet", legal_actions(flop, "B"))

    def test_r2_reject_invalid_actions_without_mutating_state(self) -> None:
        state = new_game(deck=WINNER_DECK)
        for action in ("check", "bet", "raise:30", "dance"):
            with self.subTest(action=action):
                result = apply_action(state, "A", action)
                self.assertFalse(result.accepted)
                self.assertIs(result.state, state)


class DealTests(unittest.TestCase):
    def test_c1_pair_of_aces_wins_known_deal(self) -> None:
        result = reach_showdown(WINNER_DECK)
        self.assertEqual(result.board, WINNER_BOARD)
        self.assertEqual(
            (result.winner, result.stacks, result.pot), ("A", (210, 190), 0)
        )
        self.assertEqual(result.phase, "showdown")

    def test_c2_known_ace_high_tie_splits_pot(self) -> None:
        result = reach_showdown(TIE_DECK)
        self.assertIsNone(result.winner)
        self.assertEqual((result.stacks, result.pot), ((200, 200), 0))
        self.assertEqual(result.phase, "showdown")

    def test_c3_reject_duplicate_or_short_deck(self) -> None:
        for deck in (ALL_CARDS[:-1], ALL_CARDS[:-1] + (ALL_CARDS[0],)):
            with self.subTest(deck=deck[-2:]):
                with self.assertRaises(ValueError):
                    new_game(deck=deck)

    def test_c3_bad_next_deck_leaves_finished_hand_unchanged(self) -> None:
        state = move(new_game(deck=WINNER_DECK), "A", "fold")
        state = move(state, "A", "ready")
        result = apply_action(state, "B", "ready", deck=ALL_CARDS[:-1])
        self.assertFalse(result.accepted)
        self.assertIs(result.state, state)

    def test_r5_reject_bad_bet_units(self) -> None:
        for unit in (0, 3, 22, True, 2.5):
            with self.subTest(unit=unit):
                with self.assertRaises(ValueError):
                    new_game(bet_unit=unit)


if __name__ == "__main__":
    unittest.main()
