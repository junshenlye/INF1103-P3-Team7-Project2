"""Tests for parsed source elements and staged upload records."""

from dataclasses import FrozenInstanceError, asdict
import unittest

from src.config.limits import DOCUMENT_NAME_LENGTH
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

    def test_normalizes_browser_filenames(self):
        for filename, expected in (
            ("../../brief.pdf", "brief.pdf"),
            (r"C:\fakepath\brief.png", "brief.png"),
            ("brief\x00\n.jpeg", "brief.jpeg"),
            ("folder/..", "document"),
            ("folder/", "document"),
        ):
            with self.subTest(filename=filename):
                staged = StagedDocument("r", "d", filename, ".staging/r/d")
                self.assertEqual(staged.filename, expected)
                self.assertEqual(staged.staging_key, ".staging/r/d")

    def test_shortens_long_names_and_preserves_supported_extension(self):
        staged = StagedDocument("r", "d", "x" * DOCUMENT_NAME_LENGTH + ".JPEG", ".staging/r/d")
        self.assertEqual(staged.filename, "x" * (DOCUMENT_NAME_LENGTH - 5) + ".JPEG")

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
