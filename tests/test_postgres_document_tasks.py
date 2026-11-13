"""Verify the SQL boundary for claiming queued documents."""

from contextlib import nullcontext
import unittest
from unittest.mock import Mock

from src.errors.error_codes import PROCESSING_INTERRUPTED
from src.errors.processing_error import ProcessingError
from src.models.documents.document_reference import DocumentReference
from src.models.processing.document_task import DocumentTask
from src.models.processing.processing_job import ProcessingJob
from src.storage.postgres_document_tasks import PostgresDocumentTasks


JOB = ProcessingJob("job", "project", "submission", "running", "parsing", "lease")


class PostgresDocumentTasksTests(unittest.TestCase):
    def setUp(self):
        self.connection = Mock()
        self.connection.transaction.return_value = nullcontext()
        pool = Mock()
        pool.connection.return_value = nullcontext(self.connection)
        self.tasks = PostgresDocumentTasks(pool)

    def respond(self, *rows):
        self.connection.execute.side_effect = [
            Mock(fetchone=Mock(return_value=row)) for row in rows
        ]

    def test_claim_checks_lease_and_returns_document_and_generation(self):
        metadata = dict(
            id="doc", module_id="module", filename="outline.pdf",
            media_type="application/pdf", size=42, checksum="a" * 64,
        )
        self.respond({"active": 1}, {**metadata, "generation": 3})

        self.assertEqual(
            self.tasks.claim_document_task(JOB),
            DocumentTask(DocumentReference(**metadata), 3),
        )
        self.connection.transaction.assert_called_once_with()
        lease, claim = self.connection.execute.call_args_list
        self.assertIn("lease_expires_at > clock_timestamp()", lease.args[0])
        self.assertIn("FOR UPDATE", lease.args[0])
        self.assertEqual(lease.args[1], ("job", "running", "lease"))
        self.assertIn("replacement.old_document_id = task.document_id", claim.args[0])
        self.assertIn("FOR UPDATE OF task SKIP LOCKED", claim.args[0])
        self.assertEqual(claim.args[1], ("job", "lease"))

    def test_no_available_task_returns_none(self):
        self.respond({"active": 1}, None)
        self.assertIsNone(self.tasks.claim_document_task(JOB))

    def test_lost_lease_prevents_claim(self):
        self.respond(None)
        with self.assertRaises(ProcessingError) as raised:
            self.tasks.claim_document_task(JOB)
        self.assertEqual(raised.exception.code, PROCESSING_INTERRUPTED)
        self.connection.execute.assert_called_once()
