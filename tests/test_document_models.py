"""Tests for stored document metadata and processing references."""

from dataclasses import FrozenInstanceError, asdict
import unittest

from src.models.documents.document import Document
from src.models.documents.document_reference import DocumentReference


class DocumentModelTests(unittest.TestCase):
    def setUp(self):
        self.document = Document(
            id="document-1",
            module_id="module-1",
            filename="module-outline.pdf",
            media_type="application/pdf",
            size=2048,
            checksum="example-checksum",
            storage_key="originals/module-1/document-1.pdf",
        )

    def test_reference_preserves_metadata_without_storage_key(self):
        reference = self.document.to_reference()
        expected = asdict(self.document)
        del expected["storage_key"]

        self.assertIsInstance(reference, DocumentReference)
        self.assertEqual(asdict(reference), expected)

    def test_stored_document_and_reference_are_immutable(self):
        for metadata in (self.document, self.document.to_reference()):
            with self.subTest(model=type(metadata).__name__):
                with self.assertRaises(FrozenInstanceError):
                    metadata.filename = "renamed.pdf"
