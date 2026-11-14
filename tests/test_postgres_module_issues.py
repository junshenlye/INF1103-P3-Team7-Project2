"""Verify recording module-wide issues in PostgreSQL."""

from contextlib import nullcontext
import json
import unittest
from unittest.mock import Mock

from src.errors import error_codes
from src.errors.issues import make_issue
from src.errors.processing_error import ProcessingError
from src.models.processing.processing_job import ProcessingJob
from src.storage.postgres_module_issues import PostgresModuleIssues

JOB = ProcessingJob("job", "project", "submission", "running", "validating", "lease")
ISSUE = make_issue(error_codes.INVALID_EXTRACTION, "Weights exceed 100 percent.", "module", module_id="module")


class PostgresModuleIssueTests(unittest.TestCase):
    def setUp(self):
        self.connection = Mock()
        self.connection.transaction.return_value = nullcontext()
        pool = Mock()
        pool.connection.return_value = nullcontext(self.connection)
        self.issues = PostgresModuleIssues(pool)

    def statements(self):
        return [call.args for call in self.connection.execute.call_args_list]

    def test_stores_the_issue_marks_the_result_stale_and_flags_documents(self):
        self.connection.execute.return_value.fetchone.return_value = {"id": "job"}
        self.issues.save_module_issue(JOB, ISSUE)

        lease, insert, stale, tasks = self.statements()
        self.assertIn("lease_token = %s", lease[0])
        self.assertEqual(insert[1][1:4], ("job", "module", None))
        self.assertEqual(insert[1][4], error_codes.INVALID_EXTRACTION)
        self.assertIn("module_result_heads SET stale = true", stale[0])
        self.assertEqual(stale[1], ("module",))
        sql, (issues, module, job) = tasks
        self.assertIn("item->>'document_id' IS NOT NULL", sql)
        self.assertIn("task.state = 'succeeded'", sql)
        self.assertIn("document_replacements", sql)
        self.assertIn("inference = 'partially_understood'", sql)
        self.assertEqual(json.loads(issues), [ISSUE])
        self.assertEqual((module, job), ("module", "job"))
        self.connection.transaction.assert_called_once_with()

    def test_lost_lease_writes_nothing(self):
        self.connection.execute.return_value.fetchone.return_value = None
        with self.assertRaises(ProcessingError) as raised:
            self.issues.save_module_issue(JOB, ISSUE)
        self.assertEqual(raised.exception.code, error_codes.PROCESSING_INTERRUPTED)
        self.assertEqual(len(self.statements()), 1)

    def test_issue_without_a_module_is_rejected_before_connecting(self):
        for issue in ({**ISSUE, "module_id": None}, {k: v for k, v in ISSUE.items() if k != "module_id"}):
            with self.subTest(issue=issue):
                with self.assertRaises(ValueError):
                    self.issues.save_module_issue(JOB, issue)
        self.connection.execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
