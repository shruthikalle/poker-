"""The two admission contracts share a single room and engine hand."""

import unittest

from fastapi.testclient import TestClient

from poker.rooms import RoomManager
from poker.server import create_app


class CombinedAdmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        tokens = iter(("test-token-a", "test-token-b"))
        self.rooms = RoomManager(
            ruleset="legacy",
            code_factory=lambda: "test-room",
            token_factory=tokens.__next__,
        )
        self.client = self.enterContext(TestClient(create_app(self.rooms)))

    def test_room_creation_then_lobby_join_deals_with_host_bet_unit(self) -> None:
        host = self.client.post("/api/rooms", json={"bet_unit": 12})
        self.assertEqual(host.status_code, 201)
        self.assertIsNone(self.rooms.snapshot().hand)

        with self.client.websocket_connect("/ws") as host_socket:
            host_socket.send_json({"type": "auth", "token": "test-token-a"})
            self.assertEqual(
                host_socket.receive_json(),
                {
                    "type": "lobby",
                    "your_seat": "A",
                    "table_ready": False,
                    "connected": {"A": True, "B": False},
                },
            )
            joined = self.client.post("/api/join", json={"room_code": "test-room"})
            self.assertEqual(joined.status_code, 201)
            self.assertEqual(
                joined.json(), {"seat": "B", "session_token": "test-token-b"}
            )
            self.assertEqual(
                host_socket.receive_json(),
                {
                    "type": "lobby",
                    "your_seat": "A",
                    "table_ready": True,
                    "connected": {"A": True, "B": False},
                },
            )

        hand = self.rooms.snapshot().hand
        self.assertEqual(
            (hand.hand_number, hand.actor, hand.stacks, hand.contributions, hand.pot),
            (1, "A", (234, 228), (6, 12), 18),
        )
        third = self.client.post("/api/rooms/join", json={"room_code": "test-room"})
        self.assertEqual(third.status_code, 409)
        self.assertIs(self.rooms.snapshot().hand, hand)

    def test_lobby_creation_then_room_join_uses_default_and_broadcasts(self) -> None:
        host = self.client.post("/api/table")
        self.assertEqual(host.status_code, 201)
        self.assertEqual(
            host.json(),
            {"room_code": "test-room", "seat": "A", "session_token": "test-token-a"},
        )
        self.assertEqual(host.headers["cache-control"], "no-store")
        self.assertIsNone(self.rooms.snapshot().hand)
        duplicate = self.client.post("/api/rooms", json={"bet_unit": 18})
        self.assertEqual(duplicate.status_code, 409)
        with self.client.websocket_connect("/ws") as host_socket:
            host_socket.send_json({"type": "auth", "token": "test-token-a"})
            self.assertFalse(host_socket.receive_json()["table_ready"])

            joined = self.client.post(
                "/api/rooms/join", json={"room_code": "test-room"}
            )
            self.assertEqual(joined.status_code, 200)
            self.assertEqual(joined.json()["bet_unit"], 10)
            self.assertTrue(host_socket.receive_json()["table_ready"])

        bearer = self.client.get(
            "/api/session", headers={"Authorization": "Bearer test-token-b"}
        )
        self.assertEqual(bearer.json(), {"seat": "B", "table_ready": True})
        self.assertEqual(self.rooms.snapshot().hand.stacks, (195, 190))

    def test_unknown_non_ascii_room_code_returns_404_without_claiming_seat(
        self,
    ) -> None:
        self.assertEqual(self.client.post("/api/table").status_code, 201)
        waiting = self.rooms.snapshot()
        for endpoint, detail in (
            ("/api/join", {"code": "INVALID_CODE", "message": "Table code not found"}),
            ("/api/rooms/join", "room not found"),
        ):
            with self.subTest(endpoint=endpoint):
                response = self.client.post(endpoint, json={"room_code": "café"})
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.json(), {"detail": detail})
                self.assertIs(self.rooms.snapshot(), waiting)
