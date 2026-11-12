"""Assessment facts shared by individual tasks and non-scheduled group totals."""

from __future__ import annotations

from abc import ABC, abstractmethod
from copy import deepcopy
from dataclasses import dataclass


@dataclass(frozen=True)
class Assessment(ABC):
    """A published, evidence-backed assessment fact set.

    Concrete subclasses decide how they appear in a schedule. Use
    :meth:`create` to choose the subclass from the validated ``kind`` fact.
    """

    id: str
    result_id: str
    module_id: str
    facts: dict
    evidence: dict
    parent_assessment_id: str | None = None
    revision: int = 0

    @staticmethod
    def create(
        id,
        result_id,
        module_id,
        facts,
        evidence,
        parent_assessment_id=None,
        revision=0,
    ):
        """Build the assessment type named by ``facts["kind"]``.

        Facts and evidence are copied so later changes to the caller's data
        cannot alter the assessment.

        Raises:
            ValueError: If the kind is missing or not recognised.
        """
        from src.models.assessments.assessment_group import AssessmentGroup
        from src.models.assessments.individual_assessment import IndividualAssessment

        implementations = {"group": AssessmentGroup, "assessment": IndividualAssessment}
        try:
            implementation = implementations[facts["kind"]]
        except (KeyError, TypeError) as exc:
            raise ValueError("Unknown assessment kind.") from exc
        return implementation(
            id,
            result_id,
            module_id,
            deepcopy(facts),
            deepcopy(evidence),
            parent_assessment_id,
            revision,
        )

    def schedule_item(self, module_title):
        """Return a detached display record; editing it cannot change saved facts."""
        return {
            "assessment_id": self.id,
            "result_id": self.result_id,
            "module_id": self.module_id,
            "module_title": module_title,
            **deepcopy(self.facts),
            "evidence": deepcopy(self.evidence),
            "revision": self.revision,
        }

    @abstractmethod
    def add_to_schedule(self, schedule, module_title):
        """Contribute display items without changing this assessment's facts."""
