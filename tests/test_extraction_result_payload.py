"""Tests for decoding assessment results from completion responses."""

import unittest

from src.errors.error_codes import INVALID_EXTRACTION
from src.errors.processing_error import ProcessingError
from src.processing.extraction_result_payload import decode_extraction_result


def completion(content, *, finish_reason="stop", refusal=None):
    return {
        "choices": [
            {
                "finish_reason": finish_reason,
                "message": {"content": content, "refusal": refusal},
            }
        ]
    }


class ExtractionResultPayloadTests(unittest.TestCase):
    def test_decodes_a_complete_result_object(self):
        response = completion('{"module_title":"INF1103","assessments":[],"uncertainties":[]}')
        self.assertEqual(
            decode_extraction_result(response),
            {"module_title": "INF1103", "assessments": [], "uncertainties": []},
        )

    def test_rejects_incomplete_and_refused_completions(self):
        for response in (
            completion("{}", finish_reason="length"),
            completion("{}", refusal="private refusal reason"),
        ):
            with self.subTest(response=response):
                with self.assertRaises(ProcessingError) as caught:
                    decode_extraction_result(response)
                self.assertEqual(caught.exception.code, INVALID_EXTRACTION)
                self.assertEqual(caught.exception.scope, "module")
                self.assertNotIn("private", str(caught.exception))

    def test_rejects_malformed_envelopes_and_invalid_json_objects(self):
        for response in (
            None,
            {"choices": []},
            {"choices": {"0": {}}},
            {"choices": ["not a choice"]},
            {"choices": [{"finish_reason": "stop", "message": []}]},
            completion(None),
            completion("[]"),
            completion('{"duplicate":1,"duplicate":2}'),
            completion("{"),
        ):
            with self.subTest(response=response):
                with self.assertRaises(ProcessingError) as caught:
                    decode_extraction_result(response)
                self.assertEqual(caught.exception.code, INVALID_EXTRACTION)
