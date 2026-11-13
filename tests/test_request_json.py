"""Tests for streamed JSON request validation."""

import unittest
from unittest.mock import patch

from src.errors import error_codes
from src.errors.processing_error import ProcessingError
from src.serialization.request_json import read_request_json


async def stream(*chunks):
    for chunk in chunks:
        yield chunk


class RequestJsonTests(unittest.IsolatedAsyncioTestCase):
    async def test_accepts_media_type_parameters_and_split_utf8_at_the_limit(self):
        body = '"课"'.encode("utf-8")
        with patch("src.serialization.request_json.JSON_BYTES", len(body)):
            result = await read_request_json(
                "Application/JSON; charset=utf-8", stream(body[:2], body[2:])
            )
        self.assertEqual(result, "课")

    async def test_rejects_unsupported_media_types_before_reading(self):
        async def unread():
            self.fail("The request body must not be read for unsupported media types.")
            yield b"{}"

        for media_type in ("", "text/plain", "application/jsonp"):
            with self.subTest(media_type=media_type):
                with self.assertRaises(ProcessingError) as caught:
                    await read_request_json(media_type, unread())
                self.assertEqual(caught.exception.code, error_codes.INVALID_REQUEST)

    async def test_stops_reading_when_the_cumulative_limit_is_exceeded(self):
        async def oversized():
            yield b'{"a":'
            yield b"123}"
            self.fail("The request body must not be read past the limit.")

        with patch("src.serialization.request_json.JSON_BYTES", 8):
            with self.assertRaises(ProcessingError) as caught:
                await read_request_json("application/json", oversized())
        self.assertEqual(caught.exception.code, error_codes.REQUEST_TOO_LARGE)

    async def test_rejects_ambiguous_or_malformed_json(self):
        for body in (b'{"a": 1, "a": 2}', b'{"a": NaN}', b"\xff", b""):
            with self.subTest(body=body):
                with self.assertRaises(ProcessingError) as caught:
                    await read_request_json("application/json", stream(body))
                self.assertEqual(caught.exception.code, error_codes.INVALID_REQUEST)
