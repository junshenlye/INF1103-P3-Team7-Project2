"""Exercise validation of complete provider extraction payloads."""

import unittest

from src.config import limits
from src.errors.error_codes import INVALID_EXTRACTION
from src.errors.processing_error import ProcessingError
from src.managers import LogicManager
from src.models.projects.module import Module


class ExtractionValidationTests(unittest.TestCase):
    def setUp(self):
        self.logic = LogicManager()
        self.module = Module("module-1", "project-1", "job-1", "Intro Computing", "intro computing", 6, 1)
        self.record = {
            "key": "quiz",
            "name": "Quiz",
            "kind": "assessment",
            "weight_percent": None,
            "weight_scope": "unknown",
            "week": 3,
            "end_week": None,
            "parent_key": None,
            "evidence": {
                "name": ["b", "a", "b"],
                "kind": ["a"],
                "weight_scope": ["a"],
                "week": ["a"],
            },
        }
        self.payload = {
            "module_title": "  INTRO   computing ",
            "assessments": [self.record],
            "uncertainties": ["Confirm the weight."],
        }

    def validate(self, payload):
        return self.logic.validate_extraction(payload, self.module, iter(["a", "b"]), 14)

    def test_normalizes_citations_without_mutating_the_payload(self):
        records, uncertainties = self.validate(self.payload)
        self.assertEqual(records[0]["evidence"]["name"], ["a", "b"])
        self.assertEqual(self.record["evidence"]["name"], ["b", "a", "b"])
        self.assertEqual(uncertainties, self.payload["uncertainties"])
        self.assertIsNot(uncertainties, self.payload["uncertainties"])

    def test_accepts_an_empty_extraction(self):
        self.assertEqual(self.validate({**self.payload, "assessments": []})[0], [])

    def test_rejects_shape_title_and_size_violations_with_module_id(self):
        for payload in (
            {**self.payload, "extra": True},
            {**self.payload, "module_title": "Other"},
            {**self.payload, "assessments": [self.record] * (limits.ASSESSMENTS_PER_CHUNK + 1)},
            {**self.payload, "uncertainties": ["x" * (limits.UNCERTAINTY_LENGTH + 1)]},
        ):
            with self.subTest():
                with self.assertRaises(ProcessingError) as caught:
                    self.validate(payload)
                self.assertEqual(caught.exception.code, INVALID_EXTRACTION)
                self.assertEqual(caught.exception.related_ids, {"module_id": self.module.id})

    def test_rejects_duplicate_keys_and_invalid_facts_or_citations(self):
        for records in (
            [self.record, self.record],
            [{**self.record, "unexpected": True}],
            [{**self.record, "week": 15}],
            [{**self.record, "weight_percent": 10**400}],
            [{**self.record, "evidence": {**self.record["evidence"], "week": ["foreign"]}}],
        ):
            with self.subTest():
                with self.assertRaises(ProcessingError) as caught:
                    self.validate({**self.payload, "assessments": records})
                self.assertEqual(caught.exception.code, INVALID_EXTRACTION)
