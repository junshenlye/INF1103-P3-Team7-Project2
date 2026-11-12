"""Tests for shared application bounds and their cross-field invariants."""

import unittest

from src.config import limits


class ApplicationLimitTests(unittest.TestCase):
    def test_upload_limits_are_positive_and_ordered(self):
        self.assertGreater(limits.REQUEST_BYTES, 0)
        self.assertGreater(limits.DOCUMENT_BYTES, 0)
        self.assertLessEqual(limits.DOCUMENT_BYTES, limits.REQUEST_BYTES)

    def test_multipart_part_count_covers_all_document_slots(self):
        self.assertEqual(
            limits.MULTIPART_PART_COUNT,
            limits.MODULE_COUNT * limits.DOCUMENTS_PER_MODULE + 1,
        )

    def test_chunk_and_pool_bounds_are_consistent(self):
        self.assertLessEqual(limits.MIN_CHUNK_BYTES, limits.CHUNK_BYTES)
        self.assertLessEqual(limits.CHUNK_BYTES, limits.MAX_CHUNK_BYTES)
        self.assertLessEqual(limits.CHUNK_COUNT, limits.MAX_CHUNK_COUNT)
        self.assertLessEqual(limits.POOL_SIZE, limits.MAX_POOL_SIZE)

    def test_supported_media_types_are_explicit(self):
        self.assertEqual(
            limits.MEDIA_TYPES,
            (limits.MEDIA_TYPE_PDF, limits.MEDIA_TYPE_PNG, limits.MEDIA_TYPE_JPEG),
        )

    def test_cleanup_age_includes_safety_window(self):
        self.assertEqual(
            limits.CLEANUP_AGE_SECONDS,
            2 * limits.CLEANUP_SAFETY_SECONDS,
        )


if __name__ == "__main__":
    unittest.main()
