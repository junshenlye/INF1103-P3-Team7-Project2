"""Persist retry diagnostics for the active document task."""

from __future__ import annotations

import json

from src.contracts.postgres_pool import PostgresPool
from src.errors import error_codes as errors
from src.errors.processing_error import ProcessingError
from src.models.processing.document_task import DocumentTask
from src.models.processing.lifecycle import RUNNING
from src.models.processing.processing_job import ProcessingJob


class PostgresExtractionAttempts:
    """Record failed parse or extraction attempts without changing task state."""

    def __init__(self, pool: PostgresPool):
        self.pool = pool

    def record_extraction_attempt(
        self,
        job: ProcessingJob,
        task: DocumentTask,
        stage: str,
        index: int | None,
        attempt: int,
        code: str,
        message: str,
        status: int | None = None,
        rejected: dict | None = None,
    ) -> None:
        """Record an attempt only while the job owns this task generation."""
        with self.pool.connection() as connection, connection.transaction():
            lease = connection.execute(
                """
                SELECT 1 FROM stackplan.processing_jobs
                WHERE id = %s AND status = %s AND lease_token = %s
                    AND lease_expires_at > clock_timestamp()
                FOR UPDATE
                """,
                (job.id, RUNNING, job.lease_token),
            ).fetchone()
            if lease is None:
                raise ProcessingError(
                    errors.PROCESSING_INTERRUPTED, errors.INTERRUPTION_MESSAGE,
                    "system", job_id=job.id,
                )

            saved = connection.execute(
                """
                WITH owned_task AS (
                    SELECT document_id, generation FROM stackplan.document_tasks
                    WHERE document_id = %s AND job_id = %s AND generation = %s
                        AND owner_token = %s AND state = %s
                    FOR UPDATE
                )
                INSERT INTO stackplan.extraction_attempts (
                    document_id, generation, stage, chunk_index, attempt, code,
                    message, provider_status, rejected
                )
                SELECT document_id, generation, %s, %s, %s, %s, %s, %s, %s::jsonb
                FROM owned_task
                RETURNING id
                """,
                (
                    task.document.id, job.id, task.generation, job.lease_token, RUNNING,
                    stage, index, attempt, code, message[:500], status,
                    json.dumps(rejected, allow_nan=False) if rejected is not None else None,
                ),
            ).fetchone()
            if saved is None:
                raise ProcessingError(
                    errors.PROCESSING_INTERRUPTED,
                    "This document attempt is no longer current.",
                    "document", document_id=task.document.id, module_id=task.document.module_id,
                )
