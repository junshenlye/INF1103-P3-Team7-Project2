"""Immutable input snapshot accepted for one project processing job."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from src.models.projects.module import Module

from .frozen_data import freeze


@dataclass(frozen=True)
class SubmissionSnapshot:
    """Preserve one idempotent submission's modules and document field values."""

    project_id: str
    submission_key: str
    modules: tuple[Module, ...]
    document_fields: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "modules", tuple(self.modules))
        object.__setattr__(self, "document_fields", freeze(self.document_fields))
