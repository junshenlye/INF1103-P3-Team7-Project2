"""Verify the SQL boundary for shared provider permits."""

from contextlib import nullcontext
import unittest
from unittest.mock import Mock

from src.errors import error_codes
from src.errors.processing_error import ProcessingError
from src.models.processing.processing_job import ProcessingJob
from src.storage.postgres_provider_permits import PostgresProviderPermits

JOB = ProcessingJob("job", "project", "submission", "running", "extracting", "lease")


class PostgresProviderPermitsTests(unittest.TestCase):
    def setUp(self):
        self.connection = Mock()
        self.connection.transaction.return_value = nullcontext()
        self.pool = Mock()
        self.pool.connection.return_value = nullcontext(self.connection)
        self.permits = PostgresProviderPermits(self.pool)

    def responses(self, *rows):
        self.connection.execute.side_effect = [Mock(fetchone=Mock(return_value=row)) for row in rows]

    def test_claims_a_slot_under_the_current_lease(self):
        self.responses({"active": 1}, {"slot": 2}, None)

        self.assertEqual(self.permits.acquire_provider_permit(JOB, "gpt", 2), 2)

        lease, lookup, claim = self.connection.execute.call_args_list
        self.assertIn("FOR UPDATE", lease.args[0])
        self.assertEqual(lease.args[1], ("job", "running", "lease"))
        self.assertIn("owner.lease_token = permit.owner_token", lookup.args[0])
        self.assertIn("owner.lease_expires_at > clock_timestamp()", lookup.args[0])
        self.assertIn("FOR UPDATE OF permit SKIP LOCKED", lookup.args[0])
        self.assertEqual(lookup.args[1], ("gpt", 2, "running"))
        self.assertEqual(claim.args[1], ("job", "lease", "gpt", 2))
        self.connection.transaction.assert_called_once_with()

    def test_busy_provider_does_not_write_a_claim(self):
        self.responses({"active": 1}, None)

        self.assertIsNone(self.permits.acquire_provider_permit(JOB, "docling", 1))

        self.assertEqual(self.connection.execute.call_count, 2)

    def test_expired_job_lease_interrupts_acquisition(self):
        self.responses(None)

        with self.assertRaises(ProcessingError) as raised:
            self.permits.acquire_provider_permit(JOB, "gpt", 2)

        self.assertEqual(raised.exception.code, error_codes.PROCESSING_INTERRUPTED)
        self.assertEqual(self.connection.execute.call_count, 1)

    def test_release_is_fenced_by_both_job_and_lease(self):
        self.permits.release_provider_permit(JOB, "gpt", 2)

        sql, params = self.connection.execute.call_args.args
        self.assertIn("job_id = %s AND owner_token = %s", sql)
        self.assertEqual(params, ("gpt", 2, "job", "lease"))
