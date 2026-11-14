"""Verify the HTTP event stream resumes from the correct project cursor."""

import unittest
from unittest.mock import AsyncMock, Mock, patch

from src.errors.error_codes import INVALID_REQUEST
from src.errors.processing_error import ProcessingError
from src.managers.io_manager import IOManager
from src.models.processing.processing_event import ProcessingEvent


class RequestDouble:
    def __init__(self, headers=None, disconnected=(False, False, True)):
        self.headers = headers or {}
        self._disconnected = iter(disconnected)

    async def is_disconnected(self):
        return next(self._disconnected, True)


class ProjectEventEndpointTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.data = Mock()
        self.manager = IOManager(self.data, Mock())
        self.data.get_project.return_value = object()

    async def test_stream_replays_events_after_last_event_id_and_sends_keepalive(self):
        event = ProcessingEvent(6, "document.completed", {"state": "succeeded"})
        self.data.get_processing_events.side_effect = [[event], []]
        request = RequestDouble({"last-event-id": "5"})

        with patch("src.managers.io_manager.asyncio.sleep", new_callable=AsyncMock):
            response = await self.manager.get_project_events("project-id", request, after=2)
            frames = [frame async for frame in response.body_iterator]

        self.assertEqual(response.media_type, "text/event-stream")
        self.assertEqual(response.headers["cache-control"], "no-cache")
        self.assertIn("id: 6\nevent: progress\ndata:", frames[0])
        self.assertIn('"kind":"document.completed"', frames[0])
        self.assertEqual(frames[1], ": keep-alive\n\n")
        self.assertEqual(
            [call.args for call in self.data.get_processing_events.call_args_list],
            [("project-id", 5), ("project-id", 6)],
        )

    async def test_query_cursor_is_used_when_last_event_id_is_absent(self):
        self.data.get_processing_events.return_value = []
        request = RequestDouble(disconnected=(True,))

        response = await self.manager.get_project_events("project-id", request, after=12)
        self.assertEqual(response.media_type, "text/event-stream")
        self.data.get_project.assert_called_once_with("project-id")

    async def test_invalid_last_event_id_is_rejected_before_database_access(self):
        request = RequestDouble({"last-event-id": "-1"})
        with self.assertRaises(ProcessingError) as raised:
            await self.manager.get_project_events("project-id", request, after=0)
        self.assertEqual(raised.exception.code, INVALID_REQUEST)
        self.data.get_project.assert_not_called()

    def test_event_stream_route_is_registered(self):
        app = self.manager.get_application()
        routes = [route for route in app.routes if getattr(route, "path", None) == "/api/projects/{project_id}/events"]
        self.assertEqual(len(routes), 1)
        self.assertIn("GET", routes[0].methods)

    def test_manager_package_exports_io_manager_used_by_application_factory(self):
        from src.managers import IOManager as ExportedIOManager
        self.assertIs(ExportedIOManager, IOManager)


if __name__ == "__main__":
    unittest.main()
