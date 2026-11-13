"""Tests for combining assessment records extracted from separate chunks."""

import copy
import unittest

from src.errors import error_codes
from src.errors.processing_error import ProcessingError
from src.managers import LogicManager


def record(key="exam", source="source", **changes):
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
    fields["evidence"] = {k: [source] for k, v in fields.items() if k != "key" and v is not None}
    return fields


class MergeAssessmentTests(unittest.TestCase):
    def setUp(self):
        self.logic = LogicManager()

    def assert_rejected(self, records, code=error_codes.INVALID_EXTRACTION):
        with self.assertRaises(ProcessingError) as error:
            self.logic.merge_assessments(records)
        self.assertEqual(error.exception.code, code)
        self.assertEqual(error.exception.scope, "module")

    def test_missing_facts_are_filled_without_inventing_values(self):
        first = record(source="a")
        second = record(week=8, source="b")
        before = copy.deepcopy([first, second])

        merged = self.logic.merge_assessments([first, second])

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["week"], 8)
        self.assertIsNone(merged[0]["weight_percent"])
        self.assertEqual(merged[0]["evidence"]["week"], ["b"])
        self.assertEqual(merged[0]["evidence"]["name"], ["a", "b"])
        self.assertEqual([first, second], before)

    def test_repeated_citations_are_deduplicated(self):
        merged = self.logic.merge_assessments([record(week=3), record(week=3)])
        self.assertEqual(merged[0]["evidence"]["week"], ["source"])

    def test_results_are_ordered_by_key(self):
        merged = self.logic.merge_assessments([record("quiz"), record("exam"), record("lab")])
        self.assertEqual([r["key"] for r in merged], ["exam", "lab", "quiz"])

    def test_conflicting_facts_are_rejected(self):
        self.assert_rejected([record(week=8), record(week=9)])
        # A different weight scope is a conflict, not a silent overwrite.
        self.assert_rejected(
            [record(), record(week=8, weight_percent=50, weight_scope="module")]
        )

    def test_empty_input_reports_no_assessments(self):
        self.assert_rejected([], error_codes.NO_ASSESSMENTS)

    def test_relationships_are_checked_after_merging(self):
        parent = record("project", kind="group", weight_percent=40, weight_scope="module")
        children = [
            record("proposal", parent_key="project", weight_scope="group", weight_percent=25, week=4),
            record("report", parent_key="project", weight_scope="group", weight_percent=75, week=10),
        ]
        self.assertEqual(len(self.logic.merge_assessments([parent, *children])), 3)
        self.assert_rejected(children)
        self.assert_rejected(
            [record("a", kind="group", parent_key="b"), record("b", kind="group", parent_key="a")]
        )
        self.assert_rejected(
            [
                record("a", weight_percent=80, weight_scope="module"),
                record("b", weight_percent=30, weight_scope="module"),
            ]
        )

    def test_relationship_check_can_be_deferred(self):
        children = [record("quiz", parent_key="coursework", weight_scope="group")]
        merged = self.logic.merge_assessments(children, validate_relationships=False)
        self.assertEqual([r["key"] for r in merged], ["quiz"])


if __name__ == "__main__":
    unittest.main()
