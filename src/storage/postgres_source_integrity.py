"""Record a warning when a settled project's original document is unavailable."""

from __future__ import annotations

from pathlib import Path

from src.contracts.postgres_pool import PostgresPool
from src.errors import error_codes as errors
from src.errors.issues import make_issue
from src.errors.processing_error import ProcessingError
from src.models.documents.document import Document
from src.models.processing import lifecycle
from src.storage.original_document import open_verified_document
from src.storage.postgres_job_records import insert_issue

MISSING_MESSAGE = "The original document is unavailable. Parsed evidence remains available."
CHECKED_STATUSES = (lifecycle.READY, lifecycle.PARTIAL)


class PostgresSourceIntegrity:
    """Check that a settled project's originals still match their records."""

    def __init__(self, pool: PostgresPool, document_directory: Path):
        self.pool = pool
        self.document_directory = Path(document_directory)

    def record_missing_sources(self, project_id: str) -> list[str]:
        """Warn about each current document whose original is unavailable.

        Only ``Ready`` and ``Partial`` projects are checked, because their
        schedules cite the originals as evidence. Replaced documents are
        skipped. An original is unavailable when it is missing, outside the
        storage root, or does not match its recorded size and SHA-256
        checksum. Each such document gets one ``source_missing`` warning for
        the project's job; a warning that already exists is kept as it is.

        The files are verified without holding a database connection.

        Returns:
            The ids of the documents found unavailable, sorted. An unknown
            or unsettled project returns an empty list.
        """
        with self.pool.connection() as connection:
            project = connection.execute(
                "SELECT status, job_id::text AS job_id FROM stackplan.projects WHERE id = %s",
                (project_id,),
            ).fetchone()
            if project is None or project["status"] not in CHECKED_STATUSES or project["job_id"] is None:
                return []
            rows = connection.execute(
                """
                SELECT document.id::text AS id, document.module_id::text AS module_id,
                       document.filename, document.media_type, document.size,
                       document.checksum, document.storage_key
                FROM stackplan.documents AS document
                JOIN stackplan.modules AS module ON module.id = document.module_id
                WHERE module.job_id = %s
                    AND NOT EXISTS (
                        SELECT 1 FROM stackplan.document_replacements AS replaced
                        WHERE replaced.old_document_id = document.id
                    )
                ORDER BY document.id
                """,
                (project["job_id"],),
            ).fetchall()

        documents = [Document(**row) for row in rows]
        missing = [document for document in documents if not self._available(document)]
        if not missing:
            return []
        with self.pool.connection() as connection, connection.transaction():
            for document in missing:
                insert_issue(
                    connection,
                    project["job_id"],
                    make_issue(
                        errors.SOURCE_MISSING,
                        MISSING_MESSAGE,
                        "document",
                        severity="warning",
                        module_id=document.module_id,
                        document_id=document.id,
                    ),
                )
        return [document.id for document in missing]

    def _available(self, document: Document) -> bool:
        try:
            with open_verified_document(self.document_directory, document):
                return True
        except ProcessingError as error:
            if error.code != errors.SOURCE_MISSING:
                raise
            return False
