"""Exercise the SQL boundary for saving validated extraction chunks."""

from contextlib import nullcontext
import json
import unittest
from unittest.mock import Mock

from src.errors import error_codes
from src.errors.processing_error import ProcessingError
from src.models.documents.document_reference import DocumentReference
from src.models.processing.document_task import DocumentTask
from src.models.processing.processing_job import ProcessingJob
from src.storage.postgres_document_chunks import PostgresDocumentChunks


JOB = ProcessingJob("job", "project", "submission", "running", "extracting", "lease")
DOCUMENT = DocumentReference("document", "module", "outline.pdf", "application/pdf", 123, "checksum")
TASK = DocumentTask(DOCUMENT, 2)


class PostgresDocumentChunksTests(unittest.TestCase):
    def setUp(self):
        self.connection = Mock()
        self.connection.transaction.return_value = nullcontext()
        pool = Mock()
        pool.connection.return_value = nullcontext(self.connection)
        self.chunks = PostgresDocumentChunks(pool)

    def respond(self, *rows):
        self.connection.execute.side_effect = [
            Mock(fetchone=Mock(return_value=row)) for row in rows
        ]

    def test_saves_chunk_under_current_lease_with_idempotent_insert(self):
        records = [{"name": "Quiz"}]
        uncertainties = ["Week is unclear"]
        self.respond({"active": 1}, {"owned": 1}, None)

        self.chunks.save_document_chunk(JOB, TASK, 0, "parse", records, uncertainties)

        lease, task, write = self.connection.execute.call_args_list
        self.assertIn("lease_expires_at > clock_timestamp()", lease.args[0])
        self.assertIn("FOR UPDATE", lease.args[0])
        self.assertEqual(lease.args[1], ("job", "running", "lease"))
        self.assertIn("FOR UPDATE", task.args[0])
        self.assertEqual(task.args[1], ("document", "job", 2, "lease", "running"))
        self.assertIn(
            "ON CONFLICT (document_id, chunk_index, generation) DO NOTHING",
            write.args[0],
        )
        document_id, index, parse_id, saved_records, saved_notes, generation = write.args[1]
        self.assertEqual((document_id, index, parse_id, generation), ("document", 0, "parse", 2))
        self.assertEqual(json.loads(saved_records), records)
        self.assertEqual(json.loads(saved_notes), uncertainties)
        self.connection.transaction.assert_called_once_with()

    def test_lost_job_lease_prevents_insert(self):
        self.respond(None)

        with self.assertRaises(ProcessingError) as raised:
            self.chunks.save_document_chunk(JOB, TASK, 0, "parse", [], [])

        self.assertEqual(raised.exception.code, error_codes.PROCESSING_INTERRUPTED)
        self.assertEqual(self.connection.execute.call_count, 1)

    def test_stale_document_generation_prevents_insert(self):
        self.respond({"active": 1}, None)

        with self.assertRaises(ProcessingError) as raised:
            self.chunks.save_document_chunk(JOB, TASK, 0, "parse", [], [])

        self.assertEqual(raised.exception.code, error_codes.PROCESSING_INTERRUPTED)
        self.assertEqual(raised.exception.related_ids["document_id"], "document")
        self.assertEqual(self.connection.execute.call_count, 2)
