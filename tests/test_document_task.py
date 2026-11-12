"""Tests for document tasks and combined document outcomes."""

from dataclasses import FrozenInstanceError
import unittest

from src.models.documents.document_reference import DocumentReference
from src.models.processing.document_task import (
    NO_ASSESSMENT_CONTENT,
    PARTIALLY_UNDERSTOOD,
    UNDERSTOOD,
    UNKNOWN,
    DocumentOutcome,
    DocumentTask,
)


def assessment(name, week=4, weight_percent=10):
    return {"kind": "assessment", "name": name, "week": week, "weight_percent": weight_percent}


def chunk(*records, uncertainties=()):
    return {"records": list(records), "uncertainties": list(uncertainties)}


class DocumentTaskTests(unittest.TestCase):
    def test_keeps_reference_and_generation_immutably(self):
        reference = DocumentReference("d1", "m1", "outline.pdf", "application/pdf", 10, "c")
        task = DocumentTask(reference, 2)
        self.assertEqual((task.document, task.generation), (reference, 2))
        with self.assertRaises(FrozenInstanceError):
            task.generation = 3


class DocumentOutcomeTests(unittest.TestCase):
    def test_understood_when_every_scheduling_fact_is_known(self):
        outcome = DocumentOutcome.from_chunks(
            [chunk(assessment("Quiz")), chunk(assessment("Project", week=12, weight_percent=40))]
        )
        self.assertEqual(outcome.inference, UNDERSTOOD)
        self.assertEqual([r["name"] for r in outcome.records], ["Quiz", "Project"])
        self.assertEqual((outcome.uncertainties, outcome.issues), ((), ()))

    def test_missing_week_or_weight_is_partial_with_explanations(self):
        outcome = DocumentOutcome.from_chunks(
            [chunk(assessment("Quiz", week=None), assessment("Exam", weight_percent=None))]
        )
        self.assertEqual(outcome.inference, PARTIALLY_UNDERSTOOD)
        self.assertEqual(
            outcome.uncertainties,
            (
                "Exam: weight_percent could not be inferred from this source.",
                "Quiz: week could not be inferred from this source.",
            ),
        )

    def test_group_records_do_not_need_scheduling_facts(self):
        group = {"kind": "group", "name": "Coursework", "week": None, "weight_percent": None}
        self.assertEqual(DocumentOutcome.from_chunks([chunk(group)]).inference, UNDERSTOOD)

    def test_reported_uncertainties_or_issues_make_the_outcome_partial(self):
        noted = DocumentOutcome.from_chunks(
            [chunk(assessment("Quiz"), uncertainties=["b", "a"]), chunk(uncertainties=["a"])]
        )
        self.assertEqual((noted.inference, noted.uncertainties), (PARTIALLY_UNDERSTOOD, ("a", "b")))

        issue = {"code": "invalid_extraction"}
        flagged = DocumentOutcome.from_chunks([chunk(assessment("Quiz"))], [issue])
        self.assertEqual((flagged.inference, flagged.issues), (PARTIALLY_UNDERSTOOD, (issue,)))

    def test_without_records_outcome_depends_on_issues(self):
        self.assertEqual(DocumentOutcome.from_chunks([chunk()]).inference, NO_ASSESSMENT_CONTENT)
        self.assertEqual(DocumentOutcome.from_chunks([], [{"code": "x"}]).inference, UNKNOWN)


if __name__ == "__main__":
    unittest.main()
