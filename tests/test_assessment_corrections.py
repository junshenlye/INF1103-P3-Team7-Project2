"""Tests for applying reviewed assessment fact changes."""

import unittest

from src.errors import error_codes
from src.errors.processing_error import ProcessingError
from src.managers import LogicManager


class AssessmentCorrectionTests(unittest.TestCase):
    def setUp(self):
        self.logic = LogicManager()
        self.original = {
            "key": "quiz",
            "name": "Quiz",
            "kind": "assessment",
            "weight_percent": 10,
            "weight_scope": "module",
            "week": 4,
            "end_week": 6,
            "parent_key": None,
        }

    def test_applies_allowed_changes_without_mutating_the_original(self):
        changes = {"name": "Revised quiz", "week": 5, "weight_percent": None}
        corrected = self.logic.correct_assessment(self.original, changes, 14)

        self.assertEqual(corrected, {**self.original, **changes})
        self.assertEqual(self.original["week"], 4)
        self.assertEqual(self.original["weight_percent"], 10)

    def test_rejects_empty_non_mapping_and_non_reviewable_changes(self):
        for changes in (None, [], {}, {"kind": "group"}, {"key": "other"}, {"evidence": {}}):
            with self.subTest(changes=changes):
                with self.assertRaises(ProcessingError) as caught:
                    self.logic.correct_assessment(self.original, changes, 14)
                self.assertEqual(caught.exception.code, error_codes.INVALID_REQUEST)
                self.assertEqual(caught.exception.scope, "assessment")

    def test_checks_the_corrected_record_as_a_whole(self):
        with self.assertRaisesRegex(ProcessingError, "end_week"):
            self.logic.correct_assessment(self.original, {"week": 7}, 14)

        corrected = self.logic.correct_assessment(self.original, {"week": 7, "end_week": 8}, 14)
        self.assertEqual((corrected["week"], corrected["end_week"]), (7, 8))
