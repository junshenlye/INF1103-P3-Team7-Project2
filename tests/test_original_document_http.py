"""Read verified originals through the application and document storage."""

from contextlib import nullcontext
from hashlib import sha256
from importlib.util import find_spec
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock
from uuid import uuid4

from src.config.limits import STREAM_CHUNK_BYTES
from src.config.settings import Settings
from src.main import create_app
from src.managers.data_manager import DataManager


@unittest.skipUnless(find_spec("fastapi") and find_spec("httpx"), "HTTP dependencies unavailable")
class OriginalDocumentHTTPTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient

        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        (root / "originals").mkdir()
        self.path = root / "originals" / "brief.pdf"
        self.contents = b"%PDF-1.7\n" + b"x" * STREAM_CHUNK_BYTES
        self.path.write_bytes(self.contents)
        self.document_id = str(uuid4())
        self.row = {
            "id": self.document_id,
            "module_id": str(uuid4()),
            "filename": "brief.pdf",
            "media_type": "application/pdf",
            "size": len(self.contents),
            "checksum": sha256(self.contents).hexdigest(),
            "storage_key": "originals/brief.pdf",
        }
        pool = Mock()
        connection = Mock()
        pool.connection.return_value = nullcontext(connection)
        self.execute = connection.execute
        self.execute.return_value.fetchone.return_value = self.row
        data = DataManager(pool, document_directory=root)
        settings = Settings("postgresql://localhost/test", document_directory=root)
        client = TestClient(create_app(settings=settings, data=data))
        self.client = client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)

    def read(self, document_id=None):
        return self.client.get(f"/api/documents/{document_id or self.document_id}/original")

    def test_streams_verified_bytes_with_inline_security_headers(self):
        response = self.read()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, self.contents)
        self.assertEqual(response.headers["Content-Type"], "application/pdf")
        self.assertEqual(response.headers["Content-Length"], str(len(self.contents)))
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["Content-Disposition"],
                         f'inline; filename="document-{self.document_id}.pdf"')
        self.assertEqual(self.execute.call_args.args[1], (self.document_id,))

    def test_invalid_id_does_not_query_postgres(self):
        self.assertEqual(self.read("invalid").status_code, 404)
        self.execute.assert_not_called()

    def test_unknown_id_returns_a_structured_404(self):
        self.execute.return_value.fetchone.return_value = None
        response = self.read()
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["issues"][0]["code"], "not_found")

    def test_changed_original_fails_verification_before_streaming(self):
        self.path.write_bytes(b"?" * len(self.contents))
        response = self.read()
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["issues"][0]["code"], "source_missing")
        self.assertNotIn("Content-Disposition", response.headers)

    def read_trace(self, document_id=None):
        return self.client.get(f"/api/documents/{document_id or self.document_id}/trace")

    def test_trace_returns_saved_evidence_when_original_is_missing(self):
        self.path.unlink()
        parse = {
            "id": str(uuid4()), "document_id": self.document_id,
            "parser_version": "docling", "chunk_count": 1,
        }
        elements = [{
            "id": str(uuid4()), "document_id": self.document_id, "parse_id": parse["id"],
            "text": "Quiz in week 5", "regions": [], "context": "Assessment", "position": 0,
        }]
        self.execute.side_effect = [
            Mock(fetchone=Mock(return_value=self.row)),
            Mock(fetchone=Mock(return_value=parse)),
            Mock(fetchall=Mock(return_value=elements)),
        ]

        response = self.read_trace()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")
        self.assertEqual(response.json(), {
            "document_id": self.document_id, "filename": "brief.pdf",
            "checksum": self.row["checksum"], "original_available": False,
            "parse": parse, "elements": elements,
        })
        self.assertEqual(self.execute.call_args.args[1], (parse["id"],))
        self.assertIn("ORDER BY position", self.execute.call_args.args[0])

    def test_trace_for_an_unparsed_document_indicates_original_availability(self):
        self.execute.side_effect = [
            Mock(fetchone=Mock(return_value=self.row)),
            Mock(fetchone=Mock(return_value=None)),
        ]

        response = self.read_trace()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["original_available"])
        self.assertIsNone(response.json()["parse"])
        self.assertEqual(response.json()["elements"], [])
        self.assertEqual(self.execute.call_count, 2)

    def test_trace_rejects_invalid_and_unknown_ids(self):
        self.assertEqual(self.read_trace("invalid").status_code, 404)
        self.execute.assert_not_called()
        self.execute.return_value.fetchone.return_value = None
        self.assertEqual(self.read_trace().status_code, 404)
        self.execute.assert_called_once()
