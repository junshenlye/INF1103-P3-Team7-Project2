"""Response body describing a project and its current schedule."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProjectResponse:
    """A project, its modules and schedule, and how complete the result is.

    The defaults describe a project that has not been processed yet: no
    coverage, no published revision and no progress events.
    """

    id: str
    name: str
    week_count: int
    status: str
    job_id: str | None
    modules: list
    schedule: dict | None
    issues: list
    processing_status: str = "idle"
    coverage: str = "none"
    documents: list | None = None
    schedule_revision_id: int | None = None
    stale: bool = False
    event_cursor: int = 0
