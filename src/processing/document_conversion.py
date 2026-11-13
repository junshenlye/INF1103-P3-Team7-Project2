"""Convert one uploaded document through the document parsing provider."""

from typing import BinaryIO

from src.config import limits
from src.contracts.provider_client import ProviderClient
from src.errors.error_codes import DOCUMENT_PARSE_FAILED
from src.errors.processing_error import ProcessingError
from src.models.documents.document_reference import DocumentReference
from src.processing.provider_payload import read_provider_json


async def convert_document(
    client: ProviderClient, stream: BinaryIO, document: DocumentReference
) -> dict:
    """Send the document to Docling and return a complete parsed JSON object."""
    extension = document.media_type.split("/")[-1]
    async with client.stream(
        "POST",
        "/v1/convert/file",
        files={"files": (f"document.{extension}", stream, document.media_type)},
        data={"to_formats": "json", "image_export_mode": "placeholder", "do_ocr": "true"},
    ) as response:
        payload = await read_provider_json(response, limits.DOCLING_RESPONSE_BYTES)

    if not isinstance(payload, dict) or payload.get("status") != "success":
        raise ProcessingError(
            DOCUMENT_PARSE_FAILED,
            "The document could not be completely parsed.",
            "document",
            document_id=document.id,
        )

    converted = payload.get("document")
    parsed = converted.get("json_content") if isinstance(converted, dict) else None
    if not isinstance(parsed, dict):
        raise ProcessingError(
            DOCUMENT_PARSE_FAILED,
            "The document could not be parsed.",
            "document",
            document_id=document.id,
        )
    return parsed
