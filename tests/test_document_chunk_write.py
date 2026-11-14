"""Verify that only the current document attempt can save extraction chunks."""

from contextlib import nullcontext
import json
import unittest
from unittest.mock import Mock

from src.errors import error_codes
from src.errors.processing_error import ProcessingError
from src.managers.data_manager import DataManager
from src.models.documents.document_reference import DocumentReference
from src.models.processing.document_task import DocumentTask
from src.models.processing.processing_job import ProcessingJob


class DocumentChunkWriteTests(unittest.TestCase):
    def setUp(self):
        self.job = ProcessingJob("job", "project", "submission", "running", "extracting", "lease")
        document = DocumentReference("doc", "module", "brief.pdf", "application/pdf", 10, "a" * 64)
        self.task = DocumentTask(document, 3)
        self.connection = Mock()
        self.connection.transaction.return_value = nullcontext()
        pool = Mock()
        pool.connection.return_value = nullcontext(self.connection)
        self.data = DataManager(pool)

    def test_persists_chunk_for_current_generation(self):
        self.connection.execute.return_value.fetchone.return_value = {"id": "job"}
        records = [{"name": "Quiz α"}]
        uncertainties = ["Weight unknown"]
        self.data.save_document_chunk(self.job, self.task, 0, "parse", records, uncertainties)

        _, task_lock, write = self.connection.execute.call_args_list
        self.assertEqual(task_lock.args[1], ("doc", "job", 3, "lease"))
        sql, params = write.args
        self.assertIn("ON CONFLICT (document_id, chunk_index, generation) DO NOTHING", sql)
        self.assertEqual(params[:3], ("doc", 0, "parse"))
        self.assertEqual([json.loads(value) for value in params[3:5]], [records, uncertainties])
        self.assertEqual(params[5], 3)
        self.connection.transaction.assert_called_once_with()

    def test_stale_attempt_cannot_write(self):
        self.connection.execute.side_effect = [
            Mock(fetchone=Mock(return_value={"id": "job"})),
            Mock(fetchone=Mock(return_value=None)),
        ]
        with self.assertRaises(ProcessingError) as error:
            self.data.save_document_chunk(self.job, self.task, 0, "parse", [], [])
        self.assertEqual(error.exception.code, error_codes.PROCESSING_INTERRUPTED)
        self.assertEqual(self.connection.execute.call_count, 2)
