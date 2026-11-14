"""Save and load a document's parse and extraction chunks for retries."""

import json
from typing import Mapping

from src.config.limits import CHUNK_BYTES
from src.contracts.postgres_pool import PostgresPool
from src.errors import error_codes as errors
from src.errors.processing_error import ProcessingError
from src.models.documents.source_element import SourceElement
from src.models.processing import lifecycle
from src.models.processing.checkpoint import DocumentCheckpoint
from src.models.processing.processing_job import ProcessingJob

# Recorded with each saved parse so a later parser change can be recognised.
PARSER_VERSION = "docling-json-cells-v2"


def _plain(value):
    """Return JSON-ready data for the read-only values a checkpoint holds."""
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


class PostgresDocumentCheckpoints:
    """Save a document's parse once and read worker checkpoints consistently."""

    def __init__(self, pool: PostgresPool):
        self.pool = pool

    def get_document_checkpoint(self, document_id: str) -> DocumentCheckpoint:
        """Return the current parse and newest reusable chunk at each index."""
        with self.pool.connection() as connection, connection.transaction():
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            parse = connection.execute(
                """
                SELECT id::text AS id, chunk_count, chunk_bytes
                FROM stackplan.parse_snapshots WHERE document_id = %s
                """,
                (document_id,),
            ).fetchone()
            if parse is None:
                return DocumentCheckpoint(None, (), {}, CHUNK_BYTES, 0)

            elements = connection.execute(
                """
                SELECT id::text AS id, document_id::text AS document_id,
                       parse_id::text AS parse_id, text, regions, context
                FROM stackplan.source_elements WHERE parse_id = %s ORDER BY position
                """,
                (parse["id"],),
            ).fetchall()
            chunks = connection.execute(
                """
                SELECT DISTINCT ON (chunk.chunk_index)
                       chunk.chunk_index, chunk.records, chunk.uncertainties
                FROM stackplan.document_chunks AS chunk
                JOIN stackplan.document_tasks AS task ON task.document_id = chunk.document_id
                WHERE chunk.parse_id = %s
                    AND chunk.generation BETWEEN task.minimum_generation AND task.generation
                    AND (jsonb_array_length(chunk.records) > 0 OR chunk.generation = task.generation)
                ORDER BY chunk.chunk_index, chunk.generation DESC
                """,
                (parse["id"],),
            ).fetchall()

        return DocumentCheckpoint(
            parse_id=parse["id"],
            elements=tuple(SourceElement(**element) for element in elements),
            chunks={
                str(chunk["chunk_index"]): {
                    "records": chunk["records"],
                    "uncertainties": chunk["uncertainties"],
                }
                for chunk in chunks
            },
            chunk_bytes=parse["chunk_bytes"],
            chunk_count=parse["chunk_count"],
        )

    def save_document_checkpoint(
        self, job: ProcessingJob, document_id: str, checkpoint: DocumentCheckpoint
    ) -> None:
        """Save a new parse and its source elements for a document of ``job``.

        Runs while the job's lease is live, in one transaction. A saved parse
        is immutable: saving the same parse again changes nothing, while a
        different parse for the same document is rejected.

        Raises:
            ValueError: If the checkpoint has no parse, no elements or chunks,
                or an element belongs to another document or parse.
            ProcessingError: ``processing_interrupted`` if the lease was lost,
                or ``invalid_request`` for a document outside the job or a
                document that already has a different parse.
        """
        parse_id = checkpoint.parse_id
        if not parse_id or not checkpoint.elements or checkpoint.chunk_count < 1:
            raise ValueError("A document checkpoint needs a parse, source elements and chunks.")
        if any(e.document_id != document_id or e.parse_id != parse_id for e in checkpoint.elements):
            raise ValueError("Every source element must belong to the saved document and parse.")

        with self.pool.connection() as connection, connection.transaction():
            lease = connection.execute(
                """
                SELECT id FROM stackplan.processing_jobs
                WHERE id = %s AND status = %s AND lease_token = %s
                    AND lease_expires_at > clock_timestamp()
                FOR UPDATE
                """,
                (job.id, lifecycle.RUNNING, job.lease_token),
            ).fetchone()
            if lease is None:
                raise ProcessingError(
                    errors.PROCESSING_INTERRUPTED,
                    errors.INTERRUPTION_MESSAGE,
                    "system",
                    job_id=job.id,
                )
            owned = connection.execute(
                """
                SELECT parse.id::text AS parse_id
                FROM stackplan.documents AS document
                JOIN stackplan.modules AS module ON module.id = document.module_id
                LEFT JOIN stackplan.parse_snapshots AS parse ON parse.document_id = document.id
                WHERE document.id = %s AND module.job_id = %s
                """,
                (document_id, job.id),
            ).fetchone()
            if owned is None:
                raise ProcessingError(
                    errors.INVALID_REQUEST,
                    "The document does not belong to this job.",
                    "document",
                    document_id=document_id,
                )
            if owned["parse_id"] == parse_id:
                return
            if owned["parse_id"] is not None:
                raise ProcessingError(
                    errors.INVALID_REQUEST,
                    "The document already has a saved parse.",
                    "document",
                    document_id=document_id,
                )
            connection.execute(
                """
                INSERT INTO stackplan.parse_snapshots
                    (id, document_id, parser_version, chunk_count, chunk_bytes)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (parse_id, document_id, PARSER_VERSION, checkpoint.chunk_count, checkpoint.chunk_bytes),
            )
            for position, element in enumerate(checkpoint.elements):
                connection.execute(
                    """
                    INSERT INTO stackplan.source_elements
                        (id, document_id, parse_id, text, regions, context, position)
                    VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s)
                    """,
                    (
                        element.id,
                        document_id,
                        parse_id,
                        element.text,
                        json.dumps(_plain(element.regions), ensure_ascii=False),
                        element.context,
                        position,
                    ),
                )
