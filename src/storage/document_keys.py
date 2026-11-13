"""Resolve internal document keys within the configured storage root."""

from pathlib import Path

from src.errors.error_codes import INVALID_STORAGE_KEY
from src.errors.processing_error import ProcessingError


_STORAGE_DIRECTORIES = frozenset({".staging", "originals", "generated"})


def resolve_document_key(root: Path, key: str) -> Path:
    """Resolve a slash-separated storage key for an existing or future path."""
    error = ProcessingError(
        INVALID_STORAGE_KEY,
        "The document reference is unavailable.",
        "document",
    )
    if not isinstance(key, str) or any(char in key for char in "\\:\x00"):
        raise error

    parts = key.split("/")
    if parts[0] not in _STORAGE_DIRECTORIES or any(
        part in {"", ".", ".."} for part in parts
    ):
        raise error

    try:
        resolved_root = root.resolve()
        path = resolved_root.joinpath(*parts).resolve()
    except (OSError, RuntimeError) as exc:
        raise error from exc

    if not path.is_relative_to(resolved_root):
        raise error
    return path
