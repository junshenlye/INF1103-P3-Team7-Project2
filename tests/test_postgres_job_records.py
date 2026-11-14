"""Verify the SQL steps shared by job settlement adapters."""

import unittest
from unittest.mock import Mock
from uuid import UUID

from src.errors import error_codes
from src.errors.issues import make_issue
from src.errors.processing_error import ProcessingError
from src.models.processing.processing_job import ProcessingJob
from src.storage.postgres_job_records import (
    finish_job,
    insert_issue,
    require_live_lease,
    stop_unfinished_documents,
)

JOB = ProcessingJob("job", "project", "submission", "running", "parsing", "lease")


class JobRecordTests(unittest.TestCase):
    def setUp(self):
        self.connection = Mock()

    def statements(self):
        return [call.args for call in self.connection.execute.call_args_list]

    def test_live_lease_is_locked_and_checked(self):
        self.connection.execute.return_value.fetchone.return_value = {"id": "job"}
        require_live_lease(self.connection, JOB)
        ((sql, params),) = self.statements()
        self.assertIn("FOR UPDATE", sql)
        self.assertIn("lease_expires_at > clock_timestamp()", sql)
        self.assertEqual(params, ("job", "running", "lease"))

    def test_lost_lease_is_an_interruption(self):
        self.connection.execute.return_value.fetchone.return_value = None
        with self.assertRaises(ProcessingError) as raised:
            require_live_lease(self.connection, JOB)
        self.assertEqual(raised.exception.code, error_codes.PROCESSING_INTERRUPTED)
        self.assertEqual(raised.exception.related_ids, {"job_id": "job"})

    def test_issue_fields_and_defaults_are_stored(self):
        issue = make_issue(error_codes.NO_ASSESSMENTS, "Nothing found.", "document", module_id="m", document_id="d")
        insert_issue(self.connection, "job", issue)
        insert_issue(self.connection, "job", {"code": error_codes.NOT_FOUND, "message": "Missing.", "scope": "system"})
        (first_sql, first), (_, second) = self.statements()
        self.assertIn("INSERT INTO stackplan.processing_issues", first_sql)
        UUID(first[0])
        self.assertEqual(first[1:], ("job", "m", "d", error_codes.NO_ASSESSMENTS, "error", "Nothing found.", "document"))
        self.assertEqual(second[1:], ("job", None, None, error_codes.NOT_FOUND, "error", "Missing.", "system"))
        self.assertNotEqual(first[0], second[0])

    def test_unfinished_documents_are_stopped(self):
        stop_unfinished_documents(self.connection, "job")
        ((sql, params),) = self.statements()
        self.assertIn("state IN ('queued', 'running')", sql)
        self.assertEqual(params, ("job",))

    def test_finishing_sets_the_terminal_stage_and_project_status(self):
        for status, stage in (("Ready", "complete"), ("Partial", "complete"), ("Failed", "failed"), ("Interrupted", "interrupted")):
            with self.subTest(status=status):
                self.connection.reset_mock()
                finish_job(self.connection, "job", "project", status)
                (job_sql, job_params), (project_sql, project_params) = self.statements()
                self.assertIn("lease_token = NULL", job_sql)
                self.assertEqual(job_params, (status, stage, "job"))
                self.assertEqual(project_params, (status, "project"))

    def test_non_terminal_status_is_rejected_before_writing(self):
        with self.assertRaises(ValueError):
            finish_job(self.connection, "job", "project", "Processing")
        self.connection.execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
