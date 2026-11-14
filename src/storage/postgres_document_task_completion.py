"""Store the terminal outcome of a leased document task."""

from __future__ import annotations

import json
from uuid import uuid4

from src.contracts.postgres_pool import PostgresPool
from src.errors import error_codes as errors
from src.errors.processing_error import ProcessingError
from src.models.processing import lifecycle
from src.models.processing.document_task import DocumentOutcome, DocumentTask
from src.models.processing.processing_job import ProcessingJob


class PostgresDocumentTaskCompletion:
    """Settle a document task and record its progress and issues atomically."""

    def __init__(self, pool: PostgresPool):
        self.pool = pool

    def finish_document_task(
        self, job: ProcessingJob, task: DocumentTask, outcome: DocumentOutcome
    ) -> None:
        """Settle the current generation while the job owns its lease."""
        document = task.document
        state = "succeeded" if outcome.records else "failed"
        progress = lifecycle.EXTRACTED if outcome.records else "failed"
        with self.pool.connection() as connection, connection.transaction():
            lease = connection.execute(
                """
                SELECT 1 FROM stackplan.processing_jobs
                WHERE id = %s AND status = %s AND lease_token = %s
                    AND lease_expires_at > clock_timestamp()
                FOR UPDATE
                """,
                (job.id, lifecycle.RUNNING, job.lease_token),
            ).fetchone()
            if lease is None:
                raise ProcessingError(
                    errors.PROCESSING_INTERRUPTED, errors.INTERRUPTION_MESSAGE,
                    "system", job_id=job.id,
                )

            completed = connection.execute(
                """
                UPDATE stackplan.document_tasks
                SET state = %s, inference = %s, issues = %s::jsonb,
                    uncertainties = %s::jsonb, owner_token = NULL, updated_at = now()
                WHERE document_id = %s AND job_id = %s AND generation = %s
                    AND owner_token = %s AND state = %s
                RETURNING document_id
                """,
                (
                    state, outcome.inference, json.dumps(outcome.issues, allow_nan=False),
                    json.dumps(outcome.uncertainties, allow_nan=False), document.id,
                    job.id, task.generation, job.lease_token, lifecycle.RUNNING,
                ),
            ).fetchone()
            if completed is None:
                raise ProcessingError(
                    errors.PROCESSING_INTERRUPTED,
                    "This document attempt is no longer current.",
                    "document", document_id=document.id, module_id=document.module_id,
                )

            connection.execute(
                """
                INSERT INTO stackplan.document_progress (document_id, state)
                VALUES (%s, %s)
                ON CONFLICT (document_id) DO UPDATE SET state = EXCLUDED.state
                """,
                (document.id, progress),
            )
            for issue in outcome.issues:
                connection.execute(
                    """
                    INSERT INTO stackplan.processing_issues (
                        id, job_id, module_id, document_id, code, severity, message, scope
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        str(uuid4()), job.id, issue.get("module_id"), issue.get("document_id"),
                        issue["code"], issue.get("severity", "error"), issue["message"], issue["scope"],
                    ),
                )
