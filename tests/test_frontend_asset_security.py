"""Regression tests for the frontend's static-asset security boundary."""

import unittest

from fastapi.testclient import TestClient

from src.managers.io_manager import IOManager


class FrontendAssetSecurityTests(unittest.TestCase):
    def setUp(self):
        # Static asset requests do not need a database or application data manager.
        self.client = TestClient(IOManager(None, None).get_application())

    def test_registered_assets_include_safe_response_headers(self):
        response = self.client.get("/static/app.js")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_private_and_traversal_paths_are_not_served(self):
        paths = (
            "/static/.env",
            "/static/../.env",
            "/static/%2e%2e%2f.env",
            "/static/..%5C.env",
            "/static/documents/originals/test.pdf",
            "/frontend/templates/index.html",
        )

        for path in paths:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)


if __name__ == "__main__":
    unittest.main()
