"""Allowed project-processing lifecycle transitions.

Keeping this rule in the domain layer lets HTTP handlers, workers, and future
persistence adapters agree on which states can follow one another.
"""

from __future__ import annotations

from types import MappingProxyType

CREATED = "Created"
PROCESSING = "Processing"
READY = "Ready"
PARTIAL = "Partial"
FAILED = "Failed"
INTERRUPTED = "Interrupted"

TERMINAL_STATES = frozenset({READY, PARTIAL, FAILED, INTERRUPTED})

# Execution status of a processing job before it settles into a terminal state.
QUEUED = "queued"
RUNNING = "running"

# Stages reported while a job or document is being worked on.
PARSING = "parsing"
EXTRACTING = "extracting"
VALIDATING = "validating"
EXTRACTED = "extracted"

# Stage recorded when a job settles, keyed by its terminal status.
TERMINAL_STAGES = MappingProxyType(
    {
        READY: "complete",
        PARTIAL: "complete",
        FAILED: "failed",
        INTERRUPTED: "interrupted",
    }
)
JOB_STAGES = frozenset({QUEUED, PARSING, EXTRACTING, VALIDATING, *TERMINAL_STAGES.values()})

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


def terminal_stage(status: str) -> str:
    """Return the job stage to record when a job settles with ``status``.

    Raises:
        ValueError: If ``status`` is not a terminal status.
    """
    try:
        return TERMINAL_STAGES[status]
    except KeyError:
        raise ValueError(f"{status!r} is not a terminal processing status.") from None
