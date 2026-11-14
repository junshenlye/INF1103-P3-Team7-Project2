"""Verify settling claimed document tasks in PostgreSQL."""

from contextlib import nullcontext
import json
import unittest
from unittest.mock import Mock

from src.errors import error_codes
from src.errors.issues import make_issue
from src.errors.processing_error import ProcessingError
from src.models.documents.document_reference import DocumentReference
from src.models.processing.document_task import DocumentOutcome, DocumentTask
from src.models.processing.processing_job import ProcessingJob
from src.storage.postgres_document_task_outcomes import PostgresDocumentTaskOutcomes

JOB = ProcessingJob("job", "project", "submission", "running", "extracting", "lease")
TASK = DocumentTask(DocumentReference("doc", "module", "a.pdf", "application/pdf", 10, "f" * 64), 2)
RECORD = {"key": "quiz", "name": "Quiz", "kind": "assessment", "week": 3, "weight_percent": 20}
ISSUE = make_issue(error_codes.INVALID_EXTRACTION, "Chunk 2 could not be validated.", "module", module_id="module", document_id="doc")


class PostgresDocumentTaskOutcomeTests(unittest.TestCase):
    def setUp(self):
        self.connection = Mock()
        self.connection.transaction.return_value = nullcontext()
        pool = Mock()
        pool.connection.return_value = nullcontext(self.connection)
        self.outcomes = PostgresDocumentTaskOutcomes(pool)

    def respond(self, lease=True, current=True):
        results = [{"id": "job"} if lease else None, {"document_id": "doc"} if current else None]
        self.connection.execute.side_effect = lambda sql, params=(): Mock(
            fetchone=Mock(return_value=results.pop(0) if results else None)
        )

    def statements(self):
        return [call.args for call in self.connection.execute.call_args_list]

    def test_document_with_records_succeeds_and_is_extracted(self):
        self.respond()
        outcome = DocumentOutcome("partially_understood", (RECORD,), ("Quiz: weight unknown.",), (ISSUE,))
        self.assertEqual(self.outcomes.finish_document_task(JOB, TASK, outcome), "succeeded")

        lease, current, update, progress, issue = self.statements()
        self.assertIn("lease_token = %s", lease[0])
        self.assertIn("owner_token = %s AND state = 'running'", current[0])
        self.assertEqual(current[1], ("doc", "job", 2, "lease"))
        state, inference, issues, uncertainties, document = update[1]
        self.assertEqual((state, inference, document), ("succeeded", "partially_understood", "doc"))
        self.assertEqual(json.loads(issues), [ISSUE])
        self.assertEqual(json.loads(uncertainties), ["Quiz: weight unknown."])
        self.assertIn("owner_token = NULL", update[0])
        self.assertEqual(progress[1], ("doc", "extracted"))
        self.assertEqual(issue[1][1:5], ("job", "module", "doc", error_codes.INVALID_EXTRACTION))
        self.connection.transaction.assert_called_once_with()

    def test_document_without_records_fails_for_retry(self):
        self.respond()
        outcome = DocumentOutcome("no_assessment_content")
        self.assertEqual(self.outcomes.finish_document_task(JOB, TASK, outcome), "failed")
        _, _, update, progress = self.statements()
        self.assertEqual(update[1][:2], ("failed", "no_assessment_content"))
        self.assertEqual((json.loads(update[1][2]), json.loads(update[1][3])), ([], []))
        self.assertEqual(progress[1], ("doc", "failed"))

    def test_lost_lease_interrupts_before_touching_the_task(self):
        self.respond(lease=False)
        with self.assertRaises(ProcessingError) as raised:
            self.outcomes.finish_document_task(JOB, TASK, DocumentOutcome("understood", (RECORD,)))
        self.assertEqual(raised.exception.code, error_codes.PROCESSING_INTERRUPTED)
        self.assertEqual(len(self.statements()), 1)

    def test_superseded_attempt_cannot_overwrite_the_task(self):
        self.respond(current=False)
        with self.assertRaises(ProcessingError) as raised:
            self.outcomes.finish_document_task(JOB, TASK, DocumentOutcome("understood", (RECORD,)))
        self.assertEqual(raised.exception.code, error_codes.PROCESSING_INTERRUPTED)
        self.assertEqual(raised.exception.related_ids, {"document_id": "doc"})
        self.assertEqual(len(self.statements()), 2)


if __name__ == "__main__":
    unittest.main()
