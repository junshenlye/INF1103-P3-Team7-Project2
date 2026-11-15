from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True, eq=False)
class ProcessingJob:
    id: str
    project_id: str
    submission_key: str
    status: str
    stage: str
    lease_token: str | None = None
