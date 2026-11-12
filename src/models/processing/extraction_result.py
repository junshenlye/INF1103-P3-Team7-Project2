"""Immutable published result of extracting one module's assessment facts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .frozen_data import freeze


@dataclass(frozen=True)
class ExtractionResult:
    """Connect a processed module to its assessments, uncertainties and metrics."""

    id: str
    job_id: str
    module_id: str
    assessment_ids: tuple[str, ...]
    uncertainties: tuple
    metrics: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "assessment_ids", tuple(self.assessment_ids))
        object.__setattr__(self, "uncertainties", tuple(freeze(self.uncertainties)))
        object.__setattr__(self, "metrics", freeze(self.metrics))
