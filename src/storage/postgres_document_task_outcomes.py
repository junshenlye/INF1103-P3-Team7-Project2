"""Settle a claimed document task with its outcome in PostgreSQL."""

from __future__ import annotations

import json

from src.contracts.postgres_pool import PostgresPool
from src.models.processing.document_task import DocumentOutcome, DocumentTask
from src.models.processing.processing_job import ProcessingJob
from src.storage.postgres_job_records import insert_issue, require_current_document_task


class PostgresDocumentTaskOutcomes:
    """Implement the worker's finish_document_task operation."""

    def __init__(self, pool: PostgresPool):
        self.pool = pool

    def finish_document_task(
        self, job: ProcessingJob, task: DocumentTask, outcome: DocumentOutcome
    ) -> str:
        """Record what one claimed document attempt produced.

        Only the current attempt may finish: the job's lease must be live,
        and the task must still be running under this job's lease token and
        generation. A retried or replaced attempt cannot overwrite a newer
        one.

        A document that produced records succeeds and its progress becomes
        ``extracted``. One that produced none fails (so it can be retried),
        and its progress becomes ``failed``. Its inference, uncertainties and
        issues are stored on the task, and its issues are also recorded for
        the job.

        Returns:
            The task state written: ``succeeded`` or ``failed``.

        Raises:
            ProcessingError: ``processing_interrupted`` if the lease was lost
                or this attempt is no longer current.
        """
        with self.pool.connection() as connection, connection.transaction():
            require_current_document_task(connection, job, task)
            succeeded = bool(outcome.records)
            state = "succeeded" if succeeded else "failed"
            connection.execute(
                """
                UPDATE stackplan.document_tasks
                SET state = %s, inference = %s, issues = %s::jsonb,
                    uncertainties = %s::jsonb, owner_token = NULL,
                    updated_at = clock_timestamp()
                WHERE document_id = %s
                """,
                (
                    state,
                    outcome.inference,
                    json.dumps(list(outcome.issues), ensure_ascii=False),
                    json.dumps(list(outcome.uncertainties), ensure_ascii=False),
                    task.document.id,
                ),
            )
            connection.execute(
                """
                INSERT INTO stackplan.document_progress (document_id, state)
                VALUES (%s, %s)
                ON CONFLICT (document_id) DO UPDATE SET state = EXCLUDED.state
                """,
                (task.document.id, "extracted" if succeeded else "failed"),
            )
            for issue in outcome.issues:
                insert_issue(connection, job.id, issue)
        return state
