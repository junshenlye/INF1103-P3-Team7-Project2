"""Tests for transferring reviewed assessment facts and evidence."""

import unittest

from src.models.processing import ReviewTransfer


class ReviewTransferTests(unittest.TestCase):
    def test_retains_assessment_lineage(self):
        transfer = ReviewTransfer("quiz-1", "assessment-42", 3, {"week": 5}, {})

        self.assertEqual(transfer.key, "quiz-1")
        self.assertEqual(transfer.previous_assessment_id, "assessment-42")
        self.assertEqual(transfer.revision, 3)
        self.assertEqual(transfer.facts["week"], 5)

    def test_detaches_and_freezes_nested_data(self):
        facts = {"week": 5}
        evidence = {"week": [{"source_id": "source-1"}]}
        transfer = ReviewTransfer("quiz-1", "assessment-42", 3, facts, evidence)

        facts["week"] = 7
        evidence["week"][0]["source_id"] = "source-2"
        evidence["week"].append({"source_id": "source-3"})

        self.assertEqual(transfer.facts["week"], 5)
        self.assertEqual(len(transfer.evidence["week"]), 1)
        self.assertEqual(transfer.evidence["week"][0]["source_id"], "source-1")
        with self.assertRaises(TypeError):
            transfer.facts["week"] = 8
        with self.assertRaises(TypeError):
            transfer.evidence["week"][0]["source_id"] = "source-4"
