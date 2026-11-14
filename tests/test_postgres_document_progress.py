"""Verify the PostgreSQL document progress boundary."""

from contextlib import nullcontext
import unittest
from unittest.mock import Mock

from src.errors import error_codes
from src.errors.processing_error import ProcessingError
from src.models.processing.processing_job import ProcessingJob
from src.storage.postgres_document_progress import PostgresDocumentProgress

JOB = ProcessingJob("job", "project", "submission", "running", "parsing", "lease")


class PostgresDocumentProgressTests(unittest.TestCase):
    def setUp(self):
        self.connection = Mock()
        self.connection.transaction.return_value = nullcontext()
        pool = Mock()
        pool.connection.return_value = nullcontext(self.connection)
        self.progress = PostgresDocumentProgress(pool, lease_seconds=30)
        self.results = []

        def execute(sql, params):
            return Mock(fetchone=Mock(return_value=self.results.pop(0)))

        self.connection.execute.side_effect = execute

    def save(self, state, lease=True, saved=True):
        self.results = [{"id": "job"} if lease else None, {"document_id": "doc"} if saved else None]
        self.progress.save_document_progress(JOB, "doc", state)

    def test_renews_the_lease_and_records_the_stage(self):
        self.save("extracting")

        (lease_sql, lease_params), (progress_sql, progress_params) = (
            call.args for call in self.connection.execute.call_args_list
        )
        self.assertIn("lease_token = %s", lease_sql)
        self.assertIn("lease_expires_at > clock_timestamp()", lease_sql)
        self.assertEqual(lease_params, (30, "extracting", "job", "running", "lease"))
        self.assertIn("module.job_id = %s", progress_sql)
        self.assertIn("ON CONFLICT (document_id) DO UPDATE", progress_sql)
        self.assertEqual(progress_params, ("extracting", "doc", "job", ["parsing", "extracting"]))
        self.connection.transaction.assert_called_once_with()

    def test_allowed_previous_states_move_forward_or_resume(self):
        expected = {
            "parsing": ["waiting", "unknown", "failed", "parsing", "extracting"],
            "extracting": ["parsing", "extracting"],
            "extracted": ["extracting", "extracted"],
        }
        for state, previous in expected.items():
            with self.subTest(state=state):
                self.connection.execute.reset_mock()
                self.save(state)
                self.assertEqual(self.connection.execute.call_args_list[1].args[1][3], previous)

    def test_extracted_keeps_the_job_stage(self):
        self.save("extracted")
        self.assertIsNone(self.connection.execute.call_args_list[0].args[1][1])

    def test_lost_lease_interrupts_without_touching_progress(self):
        with self.assertRaises(ProcessingError) as raised:
            self.save("parsing", lease=False)
        self.assertEqual(raised.exception.code, error_codes.PROCESSING_INTERRUPTED)
        self.assertEqual(raised.exception.related_ids, {"job_id": "job"})
        self.assertEqual(self.connection.execute.call_count, 1)

    def test_rejected_move_or_foreign_document_is_reported(self):
        with self.assertRaises(ProcessingError) as raised:
            self.save("extracting", saved=False)
        self.assertEqual(raised.exception.code, error_codes.INVALID_REQUEST)
        self.assertEqual(raised.exception.related_ids, {"document_id": "doc"})

    def test_unsupported_states_are_rejected_before_connecting(self):
        for state in ("waiting", "failed", "complete", ""):
            with self.subTest(state=state):
                with self.assertRaises(ValueError):
                    self.progress.save_document_progress(JOB, "doc", state)
        self.connection.execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
