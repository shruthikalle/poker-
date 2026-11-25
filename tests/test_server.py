import unittest

from fastapi.testclient import TestClient

from poker.rooms import RoomManager
from poker.server import create_app


class HealthTests(unittest.TestCase):
    def test_health_returns_only_running_status(self) -> None:
        with TestClient(create_app()) as client:
            response = client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})


class RoomHTTPTests(unittest.TestCase):
    def setUp(self) -> None:
        tokens = iter(("test-session-a", "test-session-b"))
        self.rooms = RoomManager(
            code_factory=lambda: "test-room-code", token_factory=tokens.__next__
        )
        self.client = self.enterContext(TestClient(create_app(self.rooms)))

    def create_room(self):
        response = self.client.post("/api/rooms", json={"bet_unit": 10})
        self.assertEqual(response.status_code, 201)
        return response

    def join_room(self, **extra):
        return self.client.post(
            "/api/rooms/join", json={"room_code": "test-room-code", **extra}
        )

    def test_create_and_join_return_only_callers_admission(self) -> None:
        host = self.create_room()
        guest = self.join_room()

        self.assertEqual(
            host.json(),
            {
                "room_code": "test-room-code",
                "seat": "A",
                "session_token": "test-session-a",
                "bet_unit": 10,
                "status": "waiting",
            },
        )
        self.assertEqual(guest.status_code, 200)
        self.assertEqual(
            guest.json(),
            {
                "room_code": "test-room-code",
                "seat": "B",
                "session_token": "test-session-b",
                "bet_unit": 10,
                "status": "ready",
            },
        )
        self.assertEqual(host.headers["cache-control"], "no-store")
        self.assertEqual(guest.headers["cache-control"], "no-store")

    def test_invalid_creation_requests_leave_room_empty(self) -> None:
        invalid_bodies = (
            {},
            {"bet_unit": True},
            {"bet_unit": "10"},
            {"bet_unit": 10.0},
            {"bet_unit": 2.5},
            {"bet_unit": 0},
            {"bet_unit": 3},
            {"bet_unit": 22},
            {"bet_unit": 10, "seat": "B"},
            [{"bet_unit": 10}],
        )
        for body in invalid_bodies:
            with self.subTest(body=body):
                response = self.client.post("/api/rooms", json=body)
                self.assertEqual(response.status_code, 422)
                self.assertIsNone(self.rooms.snapshot())
        self.create_room()

    def test_malformed_json_returns_fixed_error_without_mutation(self) -> None:
        self.create_room()
        waiting = self.rooms.snapshot()
        response = self.client.post(
            "/api/rooms/join",
            content='{"room_code":"test-room-code","session_token":"test-session-a"',
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json(), {"detail": "invalid request body"})
        self.assertIs(self.rooms.snapshot(), waiting)

    def test_wrong_code_and_seat_claim_leave_waiting_room_unchanged(self) -> None:
        self.create_room()
        waiting = self.rooms.snapshot()
        unknown = self.client.post("/api/rooms/join", json={"room_code": "wrong"})
        self.assertEqual(unknown.status_code, 404)
        self.assertEqual(unknown.json(), {"detail": "room not found"})
        self.assertIs(self.rooms.snapshot(), waiting)

        claim = self.join_room(seat="A", session_token="test-session-a")
        self.assertEqual(claim.status_code, 422)
        self.assertEqual(claim.json(), {"detail": "invalid request body"})
        self.assertIs(self.rooms.snapshot(), waiting)
        self.assertEqual(self.join_room().json()["seat"], "B")

    def test_full_room_and_second_creation_return_conflicts_without_mutation(self):
        self.create_room()
        self.assertEqual(self.join_room().status_code, 200)
        full = self.rooms.snapshot()

        third = self.join_room()
        self.assertEqual(third.status_code, 409)
        self.assertEqual(third.json(), {"detail": "room is full"})
        self.assertIs(self.rooms.snapshot(), full)
        second = self.client.post("/api/rooms", json={"bet_unit": 20})
        self.assertEqual(second.status_code, 409)
        self.assertEqual(second.json(), {"detail": "an active room already exists"})
        self.assertIs(self.rooms.snapshot(), full)

    def test_application_instances_have_independent_room_state(self) -> None:
        with (
            TestClient(create_app()) as first_client,
            TestClient(create_app()) as second_client,
        ):
            first = first_client.post("/api/rooms", json={"bet_unit": 2})
            self.assertEqual(first.status_code, 201)
            missing = second_client.post(
                "/api/rooms/join", json={"room_code": first.json()["room_code"]}
            )
            self.assertEqual(missing.status_code, 404)
            second = second_client.post("/api/rooms", json={"bet_unit": 20})
            self.assertEqual(second.status_code, 201)
            self.assertEqual(second.json()["bet_unit"], 20)
