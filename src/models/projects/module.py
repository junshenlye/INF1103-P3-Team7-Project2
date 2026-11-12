"""Value object identifying a module submitted to a project."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Module:
    """A module submitted for processing as part of a project.

    ``normalized_title`` supports duplicate detection within a project, and
    ``position`` preserves the order in which modules were submitted.
    """

    id: str
    project_id: str
    job_id: str
    module_title: str
    normalized_title: str
    credit: int
    position: int
