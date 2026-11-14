"""Recover processing jobs whose worker stopped renewing their lease."""

from __future__ import annotations

from src.contracts.postgres_pool import PostgresPool
from src.errors import error_codes as errors
from src.errors.issues import make_issue
from src.models.processing import lifecycle
from src.storage.postgres_job_records import finish_job, insert_issue, stop_unfinished_documents

MAX_RECOVERIES = 3
RECOVERY_EXHAUSTED_MESSAGE = (
    "Automatic worker recovery was exhausted. Retry the unfinished documents."
)


class PostgresJobRecovery:
    """Implement the worker's cleanup_interrupted_jobs operation."""

    def __init__(self, pool: PostgresPool, max_recoveries: int = MAX_RECOVERIES):
        if max_recoveries < 0:
            raise ValueError("max_recoveries cannot be negative.")
        self.pool = pool
        self.max_recoveries = max_recoveries

    def cleanup_interrupted_jobs(self) -> int:
        """Requeue or settle every running job whose lease has expired.

        Documents a lost worker was still processing go back to the queue,
        while finished documents and saved chunks are kept. A job is queued
        again until it has been recovered ``max_recoveries`` times; after
        that its unfinished documents are marked failed and the job settles
        as Interrupted with an issue asking for a manual retry. Jobs locked
        by another worker's recovery are skipped.

        Returns:
            The number of jobs recovered or settled.
        """
        with self.pool.connection() as connection, connection.transaction():
            jobs = connection.execute(
                """
                SELECT id::text AS id, project_id::text AS project_id, recoveries
                FROM stackplan.processing_jobs
                WHERE status = %s AND lease_expires_at <= clock_timestamp()
                ORDER BY lease_expires_at, id
                FOR UPDATE SKIP LOCKED
                """,
                (lifecycle.RUNNING,),
            ).fetchall()
            for job in jobs:
                connection.execute(
                    """
                    UPDATE stackplan.document_tasks SET state = 'queued', owner_token = NULL
                    WHERE job_id = %s AND state = 'running'
                    """,
                    (job["id"],),
                )
                connection.execute(
                    """
                    UPDATE stackplan.document_progress SET state = 'waiting'
                    WHERE state IN ('parsing', 'extracting') AND document_id IN (
                        SELECT document_id FROM stackplan.document_tasks
                        WHERE job_id = %s AND state = 'queued'
                    )
                    """,
                    (job["id"],),
                )
                if job["recoveries"] < self.max_recoveries:
                    connection.execute(
                        """
                        UPDATE stackplan.processing_jobs
                        SET status = %s, stage = %s, lease_token = NULL,
                            lease_expires_at = NULL, recoveries = recoveries + 1
                        WHERE id = %s
                        """,
                        (lifecycle.QUEUED, lifecycle.QUEUED, job["id"]),
                    )
                else:
                    stop_unfinished_documents(connection, job["id"])
                    insert_issue(
                        connection,
                        job["id"],
                        make_issue(errors.PROCESSING_INTERRUPTED, RECOVERY_EXHAUSTED_MESSAGE),
                    )
                    finish_job(connection, job["id"], job["project_id"], lifecycle.INTERRUPTED)
        return len(jobs)
