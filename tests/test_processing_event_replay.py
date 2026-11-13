"""Verify the database boundary for replaying saved progress events."""

from contextlib import nullcontext
import unittest
from unittest.mock import Mock

from src.errors import error_codes
from src.errors.processing_error import ProcessingError
from src.managers import DataManager
from src.models.processing.processing_event import ProcessingEvent
from src.serialization.processing_event import encode_processing_event


class ProcessingEventReplayTests(unittest.TestCase):
    def setUp(self):
        self.connection = Mock()
        self.pool = Mock()
        self.pool.connection.return_value = nullcontext(self.connection)
        self.data = DataManager(self.pool)

    def test_replay_reads_one_ordered_project_page_after_cursor(self):
        self.connection.execute.return_value.fetchall.return_value = [
            {"sequence": 6, "kind": "document.completed", "payload": {"state": "succeeded"}},
            {"sequence": 8, "kind": "processing.settled", "payload": {}},
        ]

        events = self.data.get_processing_events("project-id", after=5)

        self.assertEqual(
            events,
            [
                ProcessingEvent(6, "document.completed", {"state": "succeeded"}),
                ProcessingEvent(8, "processing.settled"),
            ],
        )
        self.assertTrue(encode_processing_event(events[0]).startswith("id: 6\n"))
        sql, params = self.connection.execute.call_args.args
        self.assertIn("project_id = project.id AND sequence > %s", sql)
        self.assertIn("ORDER BY event.sequence", sql)
        self.assertIn("LIMIT 100", sql)
        self.assertEqual(params, (5, "project-id"))

    def test_existing_project_with_no_events_returns_empty_page(self):
        self.connection.execute.return_value.fetchall.return_value = [
            {"sequence": None, "kind": None, "payload": None}
        ]

        self.assertEqual(self.data.get_processing_events("project-id"), [])

    def test_missing_project_raises_domain_error(self):
        self.connection.execute.return_value.fetchall.return_value = []

        with self.assertRaises(ProcessingError) as raised:
            self.data.get_processing_events("missing-project")

        self.assertEqual(raised.exception.code, error_codes.NOT_FOUND)

    def test_invalid_cursor_is_rejected_before_checkout(self):
        with self.assertRaises(ProcessingError) as raised:
            self.data.get_processing_events("project-id", after=-1)

        self.assertEqual(raised.exception.code, error_codes.INVALID_REQUEST)
        self.pool.connection.assert_not_called()
