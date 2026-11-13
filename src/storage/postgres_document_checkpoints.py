"""Load the saved parse and extraction chunks for a document retry."""

from src.config.limits import CHUNK_BYTES
from src.contracts.postgres_pool import PostgresPool
from src.models.documents.source_element import SourceElement
from src.models.processing.checkpoint import DocumentCheckpoint


class PostgresDocumentCheckpoints:
    """Read worker checkpoints from one consistent database snapshot."""

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
