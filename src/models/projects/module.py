from __future__ import annotations
from dataclasses import dataclass, field


@dataclass(frozen=True, eq=False)
class Module:
    id: str
    project_id: str
    job_id: str
    module_title: str
    normalized_title: str
    credit: int
    position: int
    _assessments: tuple["Assessment", ...] = field(default=(), repr=False, compare=False)

    def get_assessments(self):
        """Return passive references; only a manager traverses them."""
        return self._assessments
