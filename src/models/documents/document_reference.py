"""Document metadata passed to processing code."""

from dataclasses import dataclass


@dataclass(frozen=True)
class DocumentReference:
    """Identify an upload without exposing its storage location."""

    id: str
    module_id: str
    filename: str
    media_type: str
    size: int
    checksum: str
