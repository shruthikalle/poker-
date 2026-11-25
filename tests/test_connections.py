"""Authenticated lobby WebSockets and replacement-safe connection tracking."""

import unittest

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from server.main import create_app


class ConnectionTests(unittest.TestCase):
    def setUp(self) -> None:
        tokens = iter(("token-A", "token-B"))
        self.client = TestClient(create_app(lambda: "ROOM42", lambda: next(tokens)))
        self.client.post("/api/table")

    def test_join_and_websocket_lobby_updates(self) -> None:
        with self.client.websocket_connect("/ws") as a:
            a.send_json({"type": "auth", "token": "token-A"})
            self.assertEqual(
                a.receive_json(),
                {
                    "type": "lobby",
                    "your_seat": "A",
                    "table_ready": False,
                    "connected": {"A": True, "B": False},
                },
            )
            self.assertEqual(
                self.client.post("/api/join", json={"room_code": "ROOM42"}).status_code,
                201,
            )
            self.assertEqual(a.receive_json()["table_ready"], True)
            with self.client.websocket_connect("/ws") as b:
                b.send_json({"type": "auth", "token": "token-B"})
                a_view = a.receive_json()
                b_view = b.receive_json()
                self.assertEqual(a_view["connected"], {"A": True, "B": True})
                self.assertEqual(b_view["connected"], {"A": True, "B": True})
                self.assertEqual((a_view["your_seat"], b_view["your_seat"]), ("A", "B"))
                for view in (a_view, b_view):
                    self.assertNotIn("token-A", str(view))
                    self.assertNotIn("token-B", str(view))
                    self.assertNotIn("hole_cards", view)
                    self.assertNotIn("deck", view)
            self.assertEqual(a.receive_json()["connected"], {"A": True, "B": False})

    def test_invalid_auth_and_client_selected_seat_are_rejected(self) -> None:
        for message, code in (
            ({"type": "auth", "token": "ROOM42"}, "UNAUTHORIZED"),
            ({"type": "auth", "token": "token-A", "seat": "B"}, "INVALID_MESSAGE"),
            ({"type": "action", "action": "call"}, "INVALID_MESSAGE"),
        ):
            with (
                self.subTest(message=message),
                self.client.websocket_connect("/ws") as ws,
            ):
                ws.send_json(message)
                error = ws.receive_json()
                self.assertEqual(error["code"], code)
                self.assertNotIn("room_code", error)
                with self.assertRaises(WebSocketDisconnect):
                    ws.receive_json()

    def test_replaced_socket_cannot_remove_new_connection(self) -> None:
        with self.client.websocket_connect("/ws") as old:
            old.send_json({"type": "auth", "token": "token-A"})
            old.receive_json()
            with self.client.websocket_connect("/ws") as new:
                new.send_json({"type": "auth", "token": "token-A"})
                self.assertEqual(new.receive_json()["connected"]["A"], True)
                with self.assertRaises(WebSocketDisconnect):
                    old.receive_json()
                new.send_json({"type": "ping"})
                self.assertEqual(new.receive_json(), {"type": "pong"})

    def test_game_action_is_not_applied_before_engine_integration(self) -> None:
        self.client.post("/api/join", json={"room_code": "ROOM42"})
        with self.client.websocket_connect("/ws") as a:
            a.send_json({"type": "auth", "token": "token-A"})
            a.receive_json()
            a.send_json({"type": "action", "action_id": "a1", "action": "call"})
            self.assertEqual(a.receive_json()["code"], "NOT_READY")
            a.send_text("not-json")
            self.assertEqual(a.receive_json()["code"], "INVALID_MESSAGE")
            a.send_bytes(b"\xff")
            self.assertEqual(a.receive_json()["code"], "INVALID_MESSAGE")

    def test_rejects_foreign_origin_and_oversized_auth_message(self) -> None:
        with (
            self.assertRaises(WebSocketDisconnect),
            self.client.websocket_connect(
                "/ws", headers={"Origin": "https://other.example"}
            ),
        ):
            pass
        with self.client.websocket_connect("/ws") as ws:
            ws.send_text('{"type":"auth","token":"' + ("x" * 4096) + '"}')
            self.assertEqual(ws.receive_json()["code"], "INVALID_MESSAGE")
            with self.assertRaises(WebSocketDisconnect):
                ws.receive_json()


if __name__ == "__main__":
    unittest.main()
