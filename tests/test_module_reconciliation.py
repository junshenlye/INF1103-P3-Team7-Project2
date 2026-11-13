"""Tests for publishing a module result from saved extraction candidates."""

import copy
from types import SimpleNamespace
import unittest
from uuid import uuid4

from src.errors import error_codes as errors
from src.errors.processing_error import ProcessingError
from src.managers import LogicManager
from src.models.assessments import AssessmentGroup, IndividualAssessment
from src.models.processing.checkpoint import ModuleCheckpoint
from src.processing.module_reconciliation import reconcile_module

JOB = SimpleNamespace(id="job-1")
MODULE = SimpleNamespace(id="module-1")


def record(key="exam", source="source", **changes):
    fields = {
        "key": key,
        "name": key.title(),
        "kind": "assessment",
        "weight_percent": None,
        "weight_scope": "unknown",
        "week": None,
        "end_week": None,
        "parent_key": None,
        **changes,
    }
    fields["evidence"] = {k: [source] for k, v in fields.items() if k != "key" and v is not None}
    return fields


def checkpoint(records, unchanged=False, previous=(), versions=None):
    return ModuleCheckpoint(
        records=records,
        uncertainties=["Exam: week could not be inferred from this source."],
        source_ids={"source", "second"},
        manifest="manifest-1",
        unchanged=unchanged,
        previous_assessments=previous,
        previous_versions=versions or {},
    )


class ModuleStore:
    def __init__(self, *checkpoints, conflicts=0):
        self.checkpoints = list(checkpoints)
        self.conflicts = conflicts
        self.reads = 0
        self.saved = []

    def get_module_checkpoint(self, job_id, module_id):
        self.reads += 1
        return self.checkpoints[min(self.reads, len(self.checkpoints)) - 1]

    def save_extraction_result(self, job, result, assessments, manifest, previous_versions, transfers):
        if self.conflicts:
            self.conflicts -= 1
            raise ProcessingError(errors.REVISION_CONFLICT, "A review changed.", "module")
        self.saved.append((result, assessments, manifest, dict(previous_versions), transfers))


class ReconcileModuleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.logic = LogicManager()

    async def reconcile(self, store, attempts=3):
        return await reconcile_module(store, self.logic, JOB, MODULE, 14, attempts)

    async def test_merges_records_and_publishes_one_result(self):
        store = ModuleStore(
            checkpoint(
                [
                    record("project", kind="group", weight_percent=40, weight_scope="module"),
                    record("report", parent_key="project", weight_scope="group", week=10),
                    record(
                        "report",
                        source="second",
                        parent_key="project",
                        weight_scope="group",
                        weight_percent=100,
                    ),
                ]
            )
        )
        result = await self.reconcile(store)

        (saved, assessments, manifest, versions, transfers), = store.saved
        self.assertIs(saved, result)
        self.assertEqual((result.job_id, result.module_id), ("job-1", "module-1"))
        self.assertEqual(result.metrics["pipeline"], "document-queue-v1")
        self.assertEqual(result.uncertainties, ("Exam: week could not be inferred from this source.",))
        self.assertEqual(manifest, "manifest-1")
        self.assertEqual(transfers, ())

        by_key = {a.facts["key"]: a for a in assessments}
        self.assertIsInstance(by_key["project"], AssessmentGroup)
        self.assertIsInstance(by_key["report"], IndividualAssessment)
        self.assertEqual(by_key["report"].parent_assessment_id, by_key["project"].id)
        self.assertEqual(by_key["report"].facts["week"], 10)
        self.assertEqual(by_key["report"].facts["weight_percent"], 100)
        self.assertEqual(set(result.assessment_ids), {a.id for a in assessments})
        self.assertTrue(all(a.result_id == result.id for a in assessments))

    async def test_nothing_is_published_when_unchanged_or_empty(self):
        for saved in (checkpoint([record()], unchanged=True), checkpoint([])):
            with self.subTest(unchanged=saved.unchanged):
                store = ModuleStore(saved)
                self.assertIsNone(await self.reconcile(store))
                self.assertEqual(store.saved, [])

    async def test_reviewed_corrections_are_carried_forward(self):
        original = record(week=12)
        reviewed = {**original, "week": 10}
        previous = {
            "id": str(uuid4()),
            "revision": 1,
            "original_facts": {k: v for k, v in original.items() if k != "evidence"},
            "original_evidence": copy.deepcopy(original["evidence"]),
            "facts": {k: v for k, v in reviewed.items() if k != "evidence"},
            "evidence": copy.deepcopy(reviewed["evidence"]),
        }
        store = ModuleStore(
            checkpoint([record(week=12)], previous=[previous], versions={previous["id"]: 1})
        )
        await self.reconcile(store)
        _, _, _, versions, transfers = store.saved[0]
        self.assertEqual(versions, {previous["id"]: 1})
        self.assertEqual(len(transfers), 1)
        self.assertEqual(transfers[0].facts["week"], 10)

    async def test_review_conflict_rereads_and_retries(self):
        store = ModuleStore(checkpoint([record(week=3)]), checkpoint([record(week=4)]), conflicts=1)
        result = await self.reconcile(store)
        self.assertEqual(store.reads, 2)
        self.assertIs(store.saved[0][0], result)
        self.assertEqual(store.saved[0][1][0].facts["week"], 4)

    async def test_gives_up_after_the_last_conflict(self):
        store = ModuleStore(checkpoint([record()]), conflicts=5)
        with self.assertRaises(ProcessingError) as raised:
            await self.reconcile(store, attempts=2)
        self.assertEqual(raised.exception.code, errors.REVISION_CONFLICT)
        self.assertEqual(store.reads, 2)

    async def test_invalid_records_are_not_published(self):
        cases = {
            "conflicting facts": [record(week=3), record(week=4)],
            "missing parent": [record("quiz", parent_key="coursework")],
            "unknown source": [record(source="elsewhere")],
        }
        for name, records in cases.items():
            with self.subTest(name):
                store = ModuleStore(checkpoint(records))
                with self.assertRaises(ProcessingError) as raised:
                    await self.reconcile(store)
                self.assertEqual(raised.exception.code, errors.INVALID_EXTRACTION)
                self.assertEqual(store.saved, [])

    async def test_requires_at_least_one_attempt(self):
        with self.assertRaises(ValueError):
            await self.reconcile(ModuleStore(checkpoint([record()])), attempts=0)


if __name__ == "__main__":
    unittest.main()
