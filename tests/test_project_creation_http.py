"""Exercise project creation through the application factory and HTTP route."""

from contextlib import contextmanager
from importlib.util import find_spec
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from src.config.limits import JSON_BYTES
from src.config.settings import Settings
from src.main import create_app


@unittest.skipUnless(
    find_spec("fastapi") and find_spec("httpx"),
    "HTTP dependencies unavailable",
)
class ProjectCreationHTTPTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient

        self.client_class = TestClient
        self.data = Mock()
        self.data.get_health.return_value = {"status": "ok"}
        self.data.create_project.return_value = {"id": "project-id"}
        self.settings = Settings("postgresql://localhost/test", document_directory=Path.cwd())
        self.app = create_app(settings=self.settings, data=self.data)

    def test_creates_project_from_json(self):
        with self.client_class(self.app) as client:
            response = client.post(
                "/api/projects",
                json={"name": "Trimester", "week_count": 14},
            )

        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json(), {"id": "project-id"})
        self.data.create_project.assert_called_once_with("Trimester", 14)

    def test_rejects_bad_json_and_oversized_bodies_before_persistence(self):
        with self.client_class(self.app) as client:
            cases = (
                ('{"name":"A","name":"B"}', 422, "invalid_request"),
                (" " * (JSON_BYTES + 1), 413, "request_too_large"),
            )
            for body, status, code in cases:
                with self.subTest(code=code):
                    response = client.post(
                        "/api/projects",
                        content=body,
                        headers={"Content-Type": "application/json"},
                    )
                    self.assertEqual(response.status_code, status, response.text)
                    self.assertEqual(response.json()["issues"][0]["code"], code)

        self.data.create_project.assert_not_called()

    def test_default_factory_opens_and_closes_pool_with_application(self):
        pool = object()
        lifecycle = []

        @contextmanager
        def open_pool(settings):
            self.assertIs(settings, self.settings)
            lifecycle.append("open")
            try:
                yield pool
            finally:
                lifecycle.append("closed")

        with patch("src.main.open_postgres_pool", open_pool), patch(
            "src.main.DataManager", return_value=self.data
        ) as manager:
            app = create_app(settings=self.settings)
            self.assertEqual(lifecycle, [])
            with self.client_class(app) as client:
                manager.assert_called_once_with(pool, document_directory=self.settings.document_directory)
                self.assertEqual(lifecycle, ["open"])
                self.assertEqual(client.get("/ready").status_code, 200)

        self.assertEqual(lifecycle, ["open", "closed"])


if __name__ == "__main__":
    unittest.main()
