"""Verify that the worker can open a stored original by document ID."""

from contextlib import nullcontext
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

from src.errors.error_codes import NOT_FOUND, SOURCE_MISSING
from src.errors.processing_error import ProcessingError
from src.storage.postgres_original_documents import PostgresOriginalDocuments


class PostgresOriginalDocumentsTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.document_id = "4f81b0f2-3345-4656-890c-a350ca304fd1"
        key = f"originals/{self.document_id}.pdf"
        self.original = root / key
        self.original.parent.mkdir()
        self.contents = b"example PDF bytes"
        self.original.write_bytes(self.contents)
        self.connection = Mock()
        self.cursor = self.connection.execute.return_value
        self.cursor.fetchone.return_value = dict(
            id=self.document_id,
            module_id="module",
            filename="outline.pdf",
            media_type="application/pdf",
            size=len(self.contents),
            checksum=sha256(self.contents).hexdigest(),
            storage_key=key,
        )
        pool = Mock()
        pool.connection.return_value = nullcontext(self.connection)
        self.documents = PostgresOriginalDocuments(pool, root)

    def test_worker_reads_verified_original_and_context_closes_stream(self):
        with self.documents.open_document(self.document_id) as stream:
            self.assertEqual(stream.read(), self.contents)
        self.assertTrue(stream.closed)
        sql, params = self.connection.execute.call_args.args
        self.assertIn("FROM stackplan.documents", sql)
        self.assertEqual(params, (self.document_id,))

    def test_missing_metadata_raises_not_found(self):
        self.cursor.fetchone.return_value = None
        with self.assertRaises(ProcessingError) as raised:
            with self.documents.open_document(self.document_id):
                self.fail("No original should be opened.")
        self.assertEqual(raised.exception.code, NOT_FOUND)

    def test_changed_original_is_rejected(self):
        self.original.write_bytes(b"x" * len(self.contents))
        with self.assertRaises(ProcessingError) as raised:
            with self.documents.open_document(self.document_id):
                self.fail("An original with a bad checksum should not be opened.")
        self.assertEqual(raised.exception.code, SOURCE_MISSING)
        self.assertEqual(raised.exception.related_ids["document_id"], self.document_id)
