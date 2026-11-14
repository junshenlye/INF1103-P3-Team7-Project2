"""Verify document claim outcomes at the worker persistence boundary."""

from contextlib import nullcontext
import unittest
from unittest.mock import Mock

from src.errors import error_codes
from src.errors.processing_error import ProcessingError
from src.managers.data_manager import DataManager
from src.models.processing.processing_job import ProcessingJob


class DocumentTaskClaimTests(unittest.TestCase):
    def setUp(self):
        self.job = ProcessingJob("job", "project", "submission", "running", "parsing", "lease")
        self.connection = Mock()
        self.connection.transaction.return_value = nullcontext()
        pool = Mock()
        pool.connection.return_value = nullcontext(self.connection)
        self.data = DataManager(pool)

    def test_returns_the_claimed_generation_and_document(self):
        self.connection.execute.side_effect = [
            Mock(fetchone=Mock(return_value={"id": self.job.id})),
            Mock(fetchone=Mock(return_value={
                "id": "document", "module_id": "module", "filename": "brief.pdf",
                "media_type": "application/pdf", "size": 25, "checksum": "a" * 64,
                "generation": 3,
            })),
        ]

        task = self.data.claim_document_task(self.job)

        self.assertEqual(task.generation, 3)
        self.assertEqual(task.document.id, "document")
        self.assertEqual(task.document.filename, "brief.pdf")
        self.assertEqual(self.connection.execute.call_args.args[1], (self.job.id, self.job.lease_token))
        self.connection.transaction.assert_called_once_with()

    def test_returns_none_when_no_task_is_available(self):
        self.connection.execute.side_effect = [
            Mock(fetchone=Mock(return_value={"id": self.job.id})),
            Mock(fetchone=Mock(return_value=None)),
        ]

        self.assertIsNone(self.data.claim_document_task(self.job))

    def test_lost_lease_stops_before_claiming(self):
        self.connection.execute.return_value.fetchone.return_value = None

        with self.assertRaises(ProcessingError) as error:
            self.data.claim_document_task(self.job)

        self.assertEqual(error.exception.code, error_codes.PROCESSING_INTERRUPTED)
        self.assertEqual(self.connection.execute.call_count, 1)
