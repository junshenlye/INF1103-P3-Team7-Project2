"""Immutable event records for replayable project-processing progress."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .frozen_data import freeze


@dataclass(frozen=True)
class ProcessingEvent:
    """One sequenced processing event included in a project event stream.

    The sequence is the project-scoped cursor used to resume event replay.
    The payload is recursively detached and frozen so a stored event cannot
    be changed by mutating the caller's original dictionaries or lists.
    """

    sequence: int
    event_type: str
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int):
            raise TypeError("sequence must be an integer.")
        if self.sequence < 1:
            raise ValueError("sequence must be positive.")
        if not isinstance(self.event_type, str) or not self.event_type.strip():
            raise ValueError("event_type must be a nonempty string.")
        if not isinstance(self.payload, Mapping):
            raise TypeError("payload must be a mapping.")
        if any(not isinstance(key, str) or not key for key in self.payload):
            raise ValueError("payload keys must be nonempty strings.")

        object.__setattr__(self, "event_type", self.event_type.strip())
        object.__setattr__(self, "payload", freeze(self.payload))
