"""Small structural contracts for dependencies injected into the application."""

from .provider_client import ProviderClient
from .provider_response import ProviderResponse

__all__ = ["ProviderClient", "ProviderResponse"]
