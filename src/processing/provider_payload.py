"""Read bounded JSON payloads from external processing services."""

from src.contracts.provider_response import ProviderResponse
from src.errors.error_codes import INVALID_EXTRACTION
from src.errors.processing_error import ProcessingError
from src.serialization.json_data import load_json


async def read_provider_json(response: ProviderResponse, limit: int) -> object:
    """Check the HTTP status, then decode up to limit bytes from the response."""
    response.raise_for_status()
    body = bytearray()
    async for chunk in response.aiter_bytes():
        if len(body) + len(chunk) > limit:
            raise ProcessingError(
                INVALID_EXTRACTION,
                "A processing response exceeds the supported limit.",
                "system",
            )
        body.extend(chunk)

    try:
        return load_json(body)
    except (ValueError, RecursionError) as exc:
        raise ProcessingError(
            INVALID_EXTRACTION,
            "A processing service returned invalid data.",
            "system",
        ) from exc
