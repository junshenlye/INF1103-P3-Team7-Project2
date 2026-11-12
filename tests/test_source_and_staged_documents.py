"""Tests for parsed source elements and staged upload records."""

from dataclasses import FrozenInstanceError, asdict
import unittest

from src.models.documents.source_element import SourceElement
from src.models.documents.staged_document import StagedDocument


class SourceElementTests(unittest.TestCase):
    def setUp(self):
        self.element = SourceElement(
            id="element-1",
            document_id="document-1",
            parse_id="parse-1",
            text="Quiz 1 (10%) in week 4",
            regions=[{"page": 1, "bbox": [10, 20, 200, 40]}],
            context="Assessment overview",
        )

    def test_can_be_rebuilt_from_stored_fields(self):
        self.assertEqual(SourceElement(**asdict(self.element)), self.element)

    def test_is_immutable(self):
        with self.assertRaises(FrozenInstanceError):
            self.element.text = "changed"


class StagedDocumentTests(unittest.TestCase):
    def test_new_upload_starts_empty_until_completed(self):
        staged = StagedDocument("request-1", "document-1", "outline.pdf", ".staging/r/d")
        self.assertEqual(
            (staged.final_key, staged.media_type, staged.size, staged.checksum),
            ("", "", 0, ""),
        )

    def test_records_progress_and_completion_details(self):
        staged = StagedDocument("request-1", "document-1", "outline.pdf", ".staging/r/d")
        staged.size += 1024
        staged.size += 512
        staged.media_type = "application/pdf"
        staged.checksum = "example-checksum"
        staged.final_key = "originals/document-1.pdf"

        self.assertEqual(staged.size, 1536)
        self.assertEqual(staged.final_key, "originals/document-1.pdf")
        self.assertEqual(staged.staging_key, ".staging/r/d")


if __name__ == "__main__":
    unittest.main()
