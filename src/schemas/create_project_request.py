"""Validated input for creating a project."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CreateProjectRequest:
    """A project name and teaching-week count that have passed validation."""

    name: str
    week_count: int
