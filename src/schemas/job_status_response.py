"""Response body describing a processing job."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class JobStatusResponse:
    """A job's lifecycle status, current stage, issues and progress counts."""

    id: str
    project_id: str
    status: str
    stage: str
    issues: list
    progress: dict
