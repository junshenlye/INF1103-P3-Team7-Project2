"""Immutable record of a reviewed assessment carried into a new result."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .frozen_data import freeze


@dataclass(frozen=True)
class ReviewTransfer:
    """Preserve a reviewed correction and its lineage across result revisions."""

    key: str
    previous_assessment_id: str
    revision: int
    facts: Mapping[str, object]
    evidence: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "facts", freeze(self.facts))
        object.__setattr__(self, "evidence", freeze(self.evidence))
        if self.revision < 0:
            raise ValueError("revision cannot be negative.")
