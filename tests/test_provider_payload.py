"""Tests for streamed provider payload bounds and error handling."""

import unittest

from src.errors.error_codes import INVALID_EXTRACTION
from src.errors.processing_error import ProcessingError
from src.processing.provider_payload import read_provider_json


class FakeResponse:
    def __init__(self, chunks, status_error=None):
        self.chunks = chunks
        self.status_error = status_error
        self.chunks_read = 0

    def raise_for_status(self):
        if self.status_error is not None:
            raise self.status_error

    async def aiter_bytes(self):
        for chunk in self.chunks:
            self.chunks_read += 1
            yield chunk


class ProviderPayloadTests(unittest.IsolatedAsyncioTestCase):
    async def test_decodes_utf8_split_across_chunks_at_the_exact_limit(self):
        payload = '{"source": "课程"}'.encode("utf-8")
        split = payload.index("课".encode("utf-8")) + 1
        response = FakeResponse([payload[:split], payload[split:]])

        self.assertEqual(await read_provider_json(response, len(payload)), {"source": "课程"})

    async def test_stops_reading_when_the_cumulative_limit_is_exceeded(self):
        response = FakeResponse([b'{"a":', b"123}", b"unread"])

        with self.assertRaisesRegex(ProcessingError, "exceeds the supported limit") as caught:
            await read_provider_json(response, 8)

        self.assertEqual(caught.exception.code, INVALID_EXTRACTION)
        self.assertEqual(caught.exception.scope, "system")
        self.assertEqual(response.chunks_read, 2)

    async def test_rejects_invalid_json_without_exposing_the_payload(self):
        for payload in (b'{"private_value":', b'{"a": 1, "a": 2}', b'{"a": NaN}', b"\xff"):
            with self.subTest(payload=payload):
                with self.assertRaises(ProcessingError) as caught:
                    await read_provider_json(FakeResponse([payload]), 100)
                self.assertEqual(caught.exception.code, INVALID_EXTRACTION)
                self.assertEqual(str(caught.exception), "A processing service returned invalid data.")

    async def test_checks_http_status_before_reading_the_body(self):
        error = RuntimeError("provider status")
        response = FakeResponse([b"{}"], status_error=error)

        with self.assertRaises(RuntimeError) as caught:
            await read_provider_json(response, 100)

        self.assertIs(caught.exception, error)
        self.assertEqual(response.chunks_read, 0)
