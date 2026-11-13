"""Tests for converting unexpected failures into safe processing errors."""

import unittest

from src.errors.error_codes import (
    INVALID_EXTRACTION,
    PROVIDER_FAILURE_MESSAGE,
    PROVIDER_UNAVAILABLE,
)
from src.errors.issues import issue_from_error
from src.errors.processing_error import ProcessingError, safe_processing_error


class SafeProcessingErrorTests(unittest.TestCase):
    def test_processing_errors_are_returned_unchanged(self):
        error = ProcessingError(INVALID_EXTRACTION, "Bad extraction.", "module", module_id="m-1")
        self.assertIs(safe_processing_error(error), error)

    def test_unexpected_errors_become_a_generic_system_failure(self):
        cases = (
            RuntimeError("https://internal.example/convert?token=secret returned 502"),
            KeyError("document"),
            TimeoutError(),
            ValueError(""),
        )
        for original in cases:
            with self.subTest(error=type(original).__name__):
                safe = safe_processing_error(original)
                self.assertIsInstance(safe, ProcessingError)
                self.assertEqual(safe.code, PROVIDER_UNAVAILABLE)
                self.assertEqual(safe.message, PROVIDER_FAILURE_MESSAGE)
                self.assertEqual(safe.scope, "system")
                self.assertEqual(safe.related_ids, {})

    def test_internal_details_are_not_exposed(self):
        safe = safe_processing_error(RuntimeError("token=secret at /var/data/upload.pdf"))
        issue = issue_from_error(safe, document_id="d-1")
        for text in (str(safe), safe.message, repr(issue)):
            self.assertNotIn("secret", text)
            self.assertNotIn("/var/data", text)
        self.assertEqual(issue["document_id"], "d-1")
        self.assertEqual(issue["code"], PROVIDER_UNAVAILABLE)

    def test_each_call_returns_a_new_error(self):
        first = safe_processing_error(RuntimeError("a"))
        second = safe_processing_error(RuntimeError("b"))
        self.assertIsNot(first, second)


if __name__ == "__main__":
    unittest.main()
