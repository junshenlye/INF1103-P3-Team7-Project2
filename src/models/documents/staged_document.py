"""Upload record for a document that is still being received."""

from dataclasses import dataclass

from src.config.limits import DOCUMENT_NAME_LENGTH


@dataclass
class StagedDocument:
    """Track an upload between its first byte and its final storage location.

    The record is deliberately mutable: ``size`` grows as chunks arrive, and
    ``media_type``, ``checksum`` and ``final_key`` are only known once the
    upload is complete and verified. The initial filename is normalized
    for display and format checks. Storage uses the separate key fields.
    """

    request_id: str
    document_id: str
    filename: str
    staging_key: str
    final_key: str = ""
    media_type: str = ""
    size: int = 0
    checksum: str = ""

    def __post_init__(self) -> None:
        basename = self.filename.replace("\\", "/").rsplit("/", 1)[-1]
        filename = "".join(char for char in basename if char.isprintable()).strip()
        if filename in {"", ".", ".."}:
            self.filename = "document"
            return

        # Keep the extension available for upload format checks after shortening.
        stem, dot, extension = filename.rpartition(".")
        suffix = dot + extension
        if stem and dot and len(suffix) < DOCUMENT_NAME_LENGTH:
            self.filename = stem[: DOCUMENT_NAME_LENGTH - len(suffix)] + suffix
        else:
            self.filename = filename[:DOCUMENT_NAME_LENGTH]
