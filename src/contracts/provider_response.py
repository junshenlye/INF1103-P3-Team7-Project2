"""Structural contract for a streamed provider HTTP response."""

from typing import AsyncIterator, Protocol, runtime_checkable


@runtime_checkable
class ProviderResponse(Protocol):
    """A response whose status can be checked and whose body is read in chunks.

    Reading the body as a stream lets callers stop once a size limit is
    reached instead of loading an unbounded response into memory.
    """

    def raise_for_status(self) -> object: ...

    def aiter_bytes(self) -> AsyncIterator[bytes]: ...
