"""Claim queued document tasks for an active processing job."""

from __future__ import annotations

from src.contracts.postgres_pool import PostgresPool
from src.errors.error_codes import INTERRUPTION_MESSAGE, PROCESSING_INTERRUPTED
from src.errors.processing_error import ProcessingError
from src.models.documents.document_reference import DocumentReference
from src.models.processing.document_task import DocumentTask
from src.models.processing.lifecycle import RUNNING
from src.models.processing.processing_job import ProcessingJob


class PostgresDocumentTasks:
    """Persist worker claims for documents queued under a job."""

    def __init__(self, pool: PostgresPool):
        self.pool = pool

    def claim_document_task(self, job: ProcessingJob) -> DocumentTask | None:
        """Claim one queued, unreplaced document and return its current generation."""
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
                    PROCESSING_INTERRUPTED, INTERRUPTION_MESSAGE, "system", job_id=job.id
                )

            row = connection.execute(
                """
                WITH next_task AS (
                    SELECT task.document_id FROM stackplan.document_tasks AS task
                    WHERE task.job_id = %s AND task.state = 'queued'
                        AND NOT EXISTS (
                            SELECT 1 FROM stackplan.document_replacements AS replacement
                            WHERE replacement.old_document_id = task.document_id
                        )
                    ORDER BY task.document_id
                    LIMIT 1 FOR UPDATE OF task SKIP LOCKED
                ), claimed AS (
                    UPDATE stackplan.document_tasks AS task
                    SET state = 'running', owner_token = %s, updated_at = clock_timestamp()
                    FROM next_task WHERE task.document_id = next_task.document_id
                    RETURNING task.document_id, task.generation
                )
                SELECT doc.id::text AS id, doc.module_id::text AS module_id,
                       doc.filename, doc.media_type, doc.size, doc.checksum, claimed.generation
                FROM claimed JOIN stackplan.documents AS doc ON doc.id = claimed.document_id
                """,
                (job.id, job.lease_token),
            ).fetchone()

            if row is None:
                return None

            generation = row["generation"]
            metadata = {key: value for key, value in row.items() if key != "generation"}
            return DocumentTask(DocumentReference(**metadata), generation)
