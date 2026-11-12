"""Immutable view of a project's committed processing state."""

from __future__ import annotations

from dataclasses import dataclass

from src.models.projects.module import Module
from src.models.projects.project import Project


@dataclass(frozen=True)
class ProjectSnapshot:
    """A consistent project view assembled from one committed data snapshot.

    The tuples preserve related records as a single read result, while
    revision_id and event_cursor identify the published revision and the
    latest progress event included in the snapshot.
    """

    project: Project
    modules: tuple[Module, ...]
    assessments: tuple
    issues: tuple
    documents: tuple
    revision_id: int | None
    stale: bool
    event_cursor: int
