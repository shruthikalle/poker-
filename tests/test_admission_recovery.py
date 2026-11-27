import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from fastapi.testclient import TestClient

from poker.rooms import RoomManager
from poker.server import create_app


class AdmissionRecoveryTests(unittest.TestCase):
    def setUp(self):
        tokens = iter(("fixture-seat-a", "fixture-seat-b"))
        self.rooms = RoomManager(
            code_factory=lambda: "TESTROOM", token_factory=lambda: next(tokens)
        )
        self.client = self.enterContext(TestClient(create_app(self.rooms)))

    def post(self, intent, value, key=None):
        path = "/api/rooms" if intent == "create" else "/api/rooms/join"
        field = "bet_unit" if intent == "create" else "room_code"
        headers = {} if key is None else {"Admission-Key": key}
        return self.client.post(path, json={field: value}, headers=headers)

    def test_original_responses_survive_join_and_later_retries(self):
        create = self.post("create", 10, "a" * 64)
        self.assertEqual(create.status_code, 201)
        join = self.post("join", "TESTROOM", "b" * 64)
        self.assertEqual(join.status_code, 200)
        self.assertEqual(create.json()["status"], "waiting")
        room = self.rooms.snapshot()
        for kind, value, key, original in (
            ("create", 10, "a", create),
            ("join", "TESTROOM", "b", join),
        ):
            retry = self.post(kind, value, key * 64)
            self.assertEqual(retry.status_code, original.status_code)
            self.assertEqual(retry.json(), original.json())
            self.assertEqual(retry.headers["cache-control"], "no-store")
            self.assertIs(self.rooms.snapshot(), room)
        self.assertEqual(room.revision, 1)
        self.assertEqual(room.hand.pot, 15)
        self.assertNotEqual(
            create.json()["session_token"], join.json()["session_token"]
        )

    def test_concurrent_identical_create_and_join(self):
        for intent, value, key, status in (
            ("create", 10, "a" * 64, 201),
            ("join", "TESTROOM", "b" * 64, 200),
        ):
            with self.subTest(intent=intent):
                gate = Barrier(4)

                def send():
                    gate.wait(timeout=3)
                    return self.post(intent, value, key)

                with ThreadPoolExecutor(max_workers=4) as pool:
                    results = [pool.submit(send) for _ in range(4)]
                responses = [result.result() for result in results]
                self.assertEqual([resp.status_code for resp in responses], [status] * 4)
                self.assertTrue(
                    all(resp.json() == responses[0].json() for resp in responses)
                )
        self.assertEqual(self.rooms.snapshot().revision, 1)
        self.assertEqual(self.rooms.snapshot().hand.pot, 15)

    def test_conflicting_reuse_does_not_disclose_credentials(self):
        self.assertEqual(self.post("create", 10, "a" * 64).status_code, 201)
        for intent, value in (("create", 12), ("join", "TESTROOM")):
            retry = self.post(intent, value, "a" * 64)
            self.assertEqual(retry.status_code, 409)
            self.assertEqual(retry.json(), {"detail": "admission key conflict"})
        self.assertEqual(self.post("join", "TESTROOM", "b" * 64).status_code, 200)
        retry = self.post("join", "OTHERROOM", "b" * 64)
        self.assertEqual(retry.status_code, 409)
        self.assertEqual(retry.json(), {"detail": "admission key conflict"})

    def test_malformed_keys_are_rejected_without_echo_or_allocation(self):
        for headers in (
            [("Admission-Key", "invalid-marker")],
            [("Admission-Key", "A" * 64)],
            [("Admission-Key", "a" * 64), ("Admission-Key", "b" * 64)],
        ):
            result = self.client.post(
                "/api/rooms", json={"bet_unit": 10}, headers=headers
            )
            self.assertEqual(result.status_code, 422)
            self.assertEqual(result.json(), {"detail": "invalid admission key"})
        self.assertIsNone(self.rooms.snapshot())

    def test_unknown_and_unkeyed_requests_cannot_recover_reserved_seats(self):
        self.assertEqual(self.post("create", 10, "a" * 64).status_code, 201)
        self.assertEqual(self.post("join", "TESTROOM", "b" * 64).status_code, 200)
        for kind, value in (("create", 10), ("join", "TESTROOM")):
            for key in (None, "c" * 64):
                result = self.post(kind, value, key)
                self.assertEqual(result.status_code, 409)
                self.assertEqual(set(result.json()), {"detail"})

    def test_rejected_request_flood_cannot_consume_or_evict_replay_storage(self):
        create = self.post("create", 10, "a" * 64)
        for number in range(48):
            self.assertEqual(
                self.post("join", "MISSING", f"{number:064x}").status_code, 404
            )
        self.assertEqual(len(self.rooms._admissions), 1)
        join = self.post("join", "TESTROOM", "b" * 64)
        for number in range(48):
            self.assertEqual(
                self.post("join", "TESTROOM", f"{number:064x}").status_code, 409
            )
        self.assertEqual(len(self.rooms._admissions), 2)
        self.assertEqual(self.post("create", 10, "a" * 64).json(), create.json())
        self.assertEqual(self.post("join", "TESTROOM", "b" * 64).json(), join.json())
