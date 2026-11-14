"""Verify database-backed HTTP readiness responses."""

from importlib.util import find_spec
import unittest
from unittest.mock import Mock

from src.managers.io_manager import IOManager


@unittest.skipUnless(find_spec("fastapi") and find_spec("httpx"), "HTTP dependencies unavailable")
class ReadinessEndpointTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient

        self.data = Mock()
        self.data.get_health.return_value = {"status": "ok"}
        self.client = TestClient(IOManager(self.data, Mock()).get_application())

    def tearDown(self):
        self.client.close()

    def test_health_and_ready_succeed_when_the_database_is_migrated(self):
        for path in ("/health", "/ready"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), {"status": "ok"})

        self.assertEqual(self.data.get_health.call_count, 2)

    def test_health_and_ready_fail_closed_without_leaking_database_errors(self):
        self.data.get_health.side_effect = RuntimeError(
            "database unavailable: password=must-not-leak"
        )

        for path in ("/health", "/ready"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json(), {"status": "unavailable"})
                self.assertNotIn("must-not-leak", response.text)


if __name__ == "__main__":
    unittest.main()
