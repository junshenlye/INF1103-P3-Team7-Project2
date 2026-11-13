"""Tests for the document conversion provider request and response."""

import json
import unittest
from contextlib import asynccontextmanager
from io import BytesIO
from unittest.mock import patch

from src.config import limits
from src.errors.error_codes import DOCUMENT_PARSE_FAILED, INVALID_EXTRACTION
from src.errors.processing_error import ProcessingError
from src.models.documents.document_reference import DocumentReference
from src.processing.document_conversion import convert_document


class FakeDocling:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []
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
        yield json.dumps(self.payload).encode()


class DocumentConversionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.document = DocumentReference(
            "doc-1", "module", "private-original.pdf", "application/pdf", 3, "checksum"
        )
        self.stream = BytesIO(b"pdf")
        self.addCleanup(self.stream.close)

    async def test_submits_document_and_returns_parsed_json(self):
        parsed = {"texts": [{"text": "Quiz in week 5"}]}
        client = FakeDocling({"status": "success", "document": {"json_content": parsed}})

        self.assertEqual(await convert_document(client, self.stream, self.document), parsed)
        self.assertTrue(client.closed)
        self.assertEqual(
            client.calls,
            [
                (
                    "POST",
                    "/v1/convert/file",
                    {
                        "files": {"files": ("document.pdf", self.stream, "application/pdf")},
                        "data": {
                            "to_formats": "json",
                            "image_export_mode": "placeholder",
                            "do_ocr": "true",
                        },
                    },
                )
            ],
        )

    async def test_rejects_partial_and_malformed_conversion_results(self):
        for payload in (
            {"status": "partial_success", "document": {"json_content": {}}},
            {"status": "success", "document": None},
            {"status": "success", "document": {"json_content": []}},
        ):
            with self.subTest(payload=payload):
                client = FakeDocling(payload)
                with self.assertRaises(ProcessingError) as caught:
                    await convert_document(client, self.stream, self.document)
                self.assertEqual(caught.exception.code, DOCUMENT_PARSE_FAILED)
                self.assertEqual(caught.exception.scope, "document")
                self.assertEqual(caught.exception.related_ids, {"document_id": "doc-1"})
                self.assertTrue(client.closed)

    async def test_enforces_the_response_byte_limit(self):
        client = FakeDocling({"status": "success", "document": {"json_content": {}}})
        with patch.object(limits, "DOCLING_RESPONSE_BYTES", 8):
            with self.assertRaises(ProcessingError) as caught:
                await convert_document(client, self.stream, self.document)
        self.assertEqual(caught.exception.code, INVALID_EXTRACTION)
        self.assertTrue(client.closed)
