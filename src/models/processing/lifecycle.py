"""Allowed project-processing lifecycle transitions.

Keeping this rule in the domain layer lets HTTP handlers, workers, and future
persistence adapters agree on which states can follow one another.
"""

from __future__ import annotations

CREATED = "Created"
PROCESSING = "Processing"
READY = "Ready"
FAILED = "Failed"
INTERRUPTED = "Interrupted"

TERMINAL_STATES = frozenset({READY, FAILED, INTERRUPTED})

_ALLOWED_TRANSITIONS = {
    CREATED: frozenset({PROCESSING}),
    PROCESSING: TERMINAL_STATES,
}


def can_transition(current: str, next_status: str) -> bool:
    """Return whether a project may move from ``current`` to ``next_status``."""
    return next_status in _ALLOWED_TRANSITIONS.get(current, frozenset())


def transition_to(current: str, next_status: str) -> str:
    """Validate and return the next lifecycle status.

    Raises:
        ValueError: If the requested transition is not part of the lifecycle.
    """
    if not can_transition(current, next_status):
        raise ValueError(
            f"Cannot transition project processing from {current!r} to {next_status!r}."
        )
    return next_status
