"""Tests for the provider transport contracts."""

import asyncio
from contextlib import asynccontextmanager
import unittest

from src.contracts import ProviderClient, ProviderResponse


class FakeResponse:
    def __init__(self, chunks, status=200):
        self._chunks = chunks
        self.status = status

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(f"HTTP {self.status}")
        return self

    async def aiter_bytes(self):
        for chunk in self._chunks:
            yield chunk


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    @asynccontextmanager
    async def stream(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        yield self.response


async def read_limited(client, limit):
    """Read a streamed body the way a bounded provider reader would."""
    body = b""
    async with client.stream("POST", "https://provider.test/v1", json={"q": 1}) as response:
        response.raise_for_status()
        async for chunk in response.aiter_bytes():
            body += chunk
            if len(body) > limit:
                raise ValueError("Response too large.")
    return body


class ProviderContractTests(unittest.TestCase):
    def test_fakes_satisfy_the_contracts(self):
        response = FakeResponse([b"ok"])
        self.assertIsInstance(response, ProviderResponse)
        self.assertIsInstance(FakeClient(response), ProviderClient)

    def test_objects_missing_methods_do_not_satisfy_the_contracts(self):
        self.assertNotIsInstance(object(), ProviderResponse)
        self.assertNotIsInstance(object(), ProviderClient)

        class StatusOnly:
            def raise_for_status(self):
                return None

        self.assertNotIsInstance(StatusOnly(), ProviderResponse)

    def test_contract_supports_bounded_streaming_reads(self):
        client = FakeClient(FakeResponse([b"ab", b"cd"]))
        self.assertEqual(asyncio.run(read_limited(client, 10)), b"abcd")
        self.assertEqual(client.calls, [("POST", "https://provider.test/v1", {"json": {"q": 1}})])
        with self.assertRaises(ValueError):
            asyncio.run(read_limited(FakeClient(FakeResponse([b"abc", b"def"])), 4))

    def test_status_errors_surface_before_the_body_is_read(self):
        with self.assertRaises(RuntimeError):
            asyncio.run(read_limited(FakeClient(FakeResponse([b"x"], status=503)), 10))


if __name__ == "__main__":
    unittest.main()
