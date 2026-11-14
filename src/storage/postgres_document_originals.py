"""Open a document's verified original using its PostgreSQL record."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator

from src.contracts.postgres_pool import PostgresPool
from src.errors import error_codes as errors
from src.errors.processing_error import ProcessingError
from src.models.documents.document import Document
from src.storage.original_document import open_original_chunks, open_verified_document


class PostgresDocumentOriginals:
    """Implement the worker's open_document operation."""

    def __init__(self, pool: PostgresPool, document_directory: Path):
        self.pool = pool
        self.document_directory = Path(document_directory)

    def get_document(self, document_id: str) -> Document:
        """Return the stored metadata for one document.

        Raises:
            ProcessingError: ``not_found`` when no such document exists.
        """
        with self.pool.connection() as connection:
            row = connection.execute(
                """
                SELECT id::text AS id, module_id::text AS module_id, filename,
                       media_type, size, checksum, storage_key
                FROM stackplan.documents WHERE id = %s
                """,
                (document_id,),
            ).fetchone()
        if row is None:
            raise ProcessingError(
                errors.NOT_FOUND,
                "The document was not found.",
                "document",
                document_id=document_id,
            )
        return Document(**row)

    @contextmanager
    def open_original(self, document_id: str) -> Iterator[tuple[Document, Iterator[bytes]]]:
        """Return public-response metadata and bounded chunks for a verified original."""
        document = self.get_document(document_id)
        with open_original_chunks(self.document_directory, document) as chunks:
            yield document, chunks

    @contextmanager
    def open_document(self, document_id: str) -> Iterator[BinaryIO]:
        """Yield the document's original at byte zero after checking its integrity.

        The database connection is returned to the pool before the file is
        read, so a slow parse never holds a connection. The original must
        match the recorded size and SHA-256 checksum.

        Raises:
            ProcessingError: ``not_found`` for an unknown document, or
                ``source_missing`` when the original is missing, outside the
                storage root, or does not match its record.
        """
        document = self.get_document(document_id)
        with open_verified_document(self.document_directory, document) as stream:
            yield stream
