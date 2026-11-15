from __future__ import annotations
from dataclasses import dataclass
from src.models.processing.lifecycle import CREATED


@dataclass(frozen=True, eq=False)
class Project:
    id: str
    name: str
    week_count: int
    status: str = CREATED
    job_id: str | None = None
