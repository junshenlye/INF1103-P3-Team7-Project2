"""Check persistence of diagnostics from document retries."""

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


class DocumentRetryDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.job = ProcessingJob("job", "project", "submission", "running", "extracting", "lease")
        document = DocumentReference("doc", "module", "brief.pdf", "application/pdf", 10, "a" * 64)
        self.task = DocumentTask(document, 2)
        self.connection = Mock()
        self.connection.transaction.return_value = nullcontext()
        pool = Mock()
        pool.connection.return_value = nullcontext(self.connection)
        self.data = DataManager(pool)

    def record(self, *, stage="extracting", index=0, status=None, rejected=None):
        self.data.record_extraction_attempt(
            self.job, self.task, stage, index, 1, error_codes.INVALID_EXTRACTION,
            "x" * 510, status, rejected,
        )

    def test_records_the_bounded_diagnostic_and_optional_provider_details(self):
        self.connection.execute.return_value.fetchone.return_value = {"id": "saved"}
        self.record(status=503, rejected={"name": "Quiz α"})

        sql, parameters = self.connection.execute.call_args.args
        self.assertIn("FROM owned_task", sql)
        self.assertEqual(parameters[:8], ("doc", "job", 2, "lease", "extracting", 0, 1,
                                          error_codes.INVALID_EXTRACTION))
        self.assertEqual(parameters[8:10], ("x" * 500, 503))
        self.assertEqual(json.loads(parameters[10]), {"name": "Quiz α"})
        self.connection.transaction.assert_called_once_with()

    def test_parse_failure_can_omit_chunk_and_provider_details(self):
        self.connection.execute.return_value.fetchone.return_value = {"id": "saved"}
        self.record(stage="parsing", index=None)

        parameters = self.connection.execute.call_args.args[1]
        self.assertEqual(parameters[4:6], ("parsing", None))
        self.assertEqual(parameters[9:], (None, None))

    def test_lost_job_lease_stops_before_attempt_insert(self):
        self.connection.execute.return_value.fetchone.return_value = None

        with self.assertRaises(ProcessingError) as error:
            self.record()

        self.assertEqual(error.exception.code, error_codes.PROCESSING_INTERRUPTED)
        self.connection.execute.assert_called_once()

    def test_stale_task_raises_processing_interrupted(self):
        self.connection.execute.side_effect = [
            Mock(fetchone=Mock(return_value={"id": "job"})),
            Mock(fetchone=Mock(return_value=None)),
        ]

        with self.assertRaises(ProcessingError) as error:
            self.record()

        self.assertEqual(error.exception.code, error_codes.PROCESSING_INTERRUPTED)
        self.assertEqual(error.exception.related_ids, {"document_id": "doc"})
