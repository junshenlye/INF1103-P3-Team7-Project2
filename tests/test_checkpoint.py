"""Tests for immutable document processing checkpoints."""

import unittest
from dataclasses import FrozenInstanceError

from src.models.documents.source_element import SourceElement
from src.models.processing.checkpoint import DocumentCheckpoint


class DocumentCheckpointTests(unittest.TestCase):
    def element(self):
        return SourceElement(
            id="element-1",
            document_id="document-1",
            parse_id="parse-1",
            text="Assessment due in week 4",
            regions=[{"page": 1, "x": 0.1}],
            context="Assessment",
        )

    def test_captures_parse_and_chunk_metadata(self):
        element = self.element()
        checkpoint = DocumentCheckpoint(
            parse_id="parse-1",
            elements=[element],
            chunks={"chunk-1": {"records": [{"name": "Quiz"}]}},
            chunk_bytes=128,
            chunk_count=1,
        )

        self.assertEqual(checkpoint.parse_id, "parse-1")
        self.assertEqual(len(checkpoint.elements), 1)
        self.assertEqual(checkpoint.elements[0].text, element.text)
        self.assertEqual(checkpoint.chunks["chunk-1"]["records"][0]["name"], "Quiz")
        self.assertEqual((checkpoint.chunk_bytes, checkpoint.chunk_count), (128, 1))

    def test_detaches_and_freezes_nested_chunk_and_source_data(self):
        payload = {"chunk-1": {"records": [{"name": "Quiz"}]}}
        element = self.element()
        checkpoint = DocumentCheckpoint("parse-1", [element], payload, 32, 1)

        payload["chunk-1"]["records"][0]["name"] = "Changed"
        element.regions[0]["page"] = 2

        self.assertEqual(checkpoint.chunks["chunk-1"]["records"][0]["name"], "Quiz")
        self.assertEqual(checkpoint.elements[0].regions[0]["page"], 1)
        with self.assertRaises(TypeError):
            checkpoint.chunks["chunk-1"]["records"][0]["name"] = "Changed"
        with self.assertRaises(TypeError):
            checkpoint.elements[0].regions[0]["page"] = 3

    def test_normalizes_elements_to_a_tuple(self):
        elements = [self.element()]
        checkpoint = DocumentCheckpoint("parse-1", elements, {}, 0, 0)
        elements.clear()

        self.assertEqual(len(checkpoint.elements), 1)
        self.assertIsInstance(checkpoint.elements, tuple)

    def test_checkpoint_fields_are_immutable(self):
        checkpoint = DocumentCheckpoint("parse-1", (), {}, 0, 0)
        with self.assertRaises(FrozenInstanceError):
            checkpoint.chunk_count = 2

    def test_rejects_negative_chunk_metadata(self):
        for chunk_bytes, chunk_count in ((-1, 0), (0, -1)):
            with self.subTest(chunk_bytes=chunk_bytes, chunk_count=chunk_count):
                with self.assertRaises(ValueError):
                    DocumentCheckpoint("parse-1", (), {}, chunk_bytes, chunk_count)


if __name__ == "__main__":
    unittest.main()
