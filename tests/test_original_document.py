import hashlib
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from src.config.limits import STREAM_CHUNK_BYTES
from src.errors.error_codes import SOURCE_MISSING
from src.errors.processing_error import ProcessingError
from src.models.documents.document import Document
from src.storage.original_document import open_verified_document


class VerifiedOriginalDocumentTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.path = self.root / "originals" / "source.pdf"
        self.path.parent.mkdir()
        self.contents = b"x" * (STREAM_CHUNK_BYTES + 1)
        self.path.write_bytes(self.contents)
        self.document = Document(
            id="document-1",
            module_id="module-1",
            filename="source.pdf",
            media_type="application/pdf",
            size=len(self.contents),
            checksum=hashlib.sha256(self.contents).hexdigest(),
            storage_key="originals/source.pdf",
        )

    def assert_source_missing(self, document):
        with self.assertRaises(ProcessingError) as caught:
            with open_verified_document(self.root, document):
                self.fail("An unavailable original was opened.")
        error = caught.exception
        self.assertEqual(error.code, SOURCE_MISSING)
        self.assertEqual(error.scope, "document")
        self.assertEqual(
            error.related_ids,
            {"document_id": document.id, "module_id": document.module_id},
        )

    def test_yields_from_start_and_closes_stream(self):
        with open_verified_document(self.root, self.document) as stream:
            self.assertEqual(stream.tell(), 0)
            self.assertEqual(stream.read(), self.contents)
        self.assertTrue(stream.closed)

    def test_rejects_size_and_checksum_mismatches(self):
        self.path.write_bytes(self.contents[:-1])
        self.assert_source_missing(self.document)
        self.path.write_bytes(b"y" + self.contents[1:])
        self.assert_source_missing(self.document)

    def test_rejects_missing_original_and_invalid_storage_key(self):
        self.path.unlink()
        self.assert_source_missing(self.document)
        self.assert_source_missing(replace(self.document, storage_key="originals/../source.pdf"))

    def test_propagates_consumer_errors_and_closes_stream(self):
        with self.assertRaisesRegex(OSError, "consumer error"):
            with open_verified_document(self.root, self.document) as stream:
                raise OSError("consumer error")
        self.assertTrue(stream.closed)
