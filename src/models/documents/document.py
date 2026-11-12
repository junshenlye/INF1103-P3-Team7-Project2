"""Metadata for an uploaded document stored by Stackplan."""

from dataclasses import dataclass

from src.models.documents.document_reference import DocumentReference


@dataclass(frozen=True)
class Document:
    """Identify an original upload and its location in storage."""

    id: str
    module_id: str
    filename: str
    media_type: str
    size: int
    checksum: str
    storage_key: str

    def to_reference(self) -> DocumentReference:
        """Return processing metadata without the internal storage key."""
        return DocumentReference(
            id=self.id,
            module_id=self.module_id,
            filename=self.filename,
            media_type=self.media_type,
            size=self.size,
            checksum=self.checksum,
        )
