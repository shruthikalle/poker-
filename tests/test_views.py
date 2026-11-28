import json
import unittest
from dataclasses import replace

from poker.engine import apply_action, new_game
from poker.rooms import Room
from server.fixtures import fixed_deck
from server.views import player_view

WAITING_FIELDS = {"type", "status", "seat", "bet_unit", "revision"}
HAND_FIELDS = WAITING_FIELDS | {
    "hand_id",
    "phase",
    "button",
    "actor",
    "stacks",
    "contributions",
    "pot",
    "board",
    "raise_count",
    "ready_seats",
    "own_hole_cards",
    "legal_actions",
    "can_ready",
    "result",
    "match_winner",
}


class PlayerViewTests(unittest.TestCase):
    def setUp(self):
        self.room = Room("private-code", 10, "private-token-a")

    def test_waiting_has_exactly_the_public_fields(self):
        self.assertEqual(
            player_view(self.room, "A", 0),
            {
                "type": "snapshot",
                "status": "waiting",
                "seat": "A",
                "bet_unit": 10,
                "revision": 0,
            },
        )

    def test_first_hand_exact_fields_and_no_hidden_cards(self):
        hand = new_game(ruleset="legacy", deck=fixed_deck("showdown"))
        room = replace(self.room, hand=hand, seat_b_token="private-token-b")
        for seat, own, hidden, actions in (
            ("A", ["9h", "5h"], ["Ts", "3c"], ["call", "fold", "raise"]),
            ("B", ["Ts", "3c"], ["9h", "5h"], []),
        ):
            with self.subTest(seat=seat):
                view = player_view(room, seat, 1)
                self.assertEqual(set(view), HAND_FIELDS)
                self.assertEqual(view["own_hole_cards"], own)
                self.assertEqual(view["legal_actions"], actions)
                self.assertEqual(view["stacks"], {"A": 195, "B": 190})
                self.assertEqual(view["contributions"], {"A": 5, "B": 10})
                self.assertEqual(view["pot"], 15)
                self.assertEqual(view["board"], [])
                self.assertIsNone(view["result"])
                self.assertFalse(view["can_ready"])
                serialized = json.dumps(view)
                for value in (
                    *hidden,
                    *hand.deck,
                    "private-code",
                    "private-token-a",
                    "private-token-b",
                ):
                    self.assertNotIn(json.dumps(value), serialized)

    def test_fold_and_match_winner_are_distinct(self):
        starting = replace(
            new_game(ruleset="legacy", deck=fixed_deck("fold")), stacks=(10, 375)
        )
        hand = apply_action(starting, "A", "fold").state
        room = replace(self.room, hand=hand, seat_b_token="private-token-b")
        view = player_view(room, "B", 2)
        self.assertEqual(view["result"], {"kind": "fold_win", "winner": "B"})
        self.assertEqual(view["match_winner"], "B")
        self.assertFalse(view["can_ready"])
        self.assertNotIn('"9h"', json.dumps(view))

    def test_paid_showdown_distinguishes_win_from_tie(self):
        for scenario, kind, winner in (
            ("showdown", "showdown_win", "A"),
            ("tie", "showdown_tie", None),
        ):
            with self.subTest(scenario=scenario):
                hand = new_game(ruleset="legacy", deck=fixed_deck(scenario))
                hand = apply_action(hand, "A", "call").state
                for seat in ("B", "B", "A", "B", "A", "B", "A"):
                    result = apply_action(hand, seat, "check")
                    self.assertTrue(result.accepted)
                    hand = result.state
                room = replace(self.room, hand=hand, seat_b_token="private-token-b")
                view = player_view(room, "A", 9)
                self.assertEqual(view["result"]["kind"], kind)
                self.assertEqual(view["result"]["winner"], winner)
                self.assertEqual(view["pot"], 0)
                self.assertEqual(set(view["result"]["showdown_hole_cards"]), {"A", "B"})
                self.assertTrue(view["can_ready"])
