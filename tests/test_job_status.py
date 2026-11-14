"""Verify the job status read used by frontend polling."""

from contextlib import nullcontext
from importlib.util import find_spec
import unittest
from unittest.mock import Mock

from src.managers.data_manager import DataManager
from src.managers.io_manager import IOManager
from src.schemas.job_status_response import JobStatusResponse


JOB_ID = "01d877a1-960d-47bd-aa95-72f1f14429a7"


class JobStatusStorageTests(unittest.TestCase):
    def test_reads_progress_and_issues_together(self):
        db = Mock()
        pool = Mock()
        pool.connection.return_value = nullcontext(db)
        issue = {"code": "processing_interrupted"}
        db.execute.return_value.fetchone.return_value = {
            "id": JOB_ID, "project_id": "project", "status": "Interrupted",
            "stage": "interrupted", "issues": [issue],
            "documents": [{"state": state} for state in ("extracted", "parsing", "waiting")],
        }

        result = DataManager(pool).get_job_status(JOB_ID)

        self.assertEqual(result.id, JOB_ID)
        self.assertEqual(result.issues, [issue])
        self.assertEqual(result.progress, {
            "total_documents": 3, "extracted_documents": 1,
            "documents": [{"state": state} for state in ("extracted", "interrupted", "not_processed")],
        })
        db.execute.assert_called_once()
        sql, args = db.execute.call_args.args
        self.assertIn("NOT issue.resolved", sql)
        self.assertIn("replacement.old_document_id = document.id", sql)
        self.assertEqual(args, (JOB_ID,))


@unittest.skipUnless(find_spec("fastapi") and find_spec("httpx"), "HTTP dependencies unavailable")
class JobStatusRouteTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient

        self.data = Mock()
        self.client = TestClient(IOManager(self.data, Mock()).get_application())
        self.addCleanup(self.client.close)

    def test_returns_job_status_as_json(self):
        progress = {"total_documents": 0, "extracted_documents": 0, "documents": []}
        self.data.get_job_status.return_value = JobStatusResponse(
            JOB_ID, "project", "queued", "queued", [], progress
        )

        response = self.client.get(f"/api/jobs/{JOB_ID}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "id": JOB_ID, "project_id": "project", "status": "queued", "stage": "queued",
            "issues": [], "progress": progress,
        })
        self.data.get_job_status.assert_called_once_with(JOB_ID)

    def test_unknown_job_returns_404(self):
        db = Mock()
        db.execute.return_value.fetchone.return_value = None
        pool = Mock()
        pool.connection.return_value = nullcontext(db)
        self.data.get_job_status.side_effect = DataManager(pool).get_job_status

        self.assertEqual(self.client.get(f"/api/jobs/{JOB_ID}").status_code, 404)

    def test_invalid_job_id_returns_404_without_querying(self):
        self.assertEqual(self.client.get("/api/jobs/invalid").status_code, 404)
        self.data.get_job_status.assert_not_called()
