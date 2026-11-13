import json
import unittest

from src.models.processing.processing_event import ProcessingEvent
from src.serialization.processing_event import encode_processing_event


class ProcessingEventSerializationTests(unittest.TestCase):
    def test_encodes_replay_id_and_nested_payload_in_one_frame(self):
        payload = {"documents": [{"label": "文書\nevent: unexpected"}]}
        event = ProcessingEvent(7, "document.completed", payload)
        event_id, event_name, data, end = encode_processing_event(event).split("\n", 3)
        self.assertEqual(event_id, "id: 7")
        self.assertEqual(event_name, "event: progress")
        self.assertEqual(end, "\n")
        self.assertEqual(
            json.loads(data.removeprefix("data: ")),
            {"sequence": 7, "kind": "document.completed", "payload": payload},
        )

    def test_rejects_values_that_cannot_be_encoded_as_json(self):
        with self.assertRaises(ValueError):
            encode_processing_event(ProcessingEvent(1, "progress", {"value": float("nan")}))
        with self.assertRaises(TypeError):
            encode_processing_event(ProcessingEvent(1, "progress", {"value": b"bytes"}))
