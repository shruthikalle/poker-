"""Admission and identity checks for the first server milestone."""

import unittest

from fastapi.testclient import TestClient

from server.main import create_app


class AdmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        tokens = iter(("token-A", "token-B"))
        self.client = TestClient(create_app(lambda: "ROOM42", lambda: next(tokens)))

    def test_create_join_and_private_seat_identity(self) -> None:
        self.assertEqual(self.client.get("/health").json(), {"status": "ok"})
        created = self.client.post("/api/table")
        self.assertEqual(created.status_code, 201)
        self.assertEqual(
            created.json(),
            {"room_code": "ROOM42", "seat": "A", "session_token": "token-A"},
        )
        self.assertEqual(
            self.client.get(
                "/api/session", headers={"Authorization": "Bearer token-A"}
            ).json(),
            {"seat": "A", "table_ready": False},
        )

        joined = self.client.post("/api/join", json={"room_code": "ROOM42"})
        self.assertEqual(joined.status_code, 201)
        self.assertEqual(joined.json(), {"seat": "B", "session_token": "token-B"})
        for seat, token in (("A", "token-A"), ("B", "token-B")):
            with self.subTest(seat=seat):
                response = self.client.get(
                    "/api/session", headers={"Authorization": f"Bearer {token}"}
                )
                self.assertEqual(response.json(), {"seat": seat, "table_ready": True})
                self.assertNotIn("session_token", response.text)

    def test_invalid_code_and_third_join_do_not_take_a_seat(self) -> None:
        self.client.post("/api/table")
        invalid = self.client.post("/api/join", json={"room_code": "WRONG"})
        self.assertEqual(invalid.status_code, 404)
        self.assertEqual(invalid.json()["detail"]["code"], "INVALID_CODE")
        self.assertFalse(
            self.client.get(
                "/api/session", headers={"Authorization": "Bearer token-A"}
            ).json()["table_ready"]
        )
        self.assertEqual(
            self.client.post("/api/join", json={"room_code": "ROOM42"}).status_code, 201
        )
        full = self.client.post("/api/join", json={"room_code": "ROOM42"})
        self.assertEqual(full.status_code, 409)
        self.assertEqual(full.json()["detail"]["code"], "TABLE_FULL")

    def test_no_token_or_room_code_can_impersonate_another_seat(self) -> None:
        self.client.post("/api/table")
        self.client.post("/api/join", json={"room_code": "ROOM42"})
        for authorization in (None, "Bearer ROOM42", "Bearer token-A-wrong", "token-A"):
            with self.subTest(authorization=authorization):
                headers = {"Authorization": authorization} if authorization else {}
                result = self.client.get("/api/session", headers=headers)
                self.assertEqual(result.status_code, 401)
                self.assertEqual(result.json()["detail"]["code"], "UNAUTHORIZED")

    def test_duplicate_table_and_malformed_join(self) -> None:
        self.assertEqual(self.client.post("/api/table").status_code, 201)
        duplicate = self.client.post("/api/table")
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(duplicate.json()["detail"]["code"], "TABLE_EXISTS")
        for payload in ({"room_code": ""}, {"room_code": "ROOM42", "seat": "A"}):
            with self.subTest(payload=payload):
                self.assertEqual(
                    self.client.post("/api/join", json=payload).status_code, 422
                )


if __name__ == "__main__":
    unittest.main()
