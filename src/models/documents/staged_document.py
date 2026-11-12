"""Upload record for a document that is still being received."""

from dataclasses import dataclass


@dataclass
class StagedDocument:
    """Track an upload between its first byte and its final storage location.

    The record is deliberately mutable: ``size`` grows as chunks arrive, and
    ``media_type``, ``checksum`` and ``final_key`` are only known once the
    upload is complete and verified.
    """

    request_id: str
    document_id: str
    filename: str
    staging_key: str
    final_key: str = ""
    media_type: str = ""
    size: int = 0
    checksum: str = ""
