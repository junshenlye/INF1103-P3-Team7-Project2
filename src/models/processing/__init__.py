"""Processing lifecycle domain rules and outcome policy."""

from .lifecycle import (
    CREATED,
    FAILED,
    INTERRUPTED,
    PARTIAL,
    PROCESSING,
    READY,
    TERMINAL_STATES,
    can_transition,
    transition_to,
)
from .lifecycle_policy import LifecyclePolicy

__all__ = [
    "CREATED",
    "FAILED",
    "INTERRUPTED",
    "PARTIAL",
    "PROCESSING",
    "READY",
    "TERMINAL_STATES",
    "LifecyclePolicy",
    "can_transition",
    "transition_to",
]
