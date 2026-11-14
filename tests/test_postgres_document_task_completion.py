"""Verify the PostgreSQL boundary for completing a document task."""

from contextlib import nullcontext
import json
import unittest
from unittest.mock import MagicMock, Mock

from src.errors import error_codes
from src.errors.issues import make_issue
from src.errors.processing_error import ProcessingError
from src.models.documents.document_reference import DocumentReference
from src.models.processing.document_task import DocumentOutcome, DocumentTask
from src.models.processing.processing_job import ProcessingJob
from src.storage.postgres_document_task_completion import PostgresDocumentTaskCompletion


JOB = ProcessingJob("job", "project", "submission", "running", "extracting", "lease")
TASK = DocumentTask(
    DocumentReference("document", "module", "outline.pdf", "application/pdf", 123, "checksum"),
    2,
)


class PostgresDocumentTaskCompletionTests(unittest.TestCase):
    def setUp(self):
        self.connection = Mock()
        self.transaction = MagicMock()
        self.connection.transaction.return_value = self.transaction
        self.pool = Mock()
        self.pool.connection.return_value = nullcontext(self.connection)
        self.completion = PostgresDocumentTaskCompletion(self.pool)

    def respond(self, *rows):
        self.connection.execute.side_effect = [
            Mock(fetchone=Mock(return_value=row)) for row in rows
        ]

    def test_records_outcome_and_releases_task_ownership(self):
        outcome = DocumentOutcome("partially_understood", ({"name": "Quiz"},), ("Week unclear",))
        self.respond({"active": 1}, {"document_id": "document"}, None)

        self.completion.finish_document_task(JOB, TASK, outcome)

        lease, task, progress = self.connection.execute.call_args_list
        self.assertIn("lease_expires_at > clock_timestamp()", lease.args[0])
        self.assertIn("FOR UPDATE", lease.args[0])
        self.assertEqual(lease.args[1], ("job", "running", "lease"))
        self.assertIn("owner_token = NULL", task.args[0])
        self.assertEqual(task.args[1][:2], ("succeeded", "partially_understood"))
        self.assertEqual(json.loads(task.args[1][3]), ["Week unclear"])
        self.assertEqual(task.args[1][4:], ("document", "job", 2, "lease", "running"))
        self.assertEqual(progress.args[1], ("document", "extracted"))
        self.transaction.__exit__.assert_called_once_with(None, None, None)

    def test_saves_failure_and_its_issue(self):
        issue = make_issue(
            error_codes.NO_ASSESSMENTS, "No assessments found.", "document",
            module_id="module", document_id="document",
        )
        outcome = DocumentOutcome("no_assessment_content", issues=(issue,))
        self.respond({"active": 1}, {"document_id": "document"}, None, None)

        self.completion.finish_document_task(JOB, TASK, outcome)

        _, task, progress, issue_write = self.connection.execute.call_args_list
        self.assertEqual(task.args[1][:2], ("failed", "no_assessment_content"))
        self.assertEqual(json.loads(task.args[1][2]), [issue])
        self.assertEqual(progress.args[1], ("document", "failed"))
        self.assertEqual(
            issue_write.args[1][1:],
            ("job", "module", "document", issue["code"], "error", issue["message"], "document"),
        )

    def test_lost_lease_or_stale_generation_prevents_completion(self):
        for rows in ((None,), ({"active": 1}, None)):
            with self.subTest(rows=rows):
                self.connection.execute.reset_mock()
                self.respond(*rows)

                with self.assertRaises(ProcessingError) as raised:
                    self.completion.finish_document_task(JOB, TASK, DocumentOutcome("unknown"))

                self.assertEqual(raised.exception.code, error_codes.PROCESSING_INTERRUPTED)
                self.assertEqual(self.connection.execute.call_count, len(rows))

    def test_issue_write_failure_aborts_completion_transaction(self):
        outcome = DocumentOutcome("unknown", issues=({
            "code": "parse_failed", "message": "Parsing failed.", "scope": "document",
        },))
        failure = RuntimeError("Issue insert failed")
        self.connection.execute.side_effect = [
            Mock(fetchone=Mock(return_value={"active": 1})),
            Mock(fetchone=Mock(return_value={"document_id": "document"})),
            None,
            failure,
        ]

        with self.assertRaisesRegex(RuntimeError, "Issue insert failed"):
            self.completion.finish_document_task(JOB, TASK, outcome)

        self.assertIs(self.transaction.__exit__.call_args.args[1], failure)
