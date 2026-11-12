"""Evidence-backed assessment corrections carried to a new result."""

from dataclasses import dataclass
from typing import Mapping

from .frozen_data import freeze


@dataclass(frozen=True)
class ReviewTransfer:
    """Link corrected facts and their evidence to the assessment revision they came from."""

    key: str
    previous_assessment_id: str
    revision: int
    facts: Mapping[str, object]
    evidence: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "facts", freeze(self.facts))
        object.__setattr__(self, "evidence", freeze(self.evidence))
