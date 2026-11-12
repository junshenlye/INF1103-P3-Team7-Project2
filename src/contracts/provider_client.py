"""Structural contract for the HTTP client used to call external providers."""

from typing import AsyncContextManager, Protocol, runtime_checkable

from src.contracts.provider_response import ProviderResponse


@runtime_checkable
class ProviderClient(Protocol):
    """Only streaming transport is required; callers own every payload.

    Any client with a compatible ``stream`` method satisfies this contract,
    so a real HTTP client and a test double can be injected the same way.
    """

    def stream(self, method: str, url: str, **kwargs) -> AsyncContextManager[ProviderResponse]: ...
