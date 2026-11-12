"""Tests for immutable assessment review-transfer records."""

import unittest
from dataclasses import FrozenInstanceError

from src.models.processing import ReviewTransfer


class ReviewTransferTests(unittest.TestCase):
    def test_preserves_review_lineage_and_payload(self):
        transfer = ReviewTransfer(
            key="quiz-1",
            previous_assessment_id="assessment-old",
            revision=2,
            facts={"week": 10, "weight_percent": 40},
            evidence={"week": [{"source_id": "source-1", "quote": "Week 10"}]},
        )

        self.assertEqual(transfer.key, "quiz-1")
        self.assertEqual(transfer.previous_assessment_id, "assessment-old")
        self.assertEqual(transfer.revision, 2)
        self.assertEqual(transfer.facts["week"], 10)
        self.assertEqual(transfer.evidence["week"][0]["source_id"], "source-1")

    def test_detaches_and_freezes_nested_review_data(self):
        facts = {"week": 10}
        evidence = {"week": [{"quote": "Week 10"}]}
        transfer = ReviewTransfer("quiz-1", "assessment-old", 1, facts, evidence)

        facts["week"] = 12
        evidence["week"][0]["quote"] = "Week 12"

        self.assertEqual(transfer.facts["week"], 10)
        self.assertEqual(transfer.evidence["week"][0]["quote"], "Week 10")
        with self.assertRaises(TypeError):
            transfer.facts["week"] = 12
        with self.assertRaises(TypeError):
            transfer.evidence["week"][0]["quote"] = "Week 12"

    def test_record_fields_are_immutable(self):
        transfer = ReviewTransfer("quiz-1", "assessment-old", 1, {}, {})
        with self.assertRaises(FrozenInstanceError):
            transfer.revision = 2

    def test_rejects_negative_revision(self):
        with self.assertRaises(ValueError):
            ReviewTransfer("quiz-1", "assessment-old", -1, {}, {})


if __name__ == "__main__":
    unittest.main()
