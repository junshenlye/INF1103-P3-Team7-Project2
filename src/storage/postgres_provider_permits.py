"""Store shared provider permits against the processing job's current lease."""

from __future__ import annotations

from src.contracts.postgres_pool import PostgresPool
from src.errors import error_codes as errors
from src.errors.processing_error import ProcessingError
from src.models.processing.lifecycle import RUNNING
from src.models.processing.processing_job import ProcessingJob


class PostgresProviderPermits:
    """Implement the permit operations used by the worker data contract."""

    def __init__(self, pool: PostgresPool):
        self.pool = pool

    def acquire_provider_permit(self, job: ProcessingJob, provider: str, capacity: int) -> int | None:
        """Claim the lowest available slot within capacity, or return None."""
        with self.pool.connection() as connection, connection.transaction():
            active_lease = connection.execute(
                """
                SELECT 1 FROM stackplan.processing_jobs
                WHERE id = %s AND status = %s AND lease_token = %s
                    AND lease_expires_at > clock_timestamp()
                FOR UPDATE
                """,
                (job.id, RUNNING, job.lease_token),
            ).fetchone()
            if active_lease is None:
                raise ProcessingError(
                    errors.PROCESSING_INTERRUPTED,
                    errors.INTERRUPTION_MESSAGE,
                    "system",
                    job_id=job.id,
                )
            slot = connection.execute(
                """
                SELECT permit.slot FROM stackplan.provider_permits AS permit
                WHERE permit.provider = %s AND permit.slot <= %s
                    AND NOT EXISTS (
                        SELECT 1 FROM stackplan.processing_jobs AS owner
                        WHERE owner.id = permit.job_id AND owner.status = %s
                            AND owner.lease_token = permit.owner_token
                            AND owner.lease_expires_at > clock_timestamp()
                    )
                ORDER BY permit.slot
                LIMIT 1 FOR UPDATE OF permit SKIP LOCKED
                """,
                (provider, capacity, RUNNING),
            ).fetchone()
            if slot is None:
                return None

            connection.execute(
                """
                UPDATE stackplan.provider_permits SET job_id = %s, owner_token = %s
                WHERE provider = %s AND slot = %s
                """,
                (job.id, job.lease_token, provider, slot["slot"]),
            )
            return slot["slot"]

    def release_provider_permit(self, job: ProcessingJob, provider: str, slot: int) -> None:
        """Release the slot only if this job and lease still own it."""
        with self.pool.connection() as connection:
            connection.execute(
                """
                UPDATE stackplan.provider_permits SET job_id = NULL, owner_token = NULL
                WHERE provider = %s AND slot = %s AND job_id = %s AND owner_token = %s
                """,
                (provider, slot, job.id, job.lease_token),
            )
