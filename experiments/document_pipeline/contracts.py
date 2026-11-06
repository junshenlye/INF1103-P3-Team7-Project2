"""Strict extraction contract and deterministic evidence/scheduler adapters."""

from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator
from src.domain.module import Module, AssessmentGroup
from src.domain.assessment import Assessment
from src.domain.assessment_timing import AssessmentTiming
from src.logic_manager.schedule_builder import ScheduleBuilder


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class TextFact(StrictModel):
    value: Optional[str]
    evidence: list[str]


class TimingFact(StrictModel):
    weeks: Optional[list[int]]
    raw: Optional[str]
    qualification: Literal["tentative", "unspecified", "confirmed", "unknown"]
    evidence: list[str]

    @model_validator(mode="after")
    def check_weeks(self):
        if self.weeks is not None and (
            not self.weeks
            or len(set(self.weeks)) != len(self.weeks)
            or any(w < 1 or w > 53 for w in self.weeks)
        ):
            raise ValueError("Weeks must be distinct positive teaching-week numbers.")
        return self


class WeightFact(StrictModel):
    value: Optional[float] = Field(ge=0, le=100)
    scope: Literal["single", "group", "unknown"]
    evidence: list[str]


class ExtractedAssessment(StrictModel):
    name: TextFact
    timing: TimingFact
    weight: WeightFact
    requirements: list[TextFact]


class Extraction(StrictModel):
    relevant: bool
    detected_module: Optional[str]
    assessments: list[ExtractedAssessment]
    uncertainties: list[str]

    @model_validator(mode="after")
    def check_relevance(self):
        if not self.relevant and self.assessments:
            raise ValueError("Irrelevant source cannot contain extracted assessments.")
        for item in self.assessments:
            if not item.name.value or not item.name.value.strip():
                raise ValueError("Assessment name is required.")
            if (
                item.timing.weeks
                and len(item.timing.weeks) > 1
                and item.weight.scope == "single"
                and item.weight.value is not None
            ):
                raise ValueError(
                    "Multiple occurrences require an explicit group/unknown weight scope."
                )
        return self


def validate_evidence(extraction, source_map):
    """Check reference integrity, never claim this proves semantic support."""
    resolved = []
    for index, item in enumerate(extraction.assessments):
        facts = [
            ("name", item.name, item.name.value),
            ("timing", item.timing, item.timing.weeks or item.timing.raw),
            ("weight", item.weight, item.weight.value),
        ]
        facts += [
            (f"requirements.{i}", fact, fact.value)
            for i, fact in enumerate(item.requirements)
        ]
        for field, fact, value in facts:
            if value is not None and not fact.evidence:
                raise ValueError(f"Missing evidence for assessment {index} {field}")
            if len(fact.evidence) != len(set(fact.evidence)):
                raise ValueError("Duplicate evidence reference")
            for ref in fact.evidence:
                if ref not in source_map:
                    raise ValueError(f"Unknown evidence reference: {ref}")
                if not source_map[ref]["regions"]:
                    raise ValueError(f"Evidence has no source region: {ref}")
            resolved.append(
                {
                    "assessment": index,
                    "field": field,
                    "value": value,
                    "evidence": [source_map[ref] for ref in fact.evidence],
                    "semantic_support": "needs_review",
                }
            )
    return resolved


def schedule(extraction, title, credit, document_id):
    """Adapt without changing the production normalizer or scheduler.

    Keep evidence separately keyed by deterministic assessment IDs because the
    existing domain does not persist provenance. Never split a shared weight.
    """
    groups, links, follow_ups = [], {}, []
    for index, item in enumerate(extraction.assessments):
        weeks = item.timing.weeks or [None]
        assessments = []
        for occurrence, week in enumerate(weeks, 1):
            aid = f"{document_id[:16]}-a{index}-o{occurrence}"
            timing = AssessmentTiming(
                kind="week" if week else "unknown", week=week, raw=item.timing.raw
            )
            assessments.append(
                Assessment(
                    aid,
                    item.name.value,
                    timing,
                    occurrence_number=occurrence,
                    occurrence_count=len(weeks),
                    weight_percent=item.weight.value
                    if item.weight.scope == "single"
                    else None,
                    weight_scope="module"
                    if item.weight.scope == "single"
                    else "unknown",
                    details="\n".join(f.value for f in item.requirements if f.value)
                    or None,
                )
            )
            links[aid] = {
                "extraction_index": index,
                "document_id": document_id,
                "fields": item.model_dump(),
            }
            if item.timing.qualification == "tentative":
                follow_ups.append(
                    {
                        "assessment_id": aid,
                        "assessment": item.name.value,
                        "field": "schedule",
                        "message": "Source timing is tentative.",
                    }
                )
        groups.append(
            AssessmentGroup(
                "other",
                tuple(assessments),
                item.weight.value if item.weight.scope == "group" else None,
                "module" if item.weight.scope == "group" else "unknown",
            )
        )
    module = Module(
        title,
        credit,
        tuple(groups),
        notes=tuple(extraction.uncertainties),
        follow_ups=tuple(follow_ups),
    )
    errors = []
    result = ScheduleBuilder().build((module,), errors)
    if errors:
        raise ValueError("; ".join(errors))
    return {
        "module": module.to_record(),
        "schedule": result.to_record(),
        "assessment_sources": links,
    }
