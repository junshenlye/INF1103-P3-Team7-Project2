"""Validate the cursor used to resume a project event stream."""

from __future__ import annotations

from src.errors.error_codes import INVALID_REQUEST
from src.errors.processing_error import ProcessingError


def parse_event_cursor(after: int = 0, *, last_event_id: str | None = None) -> int:
    """Use the Last-Event-ID header when supplied, otherwise use the query cursor."""
    if last_event_id is not None:
        if (
            isinstance(last_event_id, str)
            and 1 <= len(last_event_id) <= 18
            and last_event_id.isascii()
            and last_event_id.isdecimal()
        ):
            return int(last_event_id)
    elif type(after) is int and 0 <= after < 10**18:
        return after

    raise ProcessingError(INVALID_REQUEST, "Use a nonnegative event cursor.")
