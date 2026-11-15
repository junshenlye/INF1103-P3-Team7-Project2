"""Assessment facts shared by individual tasks and non-scheduled group totals."""
from __future__ import annotations

from abc import ABC, abstractmethod
from copy import deepcopy
from dataclasses import dataclass


@dataclass(frozen=True, eq=False)
class Assessment(ABC):
    id: str
    result_id: str
    module_id: str
    _facts: dict
    _evidence: dict
    parent_assessment_id: str | None = None
    revision: int = 0

    def __post_init__(self):
        object.__setattr__(self, '_facts', deepcopy(self._facts))
        object.__setattr__(self, '_evidence', deepcopy(self._evidence))

    @property
    def facts(self):
        return deepcopy(self._facts)

    @property
    def evidence(self):
        return deepcopy(self._evidence)

    def to_record(self, module_title):
        """Return a detached display record; editing it cannot change saved facts."""
        return {
            "assessment_id": self.id,
            "result_id": self.result_id,
            "module_id": self.module_id,
            "module_title": module_title,
            **deepcopy(self._facts),
            "evidence": deepcopy(self._evidence),
            "revision": self.revision,
        }

    @abstractmethod
    def scheduling_span(self):
        """Return (start, end), (None, None) if undated, or None if excluded."""
