"""Tests for carrying reviewed corrections onto a new extraction."""

import copy
import unittest
from uuid import uuid4

from src.errors import error_codes
from src.errors.processing_error import ProcessingError
from src.managers import LogicManager
from src.models.processing.review_transfer import ReviewTransfer


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


def stored(original, reviewed, revision=1):
    """Build a stored assessment row as the review history keeps it."""
    return {
        "id": str(uuid4()),
        "revision": revision,
        "original_facts": {k: v for k, v in original.items() if k != "evidence"},
        "original_evidence": copy.deepcopy(original["evidence"]),
        "facts": {k: v for k, v in reviewed.items() if k != "evidence"},
        "evidence": copy.deepcopy(reviewed["evidence"]),
    }


class ReconcileReviewTests(unittest.TestCase):
    def setUp(self):
        self.logic = LogicManager()
        self.original = record(week=12, weight_percent=60, weight_scope="module")

    def assert_rejected(self, records, previous, code, source_ids=frozenset({"source"})):
        with self.assertRaises(ProcessingError) as error:
            self.logic.reconcile_reviews(records, previous, source_ids, 14)
        self.assertEqual(error.exception.code, code)
        self.assertEqual(error.exception.scope, "module")

    def test_reviewed_fields_carry_over_and_new_unreviewed_values_stay(self):
        prior = stored(self.original, {**self.original, "week": 10})
        new = record(week=12, weight_percent=40, weight_scope="module")
        before = copy.deepcopy(new)

        (transfer,) = self.logic.reconcile_reviews([new], [prior], {"source"}, 14)

        self.assertIsInstance(transfer, ReviewTransfer)
        self.assertEqual(transfer.key, "exam")
        self.assertEqual(transfer.previous_assessment_id, prior["id"])
        self.assertEqual(transfer.revision, 1)
        self.assertEqual(transfer.facts["week"], 10)
        self.assertEqual(transfer.facts["weight_percent"], 40)
        self.assertNotIn("evidence", transfer.facts)
        self.assertEqual(transfer.evidence["week"], ("source",))
        self.assertEqual(new, before)

    def test_evidence_only_review_is_carried(self):
        reviewed = copy.deepcopy(self.original)
        reviewed["evidence"]["week"] = ["source", "second"]
        prior = stored(self.original, reviewed)
        (transfer,) = self.logic.reconcile_reviews(
            [copy.deepcopy(self.original)], [prior], {"source", "second"}, 14
        )
        self.assertEqual(transfer.evidence["week"], ("source", "second"))

    def test_unreviewed_assessments_produce_no_transfer(self):
        prior = stored(self.original, self.original, revision=0)
        self.assertEqual(self.logic.reconcile_reviews([self.original], [prior], {"source"}, 14), ())

    def test_reviewed_assessment_missing_from_new_extraction_conflicts(self):
        prior = stored(self.original, {**self.original, "week": 10})
        self.assert_rejected([record("quiz")], [prior], error_codes.REVISION_CONFLICT)

    def test_correction_citing_a_replaced_source_conflicts(self):
        reviewed = {**self.original, "week": 10}
        reviewed["evidence"] = {**reviewed["evidence"], "week": ["old-source"]}
        prior = stored(self.original, reviewed)
        self.assert_rejected([copy.deepcopy(self.original)], [prior], error_codes.REVISION_CONFLICT)

    def test_reconciled_facts_are_revalidated(self):
        prior = stored(self.original, {**self.original, "week": 10})
        new = record(week=12, weight_percent=60, weight_scope="module")
        with self.assertRaises(ProcessingError) as error:
            self.logic.reconcile_reviews([new], [prior], {"source"}, 8)
        self.assertEqual(error.exception.code, error_codes.INVALID_EXTRACTION)

    def test_relationships_of_the_whole_result_are_checked(self):
        prior = stored(self.original, {**self.original, "week": 10})
        new = [
            record(week=12, weight_percent=60, weight_scope="module"),
            record("quiz", weight_percent=50, weight_scope="module"),
        ]
        self.assert_rejected(new, [prior], error_codes.INVALID_EXTRACTION)


if __name__ == "__main__":
    unittest.main()
