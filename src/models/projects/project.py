"""Value object identifying a trimester planning project."""

from __future__ import annotations

from dataclasses import dataclass

from src.models.processing.lifecycle import CREATED


@dataclass(frozen=True)
class Project:
    """A named trimester whose submitted modules are processed together.

    A new project starts in the ``Created`` lifecycle state and has no job
    until its modules are submitted. Storage and HTTP concerns stay outside
    this model.
    """

    id: str
    name: str
    week_count: int
    status: str = CREATED
    job_id: str | None = None
