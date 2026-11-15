"""Verify warnings for settled projects whose originals are unavailable."""

from contextlib import nullcontext
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from src.errors import error_codes
from src.storage.postgres_source_integrity import MISSING_MESSAGE, PostgresSourceIntegrity


class FakeConnection:
    def __init__(self, project, documents):
        self.project = project
        self.documents = documents
        self.statements = []
        self.transactions = 0

    def transaction(self):
        self.transactions += 1
        return nullcontext()

    def execute(self, sql, params=()):
        self.statements.append((" ".join(sql.split()), params))
        if "FROM stackplan.projects" in sql:
            return Mock(fetchone=Mock(return_value=self.project))
        if "FROM stackplan.documents" in sql:
            return Mock(fetchall=Mock(return_value=self.documents))
        return Mock()

    def issues(self):
        return [params for sql, params in self.statements if "INSERT INTO stackplan.processing_issues" in sql]


class SourceIntegrityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "originals").mkdir()

    def document(self, name, content=b"%PDF-1.4 outline", stored=None):
        """Return a document row; ``stored`` is what is actually on disk."""
        key = f"originals/{name}.pdf"
        if stored is not False:
            (self.root / key).write_bytes(content if stored is None else stored)
        return {
            "id": name, "module_id": "module", "filename": f"{name}.pdf",
            "media_type": "application/pdf", "size": len(content),
            "checksum": hashlib.sha256(content).hexdigest(), "storage_key": key,
        }

    def check(self, documents, status="Ready", job_id="job"):
        project = None if status is None else {"status": status, "job_id": job_id}
        self.connection = FakeConnection(project, documents)
        pool = Mock()
        pool.connection.side_effect = lambda: nullcontext(self.connection)
        return PostgresSourceIntegrity(pool, self.root).record_missing_sources("project")

    def test_missing_and_altered_originals_get_one_warning_each(self):
        documents = [
            self.document("intact"),
            self.document("deleted", stored=False),
            self.document("altered", stored=b"%PDF-1.4 changed"),
        ]

        missing = self.check(documents)

        self.assertEqual(missing, ["deleted", "altered"])
        issues = self.connection.issues()
        self.assertEqual([params[3] for params in issues], ["deleted", "altered"])
        _, job, module, _, code, severity, message, scope = issues[0]
        self.assertEqual(
            (job, module, code, severity, message, scope),
            ("job", "module", error_codes.SOURCE_MISSING, "warning", MISSING_MESSAGE, "document"),
        )
        self.assertEqual(self.connection.transactions, 1)

    def test_intact_originals_write_nothing(self):
        self.assertEqual(self.check([self.document("intact")]), [])
        self.assertEqual(self.connection.issues(), [])
        self.assertEqual(self.connection.transactions, 0)

    def test_unsettled_unknown_or_jobless_projects_are_not_checked(self):
        for status, job_id in (("Processing", "job"), ("Failed", "job"), (None, None), ("Ready", None)):
            with self.subTest(status=status, job_id=job_id):
                self.assertEqual(self.check([self.document("deleted", stored=False)], status, job_id), [])
                self.assertEqual(len(self.connection.statements), 1)

    def test_partial_projects_are_checked(self):
        self.assertEqual(self.check([self.document("deleted", stored=False)], "Partial"), ["deleted"])

    def test_document_query_skips_replaced_documents(self):
        self.check([])
        documents_query = next(sql for sql, _ in self.connection.statements if "FROM stackplan.documents" in sql)
        self.assertIn("document_replacements", documents_query)
        self.assertIn("NOT EXISTS", documents_query)

    def test_storage_key_outside_the_root_counts_as_missing(self):
        row = self.document("escape")
        row["storage_key"] = "originals/../../escape.pdf"
        self.assertEqual(self.check([row]), ["escape"])


if __name__ == "__main__":
    unittest.main()
