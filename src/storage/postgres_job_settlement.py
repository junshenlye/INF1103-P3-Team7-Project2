"""Complete or fail a claimed processing job in PostgreSQL."""

from __future__ import annotations

from src.contracts.postgres_pool import PostgresPool
from src.models.processing import lifecycle
from src.models.processing.lifecycle_policy import LifecyclePolicy
from src.models.processing.processing_job import ProcessingJob
from src.storage.postgres_job_records import (
    finish_job,
    insert_issue,
    require_live_lease,
    stop_unfinished_documents,
)


class PostgresJobSettlement:
    """Implement the worker's complete_job and fail_job operations."""

    def __init__(self, pool: PostgresPool):
        self.pool = pool

    def complete_job(self, job: ProcessingJob) -> str:
        """Settle a fully processed job as Ready, Partial or Failed.

        The outcome comes from ``LifecyclePolicy.settled_status``. It looks at
        how many modules have a published result, whether any result is
        stale, the job's current (not replaced) document tasks, and whether
        an unresolved error issue was recorded. The job and its project are
        updated together while the job's lease is live.

        Returns:
            The status the job settled with.

        Raises:
            ProcessingError: ``processing_interrupted`` if the lease was lost.
        """
        with self.pool.connection() as connection, connection.transaction():
            require_live_lease(connection, job)
            modules = connection.execute(
                "SELECT count(*) AS count FROM stackplan.modules WHERE job_id = %s",
                (job.id,),
            ).fetchone()["count"]
            heads = connection.execute(
                """
                SELECT head.stale FROM stackplan.module_result_heads AS head
                JOIN stackplan.modules AS module ON module.id = head.module_id
                WHERE module.job_id = %s
                """,
                (job.id,),
            ).fetchall()
            tasks = connection.execute(
                """
                SELECT task.state, task.inference, task.issues
                FROM stackplan.document_tasks AS task
                WHERE task.job_id = %s AND NOT EXISTS (
                    SELECT 1 FROM stackplan.document_replacements AS replaced
                    WHERE replaced.old_document_id = task.document_id
                )
                """,
                (job.id,),
            ).fetchall()
            has_errors = connection.execute(
                """
                SELECT 1 FROM stackplan.processing_issues
                WHERE job_id = %s AND NOT resolved AND severity = 'error' LIMIT 1
                """,
                (job.id,),
            ).fetchone() is not None
            status = LifecyclePolicy.settled_status(
                modules,
                len(heads),
                tasks,
                has_errors,
                any(head["stale"] for head in heads),
            )
            finish_job(connection, job.id, job.project_id, status)
        return status

    def fail_job(self, job: ProcessingJob, issues: list[dict], interrupted: bool = False) -> bool:
        """Settle a job that could not finish as Failed, or Interrupted.

        The job's issues are stored, its unfinished document tasks are
        marked failed so they can be retried, and the job and project are
        updated together. Nothing changes when the caller no longer owns the
        running job (for example, recovery already took it over), because
        another worker may now be responsible for it.

        Returns:
            True if the job was settled, False if the caller no longer owned it.
        """
        with self.pool.connection() as connection, connection.transaction():
            owned = connection.execute(
                """
                SELECT id FROM stackplan.processing_jobs
                WHERE id = %s AND status = %s AND lease_token = %s
                FOR UPDATE
                """,
                (job.id, lifecycle.RUNNING, job.lease_token),
            ).fetchone()
            if owned is None:
                return False
            for issue in issues:
                insert_issue(connection, job.id, issue)
            stop_unfinished_documents(connection, job.id)
            status = lifecycle.INTERRUPTED if interrupted else lifecycle.FAILED
            finish_job(connection, job.id, job.project_id, status)
        return True
