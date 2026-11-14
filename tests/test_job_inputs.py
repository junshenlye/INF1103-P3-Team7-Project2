"""Check that job inputs are read through the project persistence boundary."""

from contextlib import nullcontext
import unittest
from unittest.mock import Mock

from src.managers import DataManager
from src.models.documents.document_reference import DocumentReference
from src.models.projects.module import Module


class JobInputsTests(unittest.TestCase):
    def setUp(self):
        self.connection = Mock()
        pool = Mock()
        pool.connection.return_value = nullcontext(self.connection)
        self.data = DataManager(pool)

    def test_get_job_modules_returns_submitted_modules_in_order(self):
        rows = [
            dict(id="module-1", project_id="project", job_id="job", module_title="Computing",
                 normalized_title="computing", credit=6, position=0),
            dict(id="module-2", project_id="project", job_id="job", module_title="Mathematics",
                 normalized_title="mathematics", credit=6, position=1),
        ]
        self.connection.execute.return_value.fetchall.return_value = rows

        self.assertEqual(self.data.get_job_modules("job"), [Module(**row) for row in rows])
        sql, params = self.connection.execute.call_args.args
        self.assertIn("WHERE job_id = %s", sql)
        self.assertIn("ORDER BY position", sql)
        self.assertEqual(params, ("job",))

    def test_get_processing_documents_scopes_to_job_and_module(self):
        row = dict(id="document", module_id="module", filename="outline.pdf",
                   media_type="application/pdf", size=12, checksum="a" * 64)
        self.connection.execute.return_value.fetchall.return_value = [row]

        self.assertEqual(
            self.data.get_processing_documents("job", "module"),
            [DocumentReference(**row)],
        )
        sql, params = self.connection.execute.call_args.args
        self.assertIn("module.id = document.module_id", sql)
        self.assertIn("module.job_id = %s AND module.id = %s", sql)
        self.assertIn("ORDER BY document.id", sql)
        self.assertNotIn("storage_key", sql)
        self.assertEqual(params, ("job", "module"))

    def test_empty_queries_return_empty_lists(self):
        self.connection.execute.return_value.fetchall.return_value = []

        self.assertEqual(self.data.get_job_modules("job"), [])
        self.assertEqual(self.data.get_processing_documents("job", "module"), [])
