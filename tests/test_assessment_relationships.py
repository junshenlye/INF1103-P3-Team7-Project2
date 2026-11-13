"""Tests for assessment parent links and weight totals."""

import unittest

from src.errors.error_codes import INVALID_EXTRACTION
from src.errors.processing_error import ProcessingError
from src.managers import LogicManager


def assessment(key, *, parent=None, kind="assessment", weight=None, scope="module"):
    return {
        "key": key,
        "parent_key": parent,
        "kind": kind,
        "weight_percent": weight,
        "weight_scope": scope,
    }


class AssessmentRelationshipTests(unittest.TestCase):
    def setUp(self):
        self.logic = LogicManager()

    def assert_invalid(self, records, message):
        with self.assertRaisesRegex(ProcessingError, message) as caught:
            self.logic.validate_relationships(records)
        self.assertEqual(caught.exception.code, INVALID_EXTRACTION)

    def test_counts_a_group_total_once_and_preserves_inputs(self):
        records = [
            assessment("quiz", parent="coursework", weight=40),
            assessment("coursework", kind="group", weight=60),
            assessment("exam", weight=40),
            assessment("presentation", parent="coursework", weight=60, scope="group"),
        ]
        before = [dict(record) for record in records]
        self.assertIs(self.logic.validate_relationships(records), records)
        self.assertEqual(records, before)

    def test_rejects_duplicate_keys_missing_parents_and_non_group_parents(self):
        self.assert_invalid([assessment("a"), assessment("a")], "keys must be unique")
        self.assert_invalid([assessment("a", parent="missing")], "parent is missing or invalid")
        self.assert_invalid(
            [assessment("a"), assessment("b", parent="a")],
            "parent is missing or invalid",
        )

    def test_rejects_cycles(self):
        self.assert_invalid(
            [assessment("a", parent="b", kind="group"), assessment("b", parent="a", kind="group")],
            "contain a cycle",
        )

    def test_checks_parent_group_and_module_weight_limits(self):
        group = assessment("group", kind="group", weight=50)
        self.assert_invalid(
            [group, assessment("quiz", parent="group", weight=51)],
            "exceed their parent total",
        )
        self.assert_invalid(
            [
                group,
                assessment("a", parent="group", weight=60, scope="group"),
                assessment("b", parent="group", weight=50, scope="group"),
            ],
            "group weights exceed 100",
        )
        self.assert_invalid([group, assessment("exam", weight=60)], "module weights exceed 100")

    def test_handles_deep_groups_without_recursion(self):
        records = [assessment("0", kind="group")]
        records.extend(
            assessment(str(index), parent=str(index - 1), kind="group")
            for index in range(1, 1200)
        )
        self.assertIs(self.logic.validate_relationships(records), records)
