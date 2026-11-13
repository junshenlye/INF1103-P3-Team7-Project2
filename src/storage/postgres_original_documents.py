"""Look up and verify original uploads for document processing."""

from pathlib import Path
from typing import BinaryIO, ContextManager

from src.contracts.postgres_pool import PostgresPool
from src.errors.error_codes import NOT_FOUND
from src.errors.processing_error import ProcessingError
from src.models.documents.document import Document
from src.storage.original_document import open_verified_document


class PostgresOriginalDocuments:
    """Read stored metadata and open originals from the configured directory."""

    def __init__(self, pool: PostgresPool, document_directory: Path):
        self.pool = pool
        self.document_directory = document_directory

    def get_document(self, document_id: str) -> Document:
        """Return stored metadata for one original upload."""
        with self.pool.connection() as connection:
            row = connection.execute(
                """
                SELECT id::text AS id, module_id::text AS module_id, filename,
                       media_type, size, checksum, storage_key
                FROM stackplan.documents
                WHERE id = %s
                """,
                (document_id,),
            ).fetchone()
        if row is None:
            raise ProcessingError(
                NOT_FOUND, "Document was not found.", "document", document_id=document_id
            )
        return Document(**row)

    def open_document(self, document_id: str) -> ContextManager[BinaryIO]:
        """Open the verified original for a worker, closing it on context exit."""
        return open_verified_document(self.document_directory, self.get_document(document_id))
