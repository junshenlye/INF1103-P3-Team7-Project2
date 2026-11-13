"""Tests for the immutable module reconciliation checkpoint."""

import unittest
from dataclasses import FrozenInstanceError

from src.models.processing.checkpoint import ModuleCheckpoint


def checkpoint(**changes):
    fields = {
        "records": [{"key": "quiz", "week": 4, "evidence": {"week": ["source-1"]}}],
        "uncertainties": ["Quiz: weight_percent could not be inferred from this source."],
        "source_ids": {"source-1"},
        "manifest": "manifest-1",
        "unchanged": False,
        **changes,
    }
    return ModuleCheckpoint(**fields)


class ModuleCheckpointTests(unittest.TestCase):
    def test_captures_reconciliation_inputs(self):
        saved = checkpoint()
        self.assertEqual(saved.records[0]["key"], "quiz")
        self.assertEqual(saved.uncertainties, ("Quiz: weight_percent could not be inferred from this source.",))
        self.assertEqual(saved.source_ids, frozenset({"source-1"}))
        self.assertEqual(saved.manifest, "manifest-1")
        self.assertFalse(saved.unchanged)
        self.assertEqual(saved.previous_assessments, ())
        self.assertEqual(dict(saved.previous_versions), {})

    def test_detaches_and_freezes_nested_data(self):
        records = [{"key": "quiz", "evidence": {"week": ["source-1"]}}]
        previous = [{"id": "a-1", "revision": 2, "facts": {"key": "quiz"}}]
        versions = {"a-1": 2}
        saved = checkpoint(records=records, previous_assessments=previous, previous_versions=versions)

        records[0]["evidence"]["week"].append("source-2")
        previous[0]["facts"]["key"] = "exam"
        versions["a-1"] = 3

        self.assertEqual(saved.records[0]["evidence"]["week"], ("source-1",))
        self.assertEqual(saved.previous_assessments[0]["facts"]["key"], "quiz")
        self.assertEqual(saved.previous_versions["a-1"], 2)
        with self.assertRaises(TypeError):
            saved.records[0]["key"] = "exam"
        with self.assertRaises(TypeError):
            saved.previous_versions["a-1"] = 5

    def test_fields_are_immutable(self):
        saved = checkpoint()
        with self.assertRaises(FrozenInstanceError):
            saved.unchanged = True

    def test_rejects_invalid_values(self):
        cases = (
            {"manifest": ""},
            {"manifest": None},
            {"uncertainties": [3]},
            {"source_ids": {1}},
        )
        for changes in cases:
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    checkpoint(**changes)


if __name__ == "__main__":
    unittest.main()
