"""Record module-wide processing issues in PostgreSQL."""

from __future__ import annotations

import json

from src.contracts.postgres_pool import PostgresPool
from src.models.processing.processing_job import ProcessingJob
from src.storage.postgres_job_records import insert_issue, require_live_lease


class PostgresModuleIssues:
    """Implement the worker's save_module_issue operation."""

    def __init__(self, pool: PostgresPool):
        self.pool = pool

    def save_module_issue(self, job: ProcessingJob, issue: dict) -> None:
        """Record an issue that affects a whole module of ``job``.

        In one transaction, while the job's lease is live:

        - the issue is stored for the job;
        - the module's published result, if any, is marked stale, so an
          earlier valid result stays readable but is not treated as current;
        - every succeeded document task of the module (except replaced
          documents) carries the issue instead of any earlier module-wide
          issue, and is no longer counted as fully understood.

        Raises:
            ValueError: If the issue does not name a module.
            ProcessingError: ``processing_interrupted`` if the lease was lost.
        """
        module_id = issue.get("module_id")
        if not module_id:
            raise ValueError("A module issue must name its module.")
        with self.pool.connection() as connection, connection.transaction():
            require_live_lease(connection, job)
            insert_issue(connection, job.id, issue)
            connection.execute(
                "UPDATE stackplan.module_result_heads SET stale = true WHERE module_id = %s",
                (module_id,),
            )
            connection.execute(
                """
                UPDATE stackplan.document_tasks AS task
                SET issues = (
                        SELECT COALESCE(jsonb_agg(item), '[]'::jsonb)
                        FROM jsonb_array_elements(task.issues) AS item
                        WHERE item->>'document_id' IS NOT NULL
                    ) || %s::jsonb,
                    inference = 'partially_understood'
                FROM stackplan.documents AS document
                WHERE document.id = task.document_id AND document.module_id = %s
                    AND task.job_id = %s AND task.state = 'succeeded'
                    AND NOT EXISTS (
                        SELECT 1 FROM stackplan.document_replacements AS replaced
                        WHERE replaced.old_document_id = document.id
                    )
                """,
                (json.dumps([issue], ensure_ascii=False), module_id, job.id),
            )
