from dataclasses import replace
import unittest

from src.config import limits
from src.config.settings import load_settings


class UploadBoundsTests(unittest.TestCase):
    def setUp(self):
        self.settings = load_settings({"DATABASE_URL": "postgresql://localhost/stackplan"})

    def test_defaults_and_equal_limits(self):
        self.assertEqual(self.settings.request_bytes, limits.REQUEST_BYTES)
        self.assertEqual(self.settings.document_bytes, limits.DOCUMENT_BYTES)
        self.assertEqual(replace(self.settings, request_bytes=5, document_bytes=5).document_bytes, 5)

    def test_rejects_invalid_bounds(self):
        for request_bytes, document_bytes in (
            (0, 0), (5, 0), (5, 6), (limits.REQUEST_BYTES + 1, 5), (5, True), (5.5, 5),
        ):
            with self.subTest(request_bytes=request_bytes, document_bytes=document_bytes):
                with self.assertRaisesRegex(ValueError, "Invalid upload bounds"):
                    replace(self.settings, request_bytes=request_bytes, document_bytes=document_bytes)
