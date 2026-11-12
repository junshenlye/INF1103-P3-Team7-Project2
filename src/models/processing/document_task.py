"""Per-document processing work and its understood result."""

from __future__ import annotations

from dataclasses import dataclass

from src.models.documents.document_reference import DocumentReference

UNDERSTOOD = "understood"
PARTIALLY_UNDERSTOOD = "partially_understood"
UNKNOWN = "unknown"
NO_ASSESSMENT_CONTENT = "no_assessment_content"

_SCHEDULING_FIELDS = ("week", "weight_percent")


@dataclass(frozen=True)
class DocumentTask:
    """One document to process, fenced by its retry ``generation``.

    A retry or replacement increments the generation, so results from an
    older attempt can be recognised and discarded.
    """

    document: DocumentReference
    generation: int


@dataclass(frozen=True)
class DocumentOutcome:
    """What was understood from a document, independent of how it executed.

    ``inference`` is one of ``understood``, ``partially_understood``,
    ``unknown`` or ``no_assessment_content``.
    """

    inference: str
    records: tuple = ()
    uncertainties: tuple = ()
    issues: tuple = ()

    @classmethod
    def from_chunks(cls, chunks, issues=()):
        """Combine accepted extraction chunks into one document outcome.

        Each chunk provides ``records`` and ``uncertainties``. An assessment
        record without a week or weight adds an uncertainty, so a document
        is only ``understood`` when every scheduling fact is known and no
        issue was reported.
        """
        records = tuple(record for chunk in chunks for record in chunk["records"])
        missing = {
            f"{record['name']}: {field} could not be inferred from this source."
            for record in records
            if record["kind"] == "assessment"
            for field in _SCHEDULING_FIELDS
            if record[field] is None
        }
        reported = {note for chunk in chunks for note in chunk["uncertainties"]}
        uncertainties = tuple(sorted(reported | missing))

        if records:
            incomplete = bool(issues or uncertainties)
            inference = PARTIALLY_UNDERSTOOD if incomplete else UNDERSTOOD
        else:
            inference = UNKNOWN if issues else NO_ASSESSMENT_CONTENT
        return cls(inference, records, uncertainties, tuple(issues))
