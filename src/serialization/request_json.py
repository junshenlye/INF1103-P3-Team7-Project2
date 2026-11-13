"""Read JSON request bodies within the application's byte limit."""

from typing import AsyncIterable

from src.config.limits import JSON_BYTES
from src.errors import error_codes
from src.errors.processing_error import ProcessingError
from src.serialization.json_data import load_json


async def read_request_json(content_type: str, chunks: AsyncIterable[bytes]) -> object:
    """Decode a streamed application/json request using the shared strict decoder."""
    media_type = content_type.partition(";")[0].strip().lower()
    if media_type != "application/json":
        raise ProcessingError(
            error_codes.INVALID_REQUEST, "Send project and review requests as JSON."
        )

    body = bytearray()
    async for chunk in chunks:
        if len(body) + len(chunk) > JSON_BYTES:
            raise ProcessingError(
                error_codes.REQUEST_TOO_LARGE, "JSON exceeds the supported limit."
            )
        body.extend(chunk)

    try:
        return load_json(body)
    except (ValueError, RecursionError) as exc:
        raise ProcessingError(
            error_codes.INVALID_REQUEST, "Provide valid JSON without duplicate keys."
        ) from exc
