"""Check lease and generation guards on extraction attempt writes."""

from contextlib import nullcontext
import json
import unittest
from unittest.mock import Mock

from src.errors import error_codes as errors
from src.errors.processing_error import ProcessingError
from src.models.documents.document_reference import DocumentReference
from src.models.processing.document_task import DocumentTask
from src.models.processing.processing_job import ProcessingJob
from src.storage.postgres_extraction_attempts import PostgresExtractionAttempts

JOB = ProcessingJob("job", "project", "submission", "running", "extracting", "lease")
TASK = DocumentTask(
    DocumentReference("doc", "module", "outline.pdf", "application/pdf", 20, "a" * 64), 3
)


class PostgresExtractionAttemptsTests(unittest.TestCase):
    def setUp(self):
        self.connection = Mock()
        self.connection.transaction.return_value = nullcontext()
        pool = Mock()
        pool.connection.return_value = nullcontext(self.connection)
        self.attempts = PostgresExtractionAttempts(pool)

    def respond(self, *rows):
        self.connection.execute.side_effect = [
            Mock(fetchone=Mock(return_value=row)) for row in rows
        ]

    def test_records_diagnostics_for_owned_generation(self):
        self.respond({"active": 1}, {"id": 12})

        self.attempts.record_extraction_attempt(
            JOB, TASK, "extracting", 0, 2, errors.INVALID_EXTRACTION,
            "x" * 510, 422, {"assessments": []},
        )

        lease, insert = self.connection.execute.call_args_list
        self.assertIn("lease_expires_at > clock_timestamp()", lease.args[0])
        self.assertEqual(lease.args[1], ("job", "running", "lease"))
        self.assertIn("generation = %s", insert.args[0])
        self.assertIn("owner_token = %s", insert.args[0])
        self.assertIn("FOR UPDATE", insert.args[0])
        self.assertIn("INSERT INTO stackplan.extraction_attempts", insert.args[0])
        params = insert.args[1]
        self.assertEqual(params[:5], ("doc", "job", 3, "lease", "running"))
        self.assertEqual(params[5:11], ("extracting", 0, 2, errors.INVALID_EXTRACTION, "x" * 500, 422))
        self.assertEqual(json.loads(params[11]), {"assessments": []})
        self.connection.transaction.assert_called_once_with()

    def test_parse_attempt_allows_absent_chunk_status_and_payload(self):
        self.respond({"active": 1}, {"id": 13})
        self.attempts.record_extraction_attempt(
            JOB, TASK, "parsing", None, 1, errors.DOCUMENT_PARSE_FAILED, "Parse failed."
        )
        params = self.connection.execute.call_args.args[1]
        self.assertIsNone(params[6])
        self.assertEqual(params[-2:], (None, None))

    def test_lost_lease_stops_before_inserting(self):
        self.respond(None)
        with self.assertRaises(ProcessingError) as raised:
            self.attempts.record_extraction_attempt(
                JOB, TASK, "parsing", None, 1, errors.DOCUMENT_PARSE_FAILED, "Parse failed."
            )
        self.assertEqual(raised.exception.code, errors.PROCESSING_INTERRUPTED)
        self.connection.execute.assert_called_once()

    def test_stale_task_generation_reports_interruption(self):
        self.respond({"active": 1}, None)
        with self.assertRaises(ProcessingError) as raised:
            self.attempts.record_extraction_attempt(
                JOB, TASK, "parsing", None, 1, errors.DOCUMENT_PARSE_FAILED, "Parse failed."
            )
        self.assertEqual(raised.exception.code, errors.PROCESSING_INTERRUPTED)
        self.assertEqual(raised.exception.related_ids["document_id"], "doc")
