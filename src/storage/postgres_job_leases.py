"""Claim and renew worker job leases in PostgreSQL."""

from __future__ import annotations

from uuid import uuid4

from src.config.limits import LEASE_SECONDS
from src.contracts.postgres_pool import PostgresPool
from src.errors import error_codes as errors
from src.errors.processing_error import ProcessingError
from src.models.processing import lifecycle
from src.models.processing.processing_job import ProcessingJob


class PostgresJobLeases:
    """Implement the worker's job claim and heartbeat operations."""

    def __init__(self, pool: PostgresPool, lease_seconds: int = LEASE_SECONDS):
        self.pool = pool
        self.lease_seconds = lease_seconds

    def claim_next_job(self) -> ProcessingJob | None:
        """Claim the oldest unlocked queued job and assign a fresh lease."""
        token = str(uuid4())
        with self.pool.connection() as connection, connection.transaction():
            row = connection.execute(
                """
                WITH next_job AS (
                    SELECT id FROM stackplan.processing_jobs
                    WHERE status = %s
                    ORDER BY created_at, id
                    LIMIT 1 FOR UPDATE SKIP LOCKED
                )
                UPDATE stackplan.processing_jobs AS job
                SET status = %s, stage = %s, lease_token = %s,
                    lease_expires_at = clock_timestamp() + %s * interval '1 second',
                    started_at = clock_timestamp()
                FROM next_job WHERE job.id = next_job.id
                RETURNING job.id::text AS id, job.project_id::text AS project_id,
                          job.submission_key, job.status, job.stage,
                          job.lease_token::text AS lease_token
                """,
                (lifecycle.QUEUED, lifecycle.RUNNING, lifecycle.PARSING, token, self.lease_seconds),
            ).fetchone()
        return ProcessingJob(**row) if row is not None else None

    def save_job_heartbeat(self, job: ProcessingJob, stage: str | None = None) -> None:
        """Extend an active lease and optionally update the processing stage."""
        with self.pool.connection() as connection, connection.transaction():
            row = connection.execute(
                """
                UPDATE stackplan.processing_jobs
                SET lease_expires_at = clock_timestamp() + %s * interval '1 second',
                    stage = COALESCE(%s, stage)
                WHERE id = %s AND status = %s AND lease_token = %s
                    AND lease_expires_at > clock_timestamp()
                RETURNING id
                """,
                (self.lease_seconds, stage, job.id, lifecycle.RUNNING, job.lease_token),
            ).fetchone()
            if row is None:
                raise ProcessingError(
                    errors.PROCESSING_INTERRUPTED,
                    errors.INTERRUPTION_MESSAGE,
                    "system",
                    job_id=job.id,
                )
