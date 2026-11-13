"""Open a stored original only after checking its recorded integrity."""

import hashlib
import os
import stat
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator

from src.config.limits import STREAM_CHUNK_BYTES
from src.errors.error_codes import SOURCE_MISSING
from src.errors.processing_error import ProcessingError
from src.models.documents.document import Document
from src.storage.document_keys import resolve_document_key


@contextmanager
def open_verified_document(root: Path, document: Document) -> Iterator[BinaryIO]:
    """Yield the verified original at byte zero and close it on exit."""
    try:
        path = resolve_document_key(root, document.storage_key)
        if not path.is_file():
            raise OSError("Original is not a regular file.")
        stream = path.open("rb")
    except (OSError, ProcessingError) as exc:
        raise _source_missing(document) from exc

    with stream:
        try:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size != document.size:
                raise OSError("Original has an unexpected type or size.")

            digest = hashlib.sha256()
            size = 0
            for chunk in iter(lambda: stream.read(STREAM_CHUNK_BYTES), b""):
                size += len(chunk)
                if size > document.size:
                    raise OSError("Original has an unexpected size.")
                digest.update(chunk)

            if size != document.size or digest.hexdigest() != document.checksum:
                raise OSError("Original failed integrity verification.")
            stream.seek(0)
        except OSError as exc:
            raise _source_missing(document) from exc

        yield stream


def _source_missing(document: Document) -> ProcessingError:
    return ProcessingError(
        SOURCE_MISSING,
        "The original document is unavailable.",
        "document",
        document_id=document.id,
        module_id=document.module_id,
    )
