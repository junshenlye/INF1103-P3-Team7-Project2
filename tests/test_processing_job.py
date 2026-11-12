"""Tests for the processing-job domain value object."""

import unittest
from dataclasses import FrozenInstanceError

from src.models.processing import ProcessingJob


class ProcessingJobTests(unittest.TestCase):
    def test_job_preserves_submission_and_worker_claim_data(self):
        job = ProcessingJob(
            id="job-42",
            project_id="project-7",
            submission_key="submission-abc",
            status="running",
            stage="extracting",
            lease_token="lease-123",
        )

        self.assertEqual(job.project_id, "project-7")
        self.assertEqual(job.submission_key, "submission-abc")
        self.assertEqual(job.lease_token, "lease-123")

    def test_queued_job_does_not_require_a_worker_lease(self):
        job = ProcessingJob(
            id="job-42",
            project_id="project-7",
            submission_key="submission-abc",
            status="queued",
            stage="pending",
        )

        self.assertIsNone(job.lease_token)

    def test_job_identity_is_immutable(self):
        job = ProcessingJob(
            id="job-42",
            project_id="project-7",
            submission_key="submission-abc",
            status="queued",
            stage="pending",
        )

        with self.assertRaises(FrozenInstanceError):
            job.status = "running"


if __name__ == "__main__":
    unittest.main()
