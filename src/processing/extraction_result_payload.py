"""Decode the assessment result carried by a completion response."""

from src.errors.error_codes import INVALID_EXTRACTION
from src.errors.processing_error import ProcessingError
from src.serialization.json_data import load_json


def decode_extraction_result(response: object) -> dict:
    """Return the first complete, non-refused extraction as a JSON object."""
    try:
        choices = response.get("choices") if isinstance(response, dict) else None
        if not isinstance(choices, list) or not choices:
            raise ValueError("Missing completion choice.")
        choice = choices[0]
        if not isinstance(choice, dict) or choice.get("finish_reason") != "stop":
            raise ValueError("Incomplete completion.")

        message = choice.get("message")
        if not isinstance(message, dict) or message.get("refusal"):
            raise ValueError("Missing or refused completion message.")
        content = message.get("content")
        if not isinstance(content, str):
            raise ValueError("Expected JSON text in the completion message.")
        result = load_json(content)
        if not isinstance(result, dict):
            raise ValueError("Expected an extraction result object.")
        return result
    except (ValueError, RecursionError) as exc:
        raise ProcessingError(
            INVALID_EXTRACTION,
            "The extraction service returned an incomplete or invalid result.",
            "module",
        ) from exc
