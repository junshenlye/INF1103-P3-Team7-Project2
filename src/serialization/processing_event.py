"""Encode processing progress for a server-sent event stream."""

import json
from collections.abc import Mapping

from src.models.processing.processing_event import ProcessingEvent


def encode_processing_event(event: ProcessingEvent) -> str:
    """Encode a progress frame from an event with a JSON-compatible payload."""
    data = json.dumps(
        {
            "sequence": event.sequence,
            "kind": event.event_type,
            "payload": event.payload,
        },
        default=_encode_mapping,
        allow_nan=False,
        separators=(",", ":"),
    )
    return f"id: {event.sequence}\nevent: progress\ndata: {data}\n\n"


def _encode_mapping(value: object) -> dict:
    if isinstance(value, Mapping):
        return dict(value)
    raise TypeError(f"Unsupported event payload value: {type(value).__name__}")
