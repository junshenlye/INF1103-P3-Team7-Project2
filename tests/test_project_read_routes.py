"""Verify synchronous project reads do not block the HTTP event loop."""

import asyncio
from importlib.util import find_spec
import unittest
from unittest.mock import Mock

from src.managers.io_manager import IOManager
from src.models.projects.project import Project


def require_worker_thread(value):
    """Fail if a database callback is invoked on an active asyncio loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return value
    raise AssertionError("synchronous project read ran on the event loop")


@unittest.skipUnless(
    find_spec("fastapi") and find_spec("httpx"),
    "HTTP dependencies unavailable",
)
class ProjectReadRouteTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient

        self.data = Mock()
        self.client = TestClient(
            IOManager(self.data, Mock()).get_application(),
            raise_server_exceptions=False,
        )

    def tearDown(self):
        self.client.close()

    def test_project_list_read_runs_off_the_event_loop(self):
        projects = [
            {"id": "project-1", "name": "Trimester 1", "week_count": 14},
            {"id": "project-2", "name": "Trimester 2", "week_count": 13},
        ]
        self.data.get_projects.side_effect = lambda: require_worker_thread(projects)

        response = self.client.get("/api/projects")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), projects)
        self.data.get_projects.assert_called_once_with()

    def test_single_project_read_runs_off_the_event_loop(self):
        project = Project(
            id="project-1",
            name="Trimester 1",
            week_count=14,
            status="Ready",
            job_id="job-1",
        )
        self.data.get_project.side_effect = (
            lambda project_id: require_worker_thread(project)
        )

        response = self.client.get("/api/projects/project-1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "id": "project-1",
                "name": "Trimester 1",
                "week_count": 14,
                "status": "Ready",
                "job_id": "job-1",
            },
        )
        self.data.get_project.assert_called_once_with("project-1")


if __name__ == "__main__":
    unittest.main()
