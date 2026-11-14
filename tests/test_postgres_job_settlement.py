"""Verify completing and failing claimed jobs in PostgreSQL."""

from contextlib import nullcontext
import unittest
from unittest.mock import Mock

from src.errors import error_codes
from src.errors.issues import make_issue
from src.errors.processing_error import ProcessingError
from src.models.processing.processing_job import ProcessingJob
from src.storage.postgres_job_settlement import PostgresJobSettlement

JOB = ProcessingJob("job", "project", "submission", "running", "validating", "lease")
UNDERSTOOD = {"state": "succeeded", "inference": "understood", "issues": []}
PARTIAL = {"state": "succeeded", "inference": "partially_understood", "issues": []}
FAILED = {"state": "failed", "inference": "unknown", "issues": []}


class PostgresJobSettlementTests(unittest.TestCase):
    def setUp(self):
        self.connection = Mock()
        self.connection.transaction.return_value = nullcontext()
        pool = Mock()
        pool.connection.return_value = nullcontext(self.connection)
        self.settlement = PostgresJobSettlement(pool)

    def respond(self, *results):
        queue = list(results)

        def execute(sql, params=()):
            result = queue.pop(0) if queue else None
            return Mock(
                fetchone=Mock(return_value=result),
                fetchall=Mock(return_value=result or []),
            )

        self.connection.execute.side_effect = execute

    def complete(self, modules, heads, tasks, has_errors=False):
        self.respond({"id": "job"}, {"count": modules}, heads, tasks, {"?column?": 1} if has_errors else None)
        return self.settlement.complete_job(JOB)

    def settled(self):
        job_update, project_update = (call.args for call in self.connection.execute.call_args_list[-2:])
        return job_update[1][:2], project_update[1]

    def test_complete_job_applies_the_settled_status_rules(self):
        fresh = {"stale": False}
        cases = (
            ("every module available and understood", (2, [fresh, fresh], [UNDERSTOOD, UNDERSTOOD], False), "Ready", "complete"),
            ("one module unavailable", (2, [fresh], [UNDERSTOOD, FAILED], False), "Partial", "complete"),
            ("document only partly understood", (1, [fresh], [PARTIAL], False), "Partial", "complete"),
            ("stale result", (1, [{"stale": True}], [UNDERSTOOD], False), "Partial", "complete"),
            ("unresolved error issue", (1, [fresh], [UNDERSTOOD], True), "Partial", "complete"),
            ("nothing published", (1, [], [FAILED], False), "Failed", "failed"),
        )
        for name, args, status, stage in cases:
            with self.subTest(name):
                self.connection.reset_mock()
                self.assertEqual(self.complete(*args), status)
                self.assertEqual(self.settled(), ((status, stage), (status, "project")))

    def test_complete_job_ignores_replaced_documents_and_resolved_issues(self):
        self.complete(1, [{"stale": False}], [UNDERSTOOD])
        sql = [call.args[0] for call in self.connection.execute.call_args_list]
        self.assertIn("document_replacements", sql[3])
        self.assertIn("NOT resolved AND severity = 'error'", sql[4])

    def test_complete_job_requires_the_live_lease(self):
        self.respond(None)
        with self.assertRaises(ProcessingError) as raised:
            self.settlement.complete_job(JOB)
        self.assertEqual(raised.exception.code, error_codes.PROCESSING_INTERRUPTED)
        self.assertEqual(self.connection.execute.call_count, 1)

    def test_fail_job_stores_issues_stops_documents_and_settles(self):
        issues = [
            make_issue(error_codes.PROVIDER_UNAVAILABLE, "Service unavailable.", "system"),
            make_issue(error_codes.SOURCE_MISSING, "Original missing.", "document", module_id="m", document_id="d"),
        ]
        for interrupted, status, stage in ((False, "Failed", "failed"), (True, "Interrupted", "interrupted")):
            with self.subTest(interrupted=interrupted):
                self.connection.reset_mock()
                self.respond({"id": "job"})
                self.assertTrue(self.settlement.fail_job(JOB, issues, interrupted=interrupted))
                statements = [call.args for call in self.connection.execute.call_args_list]
                self.assertIn("FOR UPDATE", statements[0][0])
                self.assertNotIn("lease_expires_at", statements[0][0])
                self.assertEqual([s[1][4] for s in statements[1:3]], [error_codes.PROVIDER_UNAVAILABLE, error_codes.SOURCE_MISSING])
                self.assertIn("state IN ('queued', 'running')", statements[3][0])
                self.assertEqual(self.settled(), ((status, stage), (status, "project")))

    def test_fail_job_leaves_a_job_it_no_longer_owns(self):
        self.respond(None)
        self.assertFalse(self.settlement.fail_job(JOB, [make_issue(error_codes.PROVIDER_UNAVAILABLE, "x", "system")]))
        self.assertEqual(self.connection.execute.call_count, 1)


if __name__ == "__main__":
    unittest.main()
