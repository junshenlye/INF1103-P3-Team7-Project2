from typing import AsyncContextManager, Protocol, runtime_checkable

from httpx import Response


@runtime_checkable
class ProviderClient(Protocol):
    """Only streaming transport is required; AIManager owns every payload."""

    def stream(
        self, method: str, url: str, **kwargs
    ) -> AsyncContextManager[Response]: ...
