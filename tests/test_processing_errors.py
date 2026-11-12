"""Tests for stable, immutable and serialisable processing issues."""

import unittest
from dataclasses import FrozenInstanceError

from src.errors.error_codes import INVALID_REQUEST
from src.errors.issues import issue_from_error, make_issue
from src.errors.processing_error import ProcessingError
from src.errors.processing_issue import ProcessingIssue


class ProcessingErrorTests(unittest.TestCase):
    def test_error_keeps_safe_domain_details_and_related_ids(self):
        error = ProcessingError(
            INVALID_REQUEST, "The request is invalid.", "request", job_id="job-1"
        )
        self.assertEqual(str(error), "The request is invalid.")
        self.assertEqual(error.code, INVALID_REQUEST)
        self.assertEqual(error.scope, "request")
        self.assertEqual(error.related_ids, {"job_id": "job-1"})

    def test_unknown_error_codes_are_rejected(self):
        with self.assertRaises(ValueError):
            ProcessingError("unregistered_code", "Safe message")


class ProcessingIssueTests(unittest.TestCase):
    def test_issue_is_immutable(self):
        issue = ProcessingIssue(INVALID_REQUEST, "Bad input.", "request")
        with self.assertRaises(FrozenInstanceError):
            issue.message = "Changed"

    def test_make_issue_returns_serialisable_fields_and_defaults(self):
        issue = make_issue(INVALID_REQUEST, "Bad input.")
        self.assertEqual(
            issue,
            {
                "code": INVALID_REQUEST,
                "message": "Bad input.",
                "scope": "system",
                "severity": "error",
                "job_id": None,
                "module_id": None,
                "document_id": None,
            },
        )

    def test_make_issue_rejects_unknown_codes(self):
        with self.assertRaises(ValueError):
            make_issue("unregistered_code", "Bad input.")

    def test_issue_from_error_preserves_related_identifiers(self):
        error = ProcessingError(
            INVALID_REQUEST,
            "Bad input.",
            "module",
            job_id="job-1",
            document_id="document-1",
        )
        issue = issue_from_error(error, module_id="module-1")
        self.assertEqual(issue["job_id"], "job-1")
        self.assertEqual(issue["module_id"], "module-1")
        self.assertEqual(issue["document_id"], "document-1")


if __name__ == "__main__":
    unittest.main()
