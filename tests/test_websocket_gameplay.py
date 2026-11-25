"""Independent known-answer cases through the authenticated socket."""

import json
import unittest
from contextlib import contextmanager

from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

from poker.rooms import RoomManager
from poker.server import create_app
from server.fixtures import fixed_deck
from test_views import HAND_FIELDS

TIMING_FIELDS = {
    "lifecycle",
    "lifecycle_revision",
    "presence",
    "turn_clock",
    "disconnect_grace",
    "match_result",
    "last_automatic_action",
}

CHECK_THROUGH = ("A", "B", "B", "A", "B", "A", "B", "A")


def wire_action(action_id, move, revision, hand=1):
    return {
        "type": "action",
        "action_id": action_id,
        "hand_id": hand,
        "expected_revision": revision,
        "action": move,
    }


class GameplaySocketTests(unittest.TestCase):
    @contextmanager
    def game(self, scenario):
        deck = fixed_deck(scenario)
        self.cards = {"A": [deck[0], deck[2]], "B": [deck[1], deck[3]]}
        self.board = list(deck[4:9])
        self.deck = deck
        tokens = iter(("test-session-a", "test-session-b"))
        self.rooms = RoomManager(
            code_factory=lambda: "test-game-room",
            token_factory=tokens.__next__,
            deck=deck,
        )
        with TestClient(create_app(self.rooms)) as client:
            self.client = client
            host = client.post("/api/rooms", json={"bet_unit": 10}).json()
            with client.websocket_connect("/ws") as a:
                self.auth(a, host["session_token"])
                self.assertEqual(
                    a.receive_json(),
                    {
                        "type": "snapshot",
                        "status": "waiting",
                        "seat": "A",
                        "bet_unit": 10,
                        "revision": 0,
                        "lifecycle": "waiting",
                        "lifecycle_revision": 1,
                        "presence": {"A": True, "B": False},
                        "turn_clock": {
                            "status": "inactive",
                            "acting_player": None,
                            "remaining_ms": None,
                        },
                        "disconnect_grace": {"A": None, "B": None},
                        "match_result": None,
                        "last_automatic_action": None,
                    },
                )
                a.send_json(wire_action("waiting", "fold", 0))
                self.assertEqual(a.receive_json()["error_code"], "NOT_READY")
                self.assertEqual(self.rooms.snapshot().revision, 0)
                joined = client.post(
                    "/api/rooms/join", json={"room_code": host["room_code"]}
                )
                self.assertEqual(joined.status_code, 200)
                dealt = a.receive_json()
                self.assertEqual(
                    (dealt["revision"], dealt["lifecycle"]), (1, "awaiting_players")
                )
                self.assertEqual(dealt["turn_clock"]["status"], "inactive")
                with client.websocket_connect("/ws") as b:
                    self.auth(b, joined.json()["session_token"])
                    self.sockets = {"A": a, "B": b}
                    self.assert_views(
                        revision=1,
                        stack=(195, 190),
                        pot=15,
                        phase="preflop",
                        actor="A",
                        contributions=(5, 10),
                    )
                    yield

    def auth(self, socket, token):
        socket.send_json({"type": "auth", "token": token, "protocol": "gameplay.v1"})

    def assert_views(
        self, *, revision, stack, pot, phase, actor, contributions, hand=1, button="A"
    ):
        views = {seat: socket.receive_json() for seat, socket in self.sockets.items()}
        expected_board = self.board[
            : {
                "preflop": 0,
                "flop": 3,
                "turn": 4,
                "river": 5,
                "showdown": 5,
                "finished": 0,
            }[phase]
        ]
        for seat, view in views.items():
            self.assertEqual(set(view), HAND_FIELDS | TIMING_FIELDS)
            self.assertEqual(view["type"], "snapshot")
            self.assertEqual(view["status"], "ready")
            self.assertEqual((view["seat"], view["bet_unit"]), (seat, 10))
            self.assertEqual((view["revision"], view["hand_id"]), (revision, hand))
            self.assertEqual(
                (view["phase"], view["actor"], view["button"]), (phase, actor, button)
            )
            self.assertEqual(
                (view["stacks"], view["pot"]), (dict(zip(("A", "B"), stack)), pot)
            )
            self.assertEqual(
                view["contributions"], dict(zip(("A", "B"), contributions))
            )
            self.assertEqual(view["board"], expected_board)
            self.assertEqual(sum(view["stacks"].values()) + view["pot"], 400)
            self.assertGreaterEqual(min(*view["stacks"].values(), view["pot"]), 0)
            self.assertEqual(view["own_hole_cards"], self.cards[seat])
            self.assertEqual(
                len(set(view["own_hole_cards"] + expected_board)),
                2 + len(expected_board),
            )
            if seat != actor:
                self.assertEqual(view["legal_actions"], [])
            if phase not in {"showdown", "finished"}:
                self.assertIsNone(view["result"])
            self.assertIsNone(view["match_winner"])
            other = "B" if seat == "A" else "A"
            hidden = list(self.deck[4 + len(expected_board) :])
            if phase != "showdown":
                hidden += self.cards[other]
            self.assert_no_values(
                view, (*hidden, "test-game-room", "test-session-a", "test-session-b")
            )

        private = {"seat", "own_hole_cards", "legal_actions", "can_ready"}
        self.assertEqual(
            *(
                {key: value for key, value in view.items() if key not in private}
                for view in views.values()
            )
        )
        return views

    def assert_no_values(self, payload, forbidden):
        encoded = json.dumps(payload)
        for value in forbidden:
            self.assertNotIn(json.dumps(value), encoded)

    def send(self, seat, command):
        socket = self.sockets[seat]
        socket.send_json(command)
        ack = socket.receive_json()
        self.assertEqual(
            set(ack),
            {
                "type",
                "action_id",
                "hand_id",
                "outcome_revision",
                "accepted",
                "error_code",
            },
        )
        self.assertEqual(ack["type"], "action_ack")
        self.assertEqual(
            (ack["action_id"], ack["hand_id"]),
            (command["action_id"], command["hand_id"]),
        )
        self.assert_no_values(
            ack, (*self.deck, "test-game-room", "test-session-a", "test-session-b")
        )
        return ack

    def bet(self, seat, move, revision, **state):
        cmd = wire_action(f"action-{revision}", move, revision)
        ack = self.send(seat, cmd)
        self.assertEqual(
            (ack["accepted"], ack["outcome_revision"], ack["error_code"]),
            (True, revision + 1, None),
        )
        return cmd, ack, self.assert_views(revision=revision + 1, **state)

    def settled(self, scenario, final_stack, kind, winner):
        with self.game(scenario):
            states = [
                ("preflop", "B", (10, 10)),
                ("flop", "B", (0, 0)),
                ("flop", "A", (0, 0)),
                ("turn", "B", (0, 0)),
                ("turn", "A", (0, 0)),
                ("river", "B", (0, 0)),
                ("river", "A", (0, 0)),
                ("showdown", None, (0, 0)),
            ]
            for revision, (seat, (phase, actor, contrib)) in enumerate(
                zip(CHECK_THROUGH, states), 1
            ):
                terminal = phase == "showdown"
                command, ack, views = self.bet(
                    seat,
                    "call" if revision == 1 else "check",
                    revision,
                    stack=final_stack if terminal else (190, 190),
                    pot=0 if terminal else 20,
                    phase=phase,
                    actor=actor,
                    contributions=contrib,
                )
            for view in views.values():
                self.assertEqual(
                    view["result"],
                    {
                        "kind": kind,
                        "winner": winner,
                        "showdown_hole_cards": self.cards,
                    },
                )
                self.assertTrue(view["can_ready"])
            settled = self.rooms.snapshot()
            self.assertEqual(self.send("A", command), ack)
            self.assertEqual(
                self.send("B", wire_action("ended", "bet", 9))["error_code"],
                "HAND_COMPLETE",
            )
            self.assertIs(self.rooms.snapshot(), settled)

    def test_flush_beats_straight_and_settlement_replay_does_not_pay_twice(self):
        self.settled("showdown", (210, 190), "showdown_win", "A")

    def test_royal_flush_on_board_splits_pot(self):
        self.settled("tie", (200, 200), "showdown_tie", None)

    def test_fold_pays_opponent_and_both_views_preserve_privacy(self):
        with self.game("fold"):
            _, _, views = self.bet(
                "A",
                "fold",
                1,
                stack=(195, 205),
                pot=0,
                phase="finished",
                actor=None,
                contributions=(0, 0),
            )
            for view in views.values():
                self.assertEqual(view["result"], {"kind": "fold_win", "winner": "B"})

    def test_flop_bet_raises_cap_and_call_exact_accounting(self):
        with self.game("showdown"):
            for revision, (
                seat,
                move,
                stack,
                pot,
                phase,
                actor,
                contributions,
            ) in enumerate(
                (
                    ("A", "call", (190, 190), 20, "preflop", "B", (10, 10)),
                    ("B", "check", (190, 190), 20, "flop", "B", (0, 0)),
                    ("B", "bet", (190, 180), 30, "flop", "A", (0, 10)),
                    ("A", "raise", (170, 180), 50, "flop", "B", (20, 10)),
                    ("B", "raise", (170, 160), 70, "flop", "A", (20, 30)),
                ),
                1,
            ):
                self.bet(
                    seat,
                    move,
                    revision,
                    stack=stack,
                    pot=pot,
                    phase=phase,
                    actor=actor,
                    contributions=contributions,
                )
            capped = self.rooms.snapshot()
            self.assertEqual(
                self.send("A", wire_action("cap", "raise", 6))["error_code"],
                "ILLEGAL_ACTION",
            )
            self.assertIs(self.rooms.snapshot(), capped)
            self.bet(
                "A",
                "call",
                6,
                stack=(160, 160),
                pot=80,
                phase="turn",
                actor="B",
                contributions=(0, 0),
            )

    def test_malformed_unauthorized_and_stale_frames_preserve_room(self):
        with self.game("showdown"):
            initial = self.rooms.snapshot()
            with self.client.websocket_connect("/ws") as stranger:
                stranger.send_json(wire_action("unauth", "fold", 1))
                with self.assertRaises(WebSocketDisconnect):
                    stranger.receive_json()
            with self.client.websocket_connect("/ws") as stranger:
                self.auth(stranger, "wrong-token")
                self.assertEqual(stranger.receive_json()["code"], "UNAUTHORIZED")
                with self.assertRaises(WebSocketDisconnect):
                    stranger.receive_json()

            cmd = wire_action("bad", "call", 1)
            a = self.sockets["A"]
            frames = [
                "{",
                "[]",
                "12",
                "x" * 4097,
                json.dumps({**cmd, "seat": "B"}),
                json.dumps({**cmd, "amount": 10}),
                json.dumps({**cmd, "expected_revision": True}),
                json.dumps({**cmd, "hand_id": False}),
                json.dumps({**cmd, "action": "all-in"}),
                json.dumps(
                    {key: value for key, value in cmd.items() if key != "action_id"}
                ),
            ]
            for frame in frames:
                a.send_text(frame)
                self.assertEqual(
                    a.receive_json(), {"type": "error", "code": "INVALID_MESSAGE"}
                )
            a.send_bytes(b"{}")
            self.assertEqual(
                a.receive_json(), {"type": "error", "code": "INVALID_MESSAGE"}
            )
            for i, revision, hand, code in (
                (1, 0, 1, "STALE_REVISION"),
                (2, 2, 1, "STALE_REVISION"),
                (3, 1, 2, "WRONG_HAND"),
            ):
                rejected = self.send(
                    "A", wire_action(f"bad{i}", "call", revision, hand)
                )
                self.assertEqual(
                    (rejected["error_code"], rejected["outcome_revision"]), (code, 1)
                )
                self.assertEqual(a.receive_json()["revision"], 1)
            for seat, impersonated in (("A", "B"), ("B", "A")):
                sock = self.sockets[seat]
                sock.send_json({**cmd, "seat": impersonated})
                self.assertEqual(sock.receive_json()["code"], "INVALID_MESSAGE")
            self.assertEqual(
                self.send("B", wire_action("turn", "fold", 1))["error_code"],
                "WRONG_TURN",
            )
            a.send_json({"type": "ping"})
            self.assertEqual(a.receive_json(), {"type": "pong"})
            a.send_json({"type": "snapshot_request"})
            self.assertEqual(a.receive_json()["revision"], 1)
            self.assertIs(self.rooms.snapshot(), initial)

    def test_replacement_receives_current_snapshot_and_can_continue(self):
        with self.game("showdown"):
            self.bet(
                "A",
                "call",
                1,
                stack=(190, 190),
                pot=20,
                phase="preflop",
                actor="B",
                contributions=(10, 10),
            )
            old = self.sockets["B"]
            with self.client.websocket_connect("/ws") as replacement:
                self.auth(replacement, "test-session-b")
                self.assertEqual(replacement.receive_json()["revision"], 2)
                with self.assertRaises(WebSocketDisconnect) as caught:
                    old.receive_json()
                self.assertEqual(caught.exception.code, 4000)
                self.sockets["B"] = replacement
                self.bet(
                    "B",
                    "check",
                    2,
                    stack=(190, 190),
                    pot=20,
                    phase="flop",
                    actor="B",
                    contributions=(0, 0),
                )

    def test_ready_advances_over_transport_and_retains_previous_ack(self):
        with self.game("fold"):
            _, _, _ = self.bet(
                "A",
                "fold",
                1,
                stack=(195, 205),
                pot=0,
                phase="finished",
                actor=None,
                contributions=(0, 0),
            )
            a_ready = {
                "type": "ready",
                "action_id": "same",
                "hand_id": 1,
                "expected_revision": 2,
            }
            first = self.send("A", a_ready)
            self.assertTrue(first["accepted"])
            for socket in self.sockets.values():
                view = socket.receive_json()
                self.assertEqual(
                    (view["revision"], view["hand_id"], view["ready_seats"]),
                    (3, 1, {"A": True, "B": False}),
                )
            self.assertEqual(self.send("A", a_ready), first)
            second = self.send("B", {**a_ready, "expected_revision": 3})
            self.assertTrue(second["accepted"])
            for socket in self.sockets.values():
                view = socket.receive_json()
                self.assertEqual(
                    (view["revision"], view["hand_id"], view["button"]), (4, 2, "B")
                )
                self.assertEqual(
                    (view["stacks"], view["pot"]), ({"A": 185, "B": 200}, 15)
                )
            self.assertEqual(self.send("A", a_ready), first)

    def test_gameplay_revision_is_isolated_between_app_instances(self):
        with self.game("fold"):
            with TestClient(create_app()) as other:
                response = other.post("/api/rooms", json={"bet_unit": 12})
                self.assertEqual(response.status_code, 201)
                with other.websocket_connect("/ws") as host:
                    self.auth(host, response.json()["session_token"])
                    self.assertEqual(host.receive_json()["revision"], 0)
                    self.bet(
                        "A",
                        "fold",
                        1,
                        stack=(195, 205),
                        pot=0,
                        phase="finished",
                        actor=None,
                        contributions=(0, 0),
                    )
                    host.send_json({"type": "snapshot_request"})
                    self.assertEqual(
                        host.receive_json(),
                        {
                            "type": "snapshot",
                            "status": "waiting",
                            "seat": "A",
                            "bet_unit": 12,
                            "revision": 0,
                            "lifecycle": "waiting",
                            "lifecycle_revision": 1,
                            "presence": {"A": True, "B": False},
                            "turn_clock": {
                                "status": "inactive",
                                "acting_player": None,
                                "remaining_ms": None,
                            },
                            "disconnect_grace": {"A": None, "B": None},
                            "match_result": None,
                            "last_automatic_action": None,
                        },
                    )
