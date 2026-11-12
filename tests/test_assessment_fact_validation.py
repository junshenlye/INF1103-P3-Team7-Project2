"""Tests for validating extracted assessment facts and their evidence."""

import unittest

from src.config import limits
from src.errors import error_codes
from src.errors.processing_error import ProcessingError
from src.managers import LogicManager


def record(key="exam", **changes):
    fields = {
        "key": key,
        "name": "Exam",
        "kind": "assessment",
        "weight_percent": None,
        "weight_scope": "unknown",
        "week": None,
        "end_week": None,
        "parent_key": None,
        **changes,
    }
    fields["evidence"] = {k: ["source"] for k, v in fields.items() if k != "key" and v is not None}
    return fields


class AssessmentFactTests(unittest.TestCase):
    def setUp(self):
        self.logic = LogicManager()

    def test_valid_records_are_returned_unchanged(self):
        cases = (
            record(),
            record(week=3, end_week=5, weight_percent=40, weight_scope="module"),
            record(week=14, weight_percent=0),
            record(kind="group", weight_percent=60, weight_scope="module"),
            record("quiz", parent_key="coursework", weight_scope="group", weight_percent=50.5),
        )
        for fact in cases:
            with self.subTest(fact=fact):
                self.assertIs(self.logic.validate_assessment_facts(fact, 14), fact)

    def test_rejects_invalid_values(self):
        cases = (
            {"key": ""},
            {"key": "k" * (limits.ASSESSMENT_KEY_LENGTH + 1)},
            {"name": "   "},
            {"name": None},
            {"kind": "exam"},
            {"kind": []},
            {"weight_scope": "course"},
            {"weight_scope": {}},
            {"weight_percent": float("nan")},
            {"weight_percent": -1},
            {"weight_percent": 101},
            {"weight_percent": True},
            {"week": 0},
            {"week": 15},
            {"week": "bad", "end_week": 8},
            {"week": None, "end_week": 8},
            {"week": 8, "end_week": 7},
            {"week": {}, "end_week": []},
            {"kind": "group", "week": 3},
            {"parent_key": "exam"},
            {"parent_key": ""},
            {"weight_scope": "group"},
        )
        for changes in cases:
            with self.subTest(changes=changes):
                with self.assertRaises(ProcessingError) as error:
                    self.logic.validate_assessment_facts(record(**changes), 14)
                self.assertEqual(error.exception.code, error_codes.INVALID_EXTRACTION)
                self.assertEqual(error.exception.scope, "module")

    def test_error_lists_every_violated_field(self):
        with self.assertRaises(ProcessingError) as error:
            self.logic.validate_assessment_facts(record(kind="exam", week=99, parent_key="exam"), 14)
        message = error.exception.message
        for field in ("kind:", "week:", "parent_key:"):
            self.assertIn(field, message)
        self.assertIn("between 1 and 14", message)


class SourceReferenceTests(unittest.TestCase):
    def setUp(self):
        self.logic = LogicManager()

    def test_populated_facts_with_known_evidence_are_accepted(self):
        fact = record(week=3, weight_percent=20, weight_scope="module")
        self.assertIs(self.logic.validate_source_references(fact, {"source"}), fact)

    def test_rejects_missing_unknown_or_malformed_evidence(self):
        missing = record(week=3)
        del missing["evidence"]["week"]
        unknown = record()
        unknown["evidence"]["name"] = ["other-source"]
        extra_field = record()
        extra_field["evidence"]["notes"] = ["source"]
        not_a_list = record()
        not_a_list["evidence"]["name"] = "source"
        too_many = record()
        too_many["evidence"]["name"] = ["source"] * (limits.EVIDENCE_IDS_PER_FACT + 1)
        no_evidence = record()
        no_evidence["evidence"] = None

        for name, fact in {
            "missing": missing,
            "unknown source": unknown,
            "extra field": extra_field,
            "not a list": not_a_list,
            "too many ids": too_many,
            "no evidence": no_evidence,
        }.items():
            with self.subTest(name):
                with self.assertRaises(ProcessingError) as error:
                    self.logic.validate_source_references(fact, {"source"})
                self.assertEqual(error.exception.code, error_codes.INVALID_EXTRACTION)

    def test_unpopulated_facts_need_no_evidence(self):
        fact = record()
        fact["evidence"] = {"name": ["source"], "kind": ["source"], "weight_scope": ["source"]}
        self.assertIs(self.logic.validate_source_references(fact, {"source"}), fact)


if __name__ == "__main__":
    unittest.main()
