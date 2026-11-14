"""Verify recovering jobs whose worker lease expired."""

from contextlib import nullcontext
import unittest
from unittest.mock import Mock

from src.errors import error_codes
from src.storage.postgres_job_recovery import RECOVERY_EXHAUSTED_MESSAGE, PostgresJobRecovery


class PostgresJobRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.connection = Mock()
        self.connection.transaction.return_value = nullcontext()
        pool = Mock()
        pool.connection.return_value = nullcontext(self.connection)
        self.pool = pool

    def recover(self, jobs, max_recoveries=3):
        self.connection.execute.return_value.fetchall.return_value = jobs
        return PostgresJobRecovery(self.pool, max_recoveries).cleanup_interrupted_jobs()

    def statements(self):
        return [call.args for call in self.connection.execute.call_args_list]

    def test_no_expired_jobs_changes_nothing(self):
        self.assertEqual(self.recover([]), 0)
        ((sql, params),) = self.statements()
        self.assertIn("lease_expires_at <= clock_timestamp()", sql)
        self.assertIn("FOR UPDATE SKIP LOCKED", sql)
        self.assertEqual(params, ("running",))

    def test_expired_job_is_requeued_with_its_running_documents(self):
        self.assertEqual(self.recover([{"id": "job", "project_id": "project", "recoveries": 1}]), 1)
        _, tasks, progress, job = self.statements()
        self.assertIn("SET state = 'queued', owner_token = NULL", tasks[0])
        self.assertIn("state = 'running'", tasks[0])
        self.assertIn("SET state = 'waiting'", progress[0])
        self.assertIn("state IN ('parsing', 'extracting')", progress[0])
        self.assertIn("recoveries = recoveries + 1", job[0])
        self.assertIn("lease_token = NULL", job[0])
        self.assertEqual(job[1], ("queued", "queued", "job"))
        self.connection.transaction.assert_called_once_with()

    def test_exhausted_job_settles_as_interrupted_with_an_issue(self):
        self.assertEqual(self.recover([{"id": "job", "project_id": "project", "recoveries": 3}]), 1)
        _, _, _, stop, issue, job, project = self.statements()
        self.assertIn("state IN ('queued', 'running')", stop[0])
        self.assertEqual(issue[1][4], error_codes.PROCESSING_INTERRUPTED)
        self.assertEqual(issue[1][6], RECOVERY_EXHAUSTED_MESSAGE)
        self.assertEqual(job[1], ("Interrupted", "interrupted", "job"))
        self.assertEqual(project[1], ("Interrupted", "project"))

    def test_each_expired_job_is_handled(self):
        jobs = [
            {"id": "a", "project_id": "pa", "recoveries": 0},
            {"id": "b", "project_id": "pb", "recoveries": 0},
        ]
        self.assertEqual(self.recover(jobs, max_recoveries=0), 2)
        settled = [s[1] for s in self.statements() if "UPDATE stackplan.projects" in s[0]]
        self.assertEqual(settled, [("Interrupted", "pa"), ("Interrupted", "pb")])

    def test_negative_recovery_limit_is_rejected(self):
        with self.assertRaises(ValueError):
            PostgresJobRecovery(self.pool, -1)


if __name__ == "__main__":
    unittest.main()
