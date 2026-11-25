import unittest

from fastapi.testclient import TestClient

from poker.server import create_app


class HealthTests(unittest.TestCase):
    def test_health_returns_only_running_status(self) -> None:
        with TestClient(create_app()) as client:
            response = client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
