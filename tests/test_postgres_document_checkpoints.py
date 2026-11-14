"""Verify that saved parsing and extraction data reaches the worker."""

from contextlib import nullcontext
import unittest
from unittest.mock import Mock

from src.config.limits import CHUNK_BYTES
from src.models.processing.checkpoint import DocumentCheckpoint
from src.storage.postgres_document_checkpoints import PostgresDocumentCheckpoints


class PostgresDocumentCheckpointsTests(unittest.TestCase):
    def setUp(self):
        self.connection = Mock()
        self.connection.transaction.return_value = nullcontext()
        pool = Mock()
        pool.connection.return_value = nullcontext(self.connection)
        self.store = PostgresDocumentCheckpoints(pool)

    def test_document_without_saved_parse_returns_empty_checkpoint(self):
        self.connection.execute.return_value.fetchone.return_value = None

        self.assertEqual(
            self.store.get_document_checkpoint("doc"),
            DocumentCheckpoint(None, (), {}, CHUNK_BYTES, 0),
        )
        self.assertEqual(self.connection.execute.call_count, 2)

    def test_loads_saved_parse_and_reusable_chunks_from_one_snapshot(self):
        element = {
            "id": "source", "document_id": "doc", "parse_id": "parse",
            "text": "Sample text", "regions": [], "context": "",
        }
        chunk = {"chunk_index": 2, "records": [{"key": "quiz"}], "uncertainties": []}
        self.connection.execute.side_effect = [
            None,
            Mock(fetchone=Mock(return_value={"id": "parse", "chunk_count": 3, "chunk_bytes": 2048})),
            Mock(fetchall=Mock(return_value=[element])),
            Mock(fetchall=Mock(return_value=[chunk])),
        ]

        saved = self.store.get_document_checkpoint("doc")

        self.assertEqual((saved.parse_id, saved.chunk_count, saved.chunk_bytes), ("parse", 3, 2048))
        self.assertEqual(saved.elements[0].id, "source")
        self.assertEqual(saved.chunks["2"]["records"][0]["key"], "quiz")
        self.connection.transaction.assert_called_once_with()
        isolation, parse_query, source_query, chunk_query = self.connection.execute.call_args_list
        self.assertIn("REPEATABLE READ", isolation.args[0])
        self.assertEqual(parse_query.args[1], ("doc",))
        self.assertIn("ORDER BY position", source_query.args[0])
        self.assertEqual(source_query.args[1], ("parse",))
        self.assertIn("BETWEEN task.minimum_generation AND task.generation", chunk_query.args[0])
        self.assertIn("OR chunk.generation = task.generation", chunk_query.args[0])
        self.assertIn("ORDER BY chunk.chunk_index, chunk.generation DESC", chunk_query.args[0])
        self.assertEqual(chunk_query.args[1], ("parse",))
