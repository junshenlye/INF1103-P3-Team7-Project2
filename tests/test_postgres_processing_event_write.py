"""Verify that processing events use the caller's PostgreSQL connection."""

import json
import unittest
from unittest.mock import Mock

from src.errors.error_codes import NOT_FOUND
from src.errors.processing_error import ProcessingError
from src.storage.postgres_processing_events import append_processing_event


class ProcessingEventWriteTests(unittest.TestCase):
    def test_append_allocates_sequence_and_writes_in_one_statement(self):
        connection = Mock()
        connection.execute.return_value.fetchone.return_value = {"sequence": 6}
        payload = {"documents": [{"filename": "outline.pdf", "ready": True}]}

        sequence = append_processing_event(connection, "project", "document.completed", payload)

        self.assertEqual(sequence, 6)
        connection.execute.assert_called_once()
        sql, (project_id, kind, encoded_payload) = connection.execute.call_args.args
        self.assertIn("SET event_sequence = event_sequence + 1", sql)
        self.assertIn("INSERT INTO stackplan.processing_events", sql)
        self.assertIn("FROM next_event", sql)
        self.assertEqual((project_id, kind), ("project", "document.completed"))
        self.assertEqual(json.loads(encoded_payload), payload)
        connection.commit.assert_not_called()

    def test_append_for_missing_project_raises_domain_error(self):
        connection = Mock()
        connection.execute.return_value.fetchone.return_value = None

        with self.assertRaises(ProcessingError) as raised:
            append_processing_event(connection, "missing", "document.completed", {})

        self.assertEqual(raised.exception.code, NOT_FOUND)

    def test_invalid_json_does_not_execute_sql(self):
        connection = Mock()

        with self.assertRaises(ValueError):
            append_processing_event(connection, "project", "document.completed", {"value": float("nan")})

        connection.execute.assert_not_called()
