"""Identify supported upload formats from their signature and filename."""

from pathlib import PurePath

from src.config import limits
from src.errors.error_codes import INVALID_DOCUMENT
from src.errors.processing_error import ProcessingError


_FORMATS = (
    (b"%PDF-", (".pdf",), limits.MEDIA_TYPE_PDF),
    (b"\x89PNG\r\n\x1a\n", (".png",), limits.MEDIA_TYPE_PNG),
    (b"\xff\xd8\xff", (".jpg", ".jpeg"), limits.MEDIA_TYPE_JPEG),
)


def identify_upload_format(filename: str, header: bytes) -> tuple[str, str]:
    """Return the media type and canonical suffix before full file validation.

    Pass the first eight bytes of the staged upload, or the whole file if
    shorter. A matching signature does not guarantee the file is readable.
    """
    suffix = PurePath(filename).suffix.lower()
    for signature, suffixes, media_type in _FORMATS:
        if header.startswith(signature) and suffix in suffixes:
            return media_type, suffixes[0]

    raise ProcessingError(
        INVALID_DOCUMENT,
        "Upload a readable PDF, PNG or JPEG with a matching filename.",
        "document",
    )
