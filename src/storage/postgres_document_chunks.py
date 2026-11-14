"""Save validated extraction chunks for document retries."""

from __future__ import annotations

import json

from src.contracts.postgres_pool import PostgresPool
from src.errors import error_codes as errors
from src.errors.processing_error import ProcessingError
from src.models.processing.document_task import DocumentTask
from src.models.processing.lifecycle import RUNNING
from src.models.processing.processing_job import ProcessingJob


class PostgresDocumentChunks:
    """Persist immutable chunk results for the current document generation."""

    def __init__(self, pool: PostgresPool):
        self.pool = pool

    def save_document_chunk(
        self,
        job: ProcessingJob,
        task: DocumentTask,
        index: int,
        parse_id: str,
        records: list[dict],
        uncertainties: list[str],
    ) -> None:
        """Save a chunk once while the worker still owns the document task."""
        document = task.document
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

            owned_task = connection.execute(
                """
                SELECT 1 FROM stackplan.document_tasks
                WHERE document_id = %s AND job_id = %s AND generation = %s
                    AND owner_token = %s AND state = %s
                FOR UPDATE
                """,
                (document.id, job.id, task.generation, job.lease_token, RUNNING),
            ).fetchone()
            if owned_task is None:
                raise ProcessingError(
                    errors.PROCESSING_INTERRUPTED,
                    "This document attempt is no longer current.",
                    "document", document_id=document.id, module_id=document.module_id,
                )

            connection.execute(
                """
                INSERT INTO stackplan.document_chunks (
                    document_id, chunk_index, parse_id, records, uncertainties, generation
                )
                VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s)
                ON CONFLICT (document_id, chunk_index, generation) DO NOTHING
                """,
                (
                    document.id, index, parse_id,
                    json.dumps(records, allow_nan=False),
                    json.dumps(uncertainties, allow_nan=False),
                    task.generation,
                ),
            )
