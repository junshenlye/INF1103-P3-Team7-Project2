"""SQL steps shared by the worker's job settlement adapters.

Each function runs inside the caller's transaction on an open connection.
"""

from __future__ import annotations

from uuid import uuid4

from src.errors import error_codes as errors
from src.errors.processing_error import ProcessingError
from src.models.processing import lifecycle


def require_live_lease(connection, job) -> None:
    """Lock ``job`` and require that the caller still holds its unexpired lease.

    Raises:
        ProcessingError: ``processing_interrupted`` when the lease was lost.
    """
    row = connection.execute(
        """
        SELECT id FROM stackplan.processing_jobs
        WHERE id = %s AND status = %s AND lease_token = %s
            AND lease_expires_at > clock_timestamp()
        FOR UPDATE
        """,
        (job.id, lifecycle.RUNNING, job.lease_token),
    ).fetchone()
    if row is None:
        raise ProcessingError(
            errors.PROCESSING_INTERRUPTED,
            errors.INTERRUPTION_MESSAGE,
            "system",
            job_id=job.id,
        )


def insert_issue(connection, job_id: str, issue: dict) -> None:
    """Store one issue dictionary (as built by ``make_issue``) for ``job_id``."""
    connection.execute(
        """
        INSERT INTO stackplan.processing_issues
            (id, job_id, module_id, document_id, code, severity, message, scope)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT DO NOTHING
        """,
        (
            str(uuid4()),
            job_id,
            issue.get("module_id"),
            issue.get("document_id"),
            issue["code"],
            issue.get("severity", "error"),
            issue["message"],
            issue["scope"],
        ),
    )


def stop_unfinished_documents(connection, job_id: str) -> None:
    """Mark queued and running document tasks of ``job_id`` as failed."""
    connection.execute(
        """
        UPDATE stackplan.document_tasks SET state = 'failed', owner_token = NULL
        WHERE job_id = %s AND state IN ('queued', 'running')
        """,
        (job_id,),
    )


def finish_job(connection, job_id: str, project_id: str, status: str) -> None:
    """Settle ``job_id`` and its project with a terminal ``status``."""
    stage = lifecycle.terminal_stage(status)
    connection.execute(
        """
        UPDATE stackplan.processing_jobs
        SET status = %s, stage = %s, lease_token = NULL, lease_expires_at = NULL,
            finished_at = clock_timestamp()
        WHERE id = %s
        """,
        (status, stage, job_id),
    )
    connection.execute(
        "UPDATE stackplan.projects SET status = %s WHERE id = %s",
        (status, project_id),
    )
