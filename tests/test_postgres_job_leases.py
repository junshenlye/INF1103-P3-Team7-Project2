"""Verify the PostgreSQL job lease boundary."""

from contextlib import nullcontext
import unittest
from unittest.mock import Mock
from uuid import UUID

from src.errors import error_codes
from src.errors.processing_error import ProcessingError
from src.models.processing.processing_job import ProcessingJob
from src.storage.postgres_job_leases import PostgresJobLeases

JOB = ProcessingJob("job", "project", "submission", "running", "parsing", "lease")


class PostgresJobLeaseTests(unittest.TestCase):
    def setUp(self):
        self.connection = Mock()
        self.connection.transaction.return_value = nullcontext()
        pool = Mock()
        pool.connection.return_value = nullcontext(self.connection)
        self.leases = PostgresJobLeases(pool, lease_seconds=30)

    def test_claim_assigns_new_token_and_returns_running_job(self):
        def claim(sql, params):
            queued, running, stage, token, seconds = params
            self.assertIn("ORDER BY created_at, id", sql)
            self.assertIn("FOR UPDATE SKIP LOCKED", sql)
            self.assertEqual((queued, running, stage, seconds), ("queued", "running", "parsing", 30))
            self.assertEqual(str(UUID(token)), token)
            row = dict(
                id=JOB.id, project_id=JOB.project_id, submission_key=JOB.submission_key,
                status=running, stage=stage, lease_token=token,
            )
            return Mock(fetchone=Mock(return_value=row))

        self.connection.execute.side_effect = claim
        job = self.leases.claim_next_job()

        self.assertEqual(job.id, JOB.id)
        self.assertEqual(job.status, "running")
        self.assertEqual(job.lease_token, self.connection.execute.call_args.args[1][3])
        self.connection.transaction.assert_called_once_with()

    def test_empty_queue_returns_none(self):
        self.connection.execute.return_value.fetchone.return_value = None
        self.assertIsNone(self.leases.claim_next_job())

    def test_heartbeat_preserves_or_changes_stage_under_the_current_lease(self):
        self.connection.execute.return_value.fetchone.return_value = {"id": JOB.id}

        for stage in (None, "validating"):
            with self.subTest(stage=stage):
                self.leases.save_job_heartbeat(JOB, stage)
                sql, params = self.connection.execute.call_args.args
                self.assertIn("stage = COALESCE(%s, stage)", sql)
                self.assertIn("lease_token = %s", sql)
                self.assertIn("lease_expires_at > clock_timestamp()", sql)
                self.assertEqual(params, (30, stage, "job", "running", "lease"))

    def test_heartbeat_reports_lost_or_expired_lease(self):
        self.connection.execute.return_value.fetchone.return_value = None

        with self.assertRaises(ProcessingError) as raised:
            self.leases.save_job_heartbeat(JOB)

        self.assertEqual(raised.exception.code, error_codes.PROCESSING_INTERRUPTED)
        self.assertEqual(raised.exception.related_ids, {"job_id": JOB.id})
