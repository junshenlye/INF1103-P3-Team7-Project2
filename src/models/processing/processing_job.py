"""Value object representing a queued project-processing job."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProcessingJob:
    """Identifies a single processing attempt for a submitted project.

    ``submission_key`` makes a submission safe to retry at the API boundary,
    while ``lease_token`` is reserved for a worker that has claimed the job.
    The model intentionally contains no storage or queue concerns.
    """

    id: str
    project_id: str
    submission_key: str
    status: str
    stage: str
    lease_token: str | None = None
