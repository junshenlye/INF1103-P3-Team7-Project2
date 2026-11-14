"""Verify opening originals through their PostgreSQL document records."""

from contextlib import contextmanager
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from src.errors import error_codes
from src.errors.processing_error import ProcessingError
from src.models.documents.document import Document
from src.storage.postgres_document_originals import PostgresDocumentOriginals

CONTENTS = b"%PDF-1.7 assessment brief"


class FakePool:
    """Record whether a connection is checked out while the caller works."""

    def __init__(self, row):
        self.row = row
        self.open_connections = 0
        self.statements = []

    @contextmanager
    def connection(self):
        self.open_connections += 1
        try:
            connection = Mock()

            def execute(sql, params):
                self.statements.append((sql, params))
                return Mock(fetchone=Mock(return_value=self.row))

            connection.execute.side_effect = execute
            yield connection
        finally:
            self.open_connections -= 1


class PostgresDocumentOriginalsTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        (self.root / "originals").mkdir()
        (self.root / "originals" / "doc-1.pdf").write_bytes(CONTENTS)
        self.row = {
            "id": "doc-1",
            "module_id": "module-1",
            "filename": "brief.pdf",
            "media_type": "application/pdf",
            "size": len(CONTENTS),
            "checksum": hashlib.sha256(CONTENTS).hexdigest(),
            "storage_key": "originals/doc-1.pdf",
        }

    def originals(self, row):
        self.pool = FakePool(row)
        return PostgresDocumentOriginals(self.pool, self.root)

    def test_opens_the_verified_original_without_holding_a_connection(self):
        originals = self.originals(self.row)
        with originals.open_document("doc-1") as stream:
            self.assertEqual(self.pool.open_connections, 0)
            self.assertEqual(stream.read(), CONTENTS)
        self.assertTrue(stream.closed)
        sql, params = self.pool.statements[0]
        self.assertIn("FROM stackplan.documents WHERE id = %s", sql)
        self.assertEqual(params, ("doc-1",))

    def test_get_document_returns_the_stored_metadata(self):
        document = self.originals(self.row).get_document("doc-1")
        self.assertEqual(document, Document(**self.row))

    def test_unknown_document_is_not_found(self):
        with self.assertRaises(ProcessingError) as raised:
            with self.originals(None).open_document("missing"):
                self.fail("An unknown document was opened.")
        self.assertEqual(raised.exception.code, error_codes.NOT_FOUND)
        self.assertEqual(raised.exception.related_ids, {"document_id": "missing"})

    def test_missing_changed_or_escaping_originals_are_source_missing(self):
        cases = {
            "missing file": {"storage_key": "originals/other.pdf"},
            "changed contents": {"checksum": "0" * 64},
            "wrong size": {"size": len(CONTENTS) + 1},
            "outside the root": {"storage_key": "originals/../../secret.pdf"},
        }
        for name, changes in cases.items():
            with self.subTest(name):
                with self.assertRaises(ProcessingError) as raised:
                    with self.originals({**self.row, **changes}).open_document("doc-1"):
                        self.fail("An unverifiable original was opened.")
                self.assertEqual(raised.exception.code, error_codes.SOURCE_MISSING)
                self.assertEqual(
                    raised.exception.related_ids, {"document_id": "doc-1", "module_id": "module-1"}
                )

    def test_document_directory_accepts_strings(self):
        originals = PostgresDocumentOriginals(FakePool(self.row), str(self.root))
        with originals.open_document("doc-1") as stream:
            self.assertEqual(stream.read(), CONTENTS)


if __name__ == "__main__":
    unittest.main()
