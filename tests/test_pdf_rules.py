"""Independent expected results for the PDF rule variant."""

import unittest
from dataclasses import replace
import json

from fastapi.testclient import TestClient

from poker.engine import apply_action, legal_actions, new_game
from poker.rooms import RoomManager
from poker.server import create_app

ALL_CARDS = tuple(f"{rank}{suit}" for rank in "23456789TJQKA" for suit in "cdhs")


def deck_for(board, a=("9h", "5h"), b=("Ts", "3c")):
    # Alternating hole cards, then one burn before each board street.
    used = (*a, *b, *board)
    burns = tuple(card for card in ALL_CARDS if card not in used)[:3]
    prefix = (
        a[0],
        b[0],
        a[1],
        b[1],
        burns[0],
        *board[:3],
        burns[1],
        board[3],
        burns[2],
        board[4],
    )
    return prefix + tuple(card for card in ALL_CARDS if card not in prefix)


WINNER_BOARD = ("Ah", "Kh", "Qh", "Jc", "2d")
WINNER_DECK = deck_for(WINNER_BOARD)


def move(state, seat, action):
    result = apply_action(state, seat, action)
    assert result.accepted, result.error
    assert sum(result.state.stacks) + result.state.pot == 1000
    return result.state


class PDFRulesTests(unittest.TestCase):
    def test_independent_showdown_oracles(self):
        # Expected winners come from the PDF's hand-calculated examples.
        cases = (
            ("flush beats straight", WINNER_BOARD, ("9h", "5h"), ("Ts", "3c"), "A"),
            (
                "king kicker",
                ("As", "7d", "4c", "2h", "9s"),
                ("Ac", "Kd"),
                ("Ad", "Qd"),
                "A",
            ),
            (
                "royal flush board",
                ("As", "Ks", "Qs", "Js", "Ts"),
                ("2c", "3d"),
                ("4c", "5d"),
                None,
            ),
            (
                "wheel straight",
                ("Ac", "2d", "3h", "4s", "9c"),
                ("5d", "Kh"),
                ("Ad", "Qh"),
                "A",
            ),
            (
                "full house beats flush",
                ("Ah", "Ad", "7h", "7c", "2h"),
                ("As", "Kc"),
                ("Kh", "Qh"),
                "A",
            ),
            (
                "quads beat full house",
                ("9c", "9d", "9h", "2s", "2d"),
                ("9s", "Ac"),
                ("2c", "Kd"),
                "A",
            ),
        )
        for name, board, a, b, expected in cases:
            with self.subTest(name=name):
                state = new_game(deck=deck_for(board, a, b))
                state = move(state, "A", "call")
                state = move(state, "B", "check")
                for _ in range(3):
                    state = move(state, "B", "check")
                    state = move(state, "A", "check")
                self.assertEqual(
                    (state.phase, state.winner, state.board),
                    ("showdown", expected, board),
                )
                self.assertEqual(
                    state.stacks, (510, 490) if expected == "A" else (500, 500)
                )
                self.assertEqual(len(state.burn_cards), 3)

    def test_fixed_stacks_blinds_and_three_raises(self):
        state = new_game(deck=WINNER_DECK, ruleset="pdf")
        self.assertEqual((state.stacks, state.pot, state.actor), ((495, 490), 15, "A"))
        self.assertEqual(legal_actions(state, "A"), {"fold", "call", "raise"})
        for seat in ("A", "B", "A"):
            state = move(state, seat, "raise")
        self.assertEqual(
            (state.stacks, state.pot, state.raise_count), ((460, 470), 70, 3)
        )
        self.assertEqual(legal_actions(state, "B"), {"fold", "call"})
        self.assertIs(apply_action(state, "B", "raise").state, state)
        flop = move(state, "B", "call")
        self.assertEqual((flop.stacks, flop.pot, flop.raise_count), ((460, 460), 80, 0))
        self.assertEqual((flop.board, len(flop.burn_cards)), (WINNER_BOARD[:3], 1))

    def test_street_increment_burns_and_showdown_payout(self):
        state = new_game(deck=WINNER_DECK, ruleset="pdf")
        for seat, action in (("A", "call"), ("B", "check")):
            state = move(state, seat, action)
        self.assertEqual(
            (state.stacks, state.pot, state.board), ((490, 490), 20, WINNER_BOARD[:3])
        )
        state = move(state, "B", "bet")
        state = move(state, "A", "call")
        self.assertEqual(
            (state.stacks, state.pot, state.phase), ((480, 480), 40, "turn")
        )
        self.assertEqual((state.board, len(state.burn_cards)), (WINNER_BOARD[:4], 2))
        self.assertIn("bet", legal_actions(state, "B"))
        state = move(state, "B", "bet")
        self.assertEqual((state.stacks, state.pot), ((480, 460), 60))
        state = move(state, "A", "call")
        self.assertEqual(
            (state.stacks, state.pot, state.phase), ((460, 460), 80, "river")
        )
        self.assertEqual((state.board, len(state.burn_cards)), (WINNER_BOARD, 3))
        state = move(state, "B", "check")
        state = move(state, "A", "check")
        self.assertEqual((state.stacks, state.pot, state.winner), ((540, 460), 0, "A"))

    def test_opponent_coverage_and_next_blind_boundary(self):
        state = new_game(deck=WINNER_DECK, ruleset="pdf")
        state = move(state, "A", "call")
        state = move(state, "B", "check")
        state = move(state, "B", "check")
        short = replace(state, stacks=(100, 10), pot=890)
        self.assertNotIn("bet", legal_actions(short, "A"))
        self.assertIs(apply_action(short, "A", "bet").state, short)
        almost_out = replace(new_game(deck=WINNER_DECK, ruleset="pdf"), stacks=(5, 980))
        ended = move(almost_out, "A", "fold")
        self.assertEqual(ended.match_winner, "B")

    def test_invalid_pdf_configuration_is_rejected(self):
        with self.assertRaises(ValueError):
            new_game(bet_unit=12, ruleset="pdf")
        with self.assertRaises(ValueError):
            new_game(ruleset="unknown")

    def test_second_hand_rotates_blinds_and_resets_burns(self):
        state = move(new_game(deck=WINNER_DECK, ruleset="pdf"), "A", "fold")
        state = move(state, "A", "ready")
        second = apply_action(state, "B", "ready", deck=WINNER_DECK)
        self.assertTrue(second.accepted)
        hand = second.state
        self.assertEqual(
            (hand.ruleset, hand.hand_number, hand.button, hand.actor),
            ("pdf", 2, "B", "B"),
        )
        self.assertEqual(
            (hand.stacks, hand.contributions, hand.pot), ((485, 500), (10, 5), 15)
        )
        self.assertEqual((hand.board, hand.burn_cards), ((), ()))
        self.assertEqual(hand.hole_cards[1], ("9h", "5h"))

    def test_odd_chip_goes_to_nondealer(self):
        tie_board = ("As", "Ks", "Qs", "Js", "Ts")
        tie_deck = deck_for(tie_board, ("2c", "3d"), ("4c", "5d"))
        state = new_game(deck=tie_deck, ruleset="pdf")
        for seat, action in (
            ("A", "call"),
            ("B", "check"),
            *((seat, "check") for seat in ("B", "A", "B", "A", "B")),
        ):
            state = move(state, seat, action)
        # This odd pot is an accounting boundary fixture; normal matched bets make an even showdown pot.
        state = replace(state, stacks=(489, 490), pot=21)
        tied = move(state, "A", "check")
        self.assertEqual((tied.winner, tied.stacks, tied.pot), (None, (499, 501), 0))


class PDFIntegrationTests(unittest.TestCase):
    def test_default_app_rejects_non_pdf_table_settings(self):
        with TestClient(create_app()) as client:
            self.assertEqual(client.get("/api/config").json()["ruleset"], "pdf")
            self.assertEqual(
                client.post("/api/rooms", json={"bet_unit": 12}).status_code, 422
            )
            host = client.post("/api/rooms", json={"bet_unit": 10})
            self.assertEqual(host.status_code, 201)
            joined = client.post(
                "/api/rooms/join", json={"room_code": host.json()["room_code"]}
            )
            self.assertEqual(joined.status_code, 200)

    def test_two_live_seats_play_fixed_pdf_hand_without_card_leaks(self):
        tokens = iter(("pdf-token-a", "pdf-token-b"))
        rooms = RoomManager(
            code_factory=lambda: "PDFROOM",
            token_factory=tokens.__next__,
            deck=WINNER_DECK,
            ruleset="pdf",
        )
        with TestClient(create_app(rooms)) as client:
            host = client.post("/api/rooms", json={"bet_unit": 10}).json()
            guest = client.post("/api/rooms/join", json={"room_code": "PDFROOM"}).json()
            with client.websocket_connect("/ws") as a:
                a.send_json(
                    {
                        "type": "auth",
                        "token": host["session_token"],
                        "protocol": "gameplay.v1",
                    }
                )
                self.assertEqual(a.receive_json()["lifecycle"], "awaiting_players")
                with client.websocket_connect("/ws") as b:
                    b.send_json(
                        {
                            "type": "auth",
                            "token": guest["session_token"],
                            "protocol": "gameplay.v1",
                        }
                    )
                    current = {"A": a.receive_json(), "B": b.receive_json()}
                    self.assertEqual(
                        (current["A"]["stacks"], current["A"]["pot"]),
                        ({"A": 495, "B": 490}, 15),
                    )
                    moves = (
                        ("A", "call"),
                        ("B", "check"),
                        ("B", "bet"),
                        ("A", "call"),
                        ("B", "bet"),
                        ("A", "call"),
                        ("B", "check"),
                        ("A", "check"),
                    )
                    for number, (seat, action) in enumerate(moves, 1):
                        socket = a if seat == "A" else b
                        socket.send_json(
                            {
                                "type": "action",
                                "action_id": f"pdf-{number}",
                                "hand_id": 1,
                                "expected_revision": number,
                                "action": action,
                            }
                        )
                        ack = socket.receive_json()
                        self.assertTrue(ack["accepted"], ack)
                        current = {"A": a.receive_json(), "B": b.receive_json()}
                        self.assertEqual(current["A"]["revision"], number + 1)
                        self.assertEqual(current["A"]["stacks"], current["B"]["stacks"])
                        self.assertEqual(
                            sum(current["A"]["stacks"].values()) + current["A"]["pot"],
                            1000,
                        )
                        for recipient, hidden in (
                            ("A", ("Ts", "3c")),
                            ("B", ("9h", "5h")),
                        ):
                            view = current[recipient]
                            self.assertNotIn("deck", view)
                            self.assertNotIn("burn_cards", view)
                            if view["phase"] != "showdown":
                                for card in hidden:
                                    self.assertNotIn(json.dumps(card), json.dumps(view))
                    result = current["A"]
                    self.assertEqual(
                        (result["stacks"], result["pot"], result["board"]),
                        ({"A": 540, "B": 460}, 0, list(WINNER_BOARD)),
                    )
                    self.assertEqual(result["result"]["winner"], "A")


if __name__ == "__main__":
    unittest.main()
