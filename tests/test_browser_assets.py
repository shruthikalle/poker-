import unittest

from fastapi.testclient import TestClient

from poker.server import create_app


class BrowserAssetsTests(unittest.TestCase):
    def test_app_and_css_are_local_and_api_keeps_its_route(self):
        with TestClient(create_app()) as client:
            page = client.get("/")
            self.assertEqual(page.status_code, 200)
            self.assertIn("Heads-Up Live Poker", page.text)
            self.assertIn("default-src 'self'", page.headers["content-security-policy"])
            self.assertEqual(client.get("/assets/styles.css").status_code, 200)
            self.assertEqual(client.get("/health").json(), {"status": "ok"})

    def test_static_path_cannot_read_repository_files(self):
        with TestClient(create_app()) as client:
            for path in (
                "README.md",
                ".env",
                "evidence/browser-interface/baseline.txt",
                "%2e%2e/%2e%2e/pyproject.toml",
            ):
                with self.subTest(path=path):
                    self.assertEqual(client.get("/assets/" + path).status_code, 404)
