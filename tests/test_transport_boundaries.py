import unittest

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from poker.server import create_app


class TransportBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.client = self.enterContext(
            TestClient(create_app(), base_url="http://127.0.0.1:8999")
        )

    def test_foreign_browser_origins_never_allocate_a_seat(self):
        for origin in (
            "https://example.invalid",
            "http://127.0.0.1:8998",
            "http://localhost:8999",
            "https://127.0.0.1:8999",
            "http://127.0.0.1:8999/other",
            "http://127.0.0.1:bad",
            "null",
        ):
            with self.subTest(origin=origin):
                response = self.client.post(
                    "/api/rooms",
                    json={"bet_unit": 10},
                    headers={
                        "Origin": origin,
                        "Admission-Key": "a" * 64,
                    },
                )
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json(), {"detail": "origin not allowed"})
        create = self.client.post(
            "/api/rooms",
            json={"bet_unit": 10},
            headers={
                "Origin": "http://127.0.0.1:8999",
                "Admission-Key": "a" * 64,
            },
        )
        self.assertEqual(create.status_code, 201)
        join = self.client.post(
            "/api/rooms/join", json={"room_code": create.json()["room_code"]}
        )
        self.assertEqual(join.status_code, 200)

    def test_websocket_rejects_other_loopback_ports_and_accepts_same_origin(self):
        with self.assertRaises(WebSocketDisconnect) as error:
            with self.client.websocket_connect(
                "ws://127.0.0.1:8999/ws", headers={"Origin": "http://127.0.0.1:8998"}
            ):
                self.fail("unexpected foreign-origin connection")
        self.assertEqual(error.exception.code, 1008)
        room = self.client.post("/api/rooms", json={"bet_unit": 10}).json()
        with self.client.websocket_connect(
            "ws://127.0.0.1:8999/ws", headers={"Origin": "http://127.0.0.1:8999"}
        ) as ws:
            ws.send_json(
                {
                    "type": "auth",
                    "token": room["session_token"],
                    "protocol": "gameplay.v1",
                }
            )
            self.assertEqual(ws.receive_json()["seat"], "A")

    def test_static_mount_rejects_nonasset_paths(self):
        for filename in (
            ".git/config",
            ".env",
            "pyproject.toml",
            "uv.lock",
            "poker/engine.py",
            "evidence/browser-reliability/baseline.txt",
            "%2e%2e%2f%2e%2e%2f.git%2fconfig",
            "%252e%252e%252fpyproject.toml",
        ):
            with self.subTest(filename=filename):
                response = self.client.get(f"/assets/{filename}")
                self.assertEqual(response.status_code, 404)
        self.assertEqual(self.client.get("/assets/js/session.mjs").status_code, 200)
