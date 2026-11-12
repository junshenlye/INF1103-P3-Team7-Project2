"""Tests for immutable processing input and output records."""

import unittest
from dataclasses import FrozenInstanceError

from src.models.processing import ExtractionResult, SubmissionSnapshot
from src.models.projects.module import Module


def module() -> Module:
    return Module(
        id="module-1",
        project_id="project-7",
        job_id="job-4",
        module_title="Software Engineering",
        normalized_title="software engineering",
        credit=4,
        position=1,
    )


class ExtractionResultTests(unittest.TestCase):
    def test_preserves_detached_assessment_output(self):
        metrics = {"documents": 2, "tokens": {"input": 120}}
        uncertainties = [{"field": "week", "reason": "missing"}]

        result = ExtractionResult(
            id="result-3",
            job_id="job-4",
            module_id="module-1",
            assessment_ids=["assessment-2"],
            uncertainties=uncertainties,
            metrics=metrics,
        )
        metrics["tokens"]["input"] = 999
        uncertainties[0]["reason"] = "changed"

        self.assertEqual(result.assessment_ids, ("assessment-2",))
        self.assertEqual(result.metrics["tokens"]["input"], 120)
        self.assertEqual(result.uncertainties[0]["reason"], "missing")
        with self.assertRaises(TypeError):
            result.metrics["documents"] = 4
        with self.assertRaises(TypeError):
            result.metrics["tokens"]["input"] = 4
        with self.assertRaises(FrozenInstanceError):
            result.job_id = "job-5"


class SubmissionSnapshotTests(unittest.TestCase):
    def test_preserves_a_detached_submission_payload(self):
        fields = {"module-1": {"documents": ["document-2"]}}

        snapshot = SubmissionSnapshot(
            project_id="project-7",
            submission_key="submission-abc",
            modules=[module()],
            document_fields=fields,
        )
        fields["module-1"]["documents"].append("document-3")

        self.assertEqual(snapshot.modules, (module(),))
        self.assertEqual(
            snapshot.document_fields["module-1"]["documents"], ("document-2",)
        )
        with self.assertRaises(TypeError):
            snapshot.document_fields["module-1"] = {}
        with self.assertRaises(FrozenInstanceError):
            snapshot.submission_key = "submission-def"


if __name__ == "__main__":
    unittest.main()
