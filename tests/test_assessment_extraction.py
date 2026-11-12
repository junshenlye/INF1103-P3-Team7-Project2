"""Tests for schema-constrained assessment extraction requests."""

import json
import unittest
from contextlib import asynccontextmanager

from src.config import limits
from src.errors.error_codes import DOCUMENT_PARSE_FAILED, INVALID_EXTRACTION, PROVIDER_UNAVAILABLE
from src.errors.processing_error import ProcessingError
from src.models.documents.source_element import SourceElement
from src.processing.assessment_extraction import extract_assessment_chunk


class FakeProvider:
    def __init__(self, *, finish_reason="stop"):
        self.calls = []
        self.finish_reason = finish_reason
        self.closed = False

    @asynccontextmanager
    async def stream(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        try:
            yield self
        finally:
            self.closed = True

    def raise_for_status(self):
        pass

    async def aiter_bytes(self):
        message = {"content": '{"module_title":"M","assessments":[],"uncertainties":[]}'}
        body = {"choices": [{"finish_reason": self.finish_reason, "message": message}]}
        yield json.dumps(body).encode()


class AssessmentExtractionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.element = SourceElement("source-1", "document", "parse", "课程", [], "paragraph")
        self.settings = {"model": "test-model", "api_key": "test-key", "module_title": "M"}

    async def test_sends_one_strict_request_and_decodes_the_result(self):
        client = FakeProvider()
        result = await extract_assessment_chunk(
            client, **self.settings, chunk=iter([self.element]), feedback="Check the week."
        )

        self.assertEqual(result, {"module_title": "M", "assessments": [], "uncertainties": []})
        self.assertTrue(client.closed)
        self.assertEqual(len(client.calls), 1)
        method, path, request = client.calls[0]
        self.assertEqual((method, path), ("POST", "/chat/completions"))
        self.assertEqual(request["headers"], {"Authorization": "Bearer test-key"})
        payload = request["json"]
        self.assertEqual(payload["model"], "test-model")
        self.assertEqual(payload["max_completion_tokens"], limits.GPT_COMPLETION_TOKENS)
        self.assertTrue(payload["response_format"]["json_schema"]["strict"])
        schema = payload["response_format"]["json_schema"]["schema"]
        self.assertEqual(schema["$defs"]["source_id"]["enum"], ["source-1"])
        system, user = payload["messages"]
        self.assertEqual((system["role"], user["role"]), ("system", "user"))
        self.assertNotIn("Check the week.", system["content"])
        data = json.loads(user["content"])
        self.assertEqual(data["source_elements"][0]["text"], "课程")
        self.assertEqual(data["validation_feedback"], "Check the week.")
        self.assertNotIn("test-key", json.dumps(payload))

    async def test_rejects_an_empty_chunk_or_missing_credentials_before_calling_provider(self):
        client = FakeProvider()
        with self.assertRaises(ProcessingError) as empty:
            await extract_assessment_chunk(client, **self.settings, chunk=[])
        self.assertEqual(empty.exception.code, DOCUMENT_PARSE_FAILED)

        with self.assertRaises(ProcessingError) as unconfigured:
            await extract_assessment_chunk(
                client, **{**self.settings, "api_key": ""}, chunk=[self.element]
            )
        self.assertEqual(unconfigured.exception.code, PROVIDER_UNAVAILABLE)
        self.assertEqual(client.calls, [])

    async def test_propagates_incomplete_result_and_closes_the_response(self):
        client = FakeProvider(finish_reason="length")
        with self.assertRaises(ProcessingError) as caught:
            await extract_assessment_chunk(client, **self.settings, chunk=[self.element])
        self.assertEqual(caught.exception.code, INVALID_EXTRACTION)
        self.assertTrue(client.closed)
        self.assertEqual(len(client.calls), 1)
