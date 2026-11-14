"""Exercise the published-result reads used by the document viewer."""

from contextlib import nullcontext
from importlib.util import find_spec
import unittest
from unittest.mock import Mock
from uuid import uuid4

from src.managers.data_manager import DataManager
from src.managers.io_manager import IOManager


@unittest.skipUnless(find_spec("fastapi") and find_spec("httpx"), "HTTP dependencies unavailable")
class PublishedResultHTTPTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient

        self.result_id = str(uuid4())
        self.db = Mock()
        self.db.transaction.return_value = nullcontext()
        pool = Mock()
        pool.connection.return_value = nullcontext(self.db)
        self.client = TestClient(IOManager(DataManager(pool), Mock()).get_application())
        self.addCleanup(self.client.close)

    def test_returns_published_assessment_facts_and_evidence(self):
        result = {
            "id": self.result_id, "job_id": str(uuid4()), "module_id": str(uuid4()),
            "uncertainties": [], "metrics": {},
        }
        assessment = {
            "id": str(uuid4()), "result_id": self.result_id, "module_id": result["module_id"],
            "parent_assessment_id": None, "facts": {"week": 4}, "revision": 2,
            "evidence": {"week": [str(uuid4())]},
        }
        self.db.execute.side_effect = [
            Mock(),
            Mock(fetchone=Mock(return_value=result)),
            Mock(fetchall=Mock(return_value=[assessment])),
        ]

        response = self.client.get(f"/api/results/{self.result_id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {**result, "assessments": [assessment]})
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")
        self.db.transaction.assert_called_once()

    def test_returns_result_source_documents(self):
        documents = [{"id": str(uuid4()), "filename": "brief.pdf", "media_type": "application/pdf"}]
        self.db.execute.return_value.fetchone.return_value = {"documents": documents}

        response = self.client.get(f"/api/results/{self.result_id}/documents")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), documents)

    def test_both_routes_reject_invalid_ids_without_querying(self):
        for suffix in ("", "/documents"):
            with self.subTest(suffix=suffix):
                self.assertEqual(self.client.get(f"/api/results/invalid{suffix}").status_code, 404)
        self.db.execute.assert_not_called()

    def test_both_routes_return_404_for_results_that_are_not_public(self):
        self.db.execute.return_value.fetchone.return_value = None
        for suffix in ("", "/documents"):
            with self.subTest(suffix=suffix):
                response = self.client.get(f"/api/results/{self.result_id}{suffix}")
                self.assertEqual(response.status_code, 404)
