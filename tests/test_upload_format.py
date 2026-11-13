import unittest

from src.config import limits
from src.errors.error_codes import INVALID_DOCUMENT
from src.errors.processing_error import ProcessingError
from src.storage.upload_format import identify_upload_format


class UploadFormatTests(unittest.TestCase):
    def test_recognizes_supported_formats_and_normalizes_suffixes(self):
        for filename, header, expected in (
            ("brief.PDF", b"%PDF-1.7", (limits.MEDIA_TYPE_PDF, ".pdf")),
            ("brief.png", b"\x89PNG\r\n\x1a\n", (limits.MEDIA_TYPE_PNG, ".png")),
            ("brief.jpg", b"\xff\xd8\xff\xe0", (limits.MEDIA_TYPE_JPEG, ".jpg")),
            ("brief.JPEG", b"\xff\xd8\xff\xe1", (limits.MEDIA_TYPE_JPEG, ".jpg")),
        ):
            with self.subTest(filename=filename):
                self.assertEqual(identify_upload_format(filename, header), expected)

    def test_rejects_unknown_truncated_or_mismatched_signatures(self):
        for filename, header in (
            ("brief.pdf", b""),
            ("brief.pdf", b"%PDF"),
            ("brief.pdf", b"not pdf"),
            ("brief.png", b"\x89PNG\r\n\x1a"),
            ("brief.jpg", b"\xff\xd8"),
            ("brief.png", b"%PDF-1.7"),
            ("brief.pdf.exe", b"%PDF-1.7"),
            ("brief", b"%PDF-1.7"),
        ):
            with self.subTest(filename=filename, header=header):
                with self.assertRaises(ProcessingError) as error:
                    identify_upload_format(filename, header)
                self.assertEqual(error.exception.code, INVALID_DOCUMENT)
                self.assertEqual(error.exception.scope, "document")
