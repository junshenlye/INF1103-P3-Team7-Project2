"""Record each document's processing stage in PostgreSQL."""

from __future__ import annotations

from src.config.limits import LEASE_SECONDS
from src.contracts.postgres_pool import PostgresPool
from src.errors import error_codes as errors
from src.errors.processing_error import ProcessingError
from src.models.processing import lifecycle
from src.models.processing.processing_job import ProcessingJob

# The progress state each recorded stage may follow. Progress moves forward,
# except that a resumed document passes through parsing again before it
# continues from its saved parse. An extracted document never moves back.
ALLOWED_PREVIOUS = {
    lifecycle.PARSING: ("waiting", "unknown", "failed", lifecycle.PARSING, lifecycle.EXTRACTING),
    lifecycle.EXTRACTING: (lifecycle.PARSING, lifecycle.EXTRACTING),
    lifecycle.EXTRACTED: (lifecycle.EXTRACTING, lifecycle.EXTRACTED),
}


class PostgresDocumentProgress:
    """Implement the worker's document progress operation."""

    def __init__(self, pool: PostgresPool, lease_seconds: int = LEASE_SECONDS):
        self.pool = pool
        self.lease_seconds = lease_seconds

    def save_document_progress(self, job: ProcessingJob, document_id: str, state: str) -> None:
        """Record ``state`` for a document of ``job`` while the job's lease is live.

        The job's lease is renewed in the same transaction, and its stage
        follows parsing and extracting. A document outside the job, a lost
        lease or a backwards move is rejected without changing anything.

        Raises:
            ValueError: If ``state`` is not a recorded processing stage.
            ProcessingError: ``processing_interrupted`` if the lease was lost,
                or ``invalid_request`` if the move is not allowed.
        """
        if state not in ALLOWED_PREVIOUS:
            raise ValueError(f"Unsupported document progress state {state!r}.")
        with self.pool.connection() as connection, connection.transaction():
            lease = connection.execute(
                """
                UPDATE stackplan.processing_jobs
                SET lease_expires_at = clock_timestamp() + %s * interval '1 second',
                    stage = COALESCE(%s, stage)
                WHERE id = %s AND status = %s AND lease_token = %s
                    AND lease_expires_at > clock_timestamp()
                RETURNING id
                """,
                (
                    self.lease_seconds,
                    state if state != lifecycle.EXTRACTED else None,
                    job.id,
                    lifecycle.RUNNING,
                    job.lease_token,
                ),
            ).fetchone()
            if lease is None:
                raise ProcessingError(
                    errors.PROCESSING_INTERRUPTED,
                    errors.INTERRUPTION_MESSAGE,
                    "system",
                    job_id=job.id,
                )
            saved = connection.execute(
                """
                INSERT INTO stackplan.document_progress (document_id, state)
                SELECT document.id, %s
                FROM stackplan.documents AS document
                JOIN stackplan.modules AS module ON module.id = document.module_id
                WHERE document.id = %s AND module.job_id = %s
                ON CONFLICT (document_id) DO UPDATE SET state = EXCLUDED.state
                WHERE stackplan.document_progress.state = ANY(%s)
                RETURNING document_id
                """,
                (state, document_id, job.id, list(ALLOWED_PREVIOUS[state])),
            ).fetchone()
            if saved is None:
                raise ProcessingError(
                    errors.INVALID_REQUEST,
                    "The document progress update is not valid for this job.",
                    "document",
                    document_id=document_id,
                )
