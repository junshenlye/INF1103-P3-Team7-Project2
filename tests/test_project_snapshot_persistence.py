"""Verify project snapshots are assembled in one consistent database transaction."""

from contextlib import contextmanager, nullcontext
import unittest
from unittest.mock import Mock

from src.errors import error_codes
from src.errors.processing_error import ProcessingError
from src.managers.data_manager import DataManager
from src.models.processing.project_snapshot import ProjectSnapshot


class ProjectSnapshotPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.db = Mock()
        self.db.transaction.return_value = nullcontext()
        self.checkouts = 0
        self.manager = DataManager(self)

    @contextmanager
    def connection(self):
        self.checkouts += 1
        try:
            yield self.db
        finally:
            self.checkouts -= 1

    @staticmethod
    def result(*, one=None, many=None):
        value = Mock()
        value.fetchone.return_value = one
        value.fetchall.return_value = many
        return value

    def test_snapshot_reads_project_modules_and_cursor_in_one_transaction(self):
        project = {
            "id": "project-1",
            "name": "Trimester 1",
            "week_count": 14,
            "status": "Ready",
            "job_id": "job-1",
            "event_sequence": 12,
        }
        module = {
            "id": "module-1",
            "project_id": "project-1",
            "job_id": "job-1",
            "module_title": "Computing",
            "normalized_title": "computing",
            "credit": 6,
            "position": 0,
        }
        head = {"result_id": "result-1", "stale": False}
        assessment = {
            "id": "assessment-1",
            "result_id": "result-1",
            "module_id": "module-1",
            "parent_assessment_id": None,
            "facts": {"name": "Quiz", "week": 4},
        }
        document = {
            "id": "document-1",
            "module_id": "module-1",
            "module_title": "Computing",
            "filename": "brief.pdf",
            "media_type": "application/pdf",
            "size": 100,
            "checksum": "a" * 64,
            "state": "succeeded",
            "inference": "understood",
            "generation": 1,
            "replaced_by": None,
        }
        issue = {
            "code": "source_warning",
            "severity": "warning",
            "message": "Source needs review.",
            "scope": "document",
            "job_id": "job-1",
            "module_id": "module-1",
            "document_id": "document-1",
        }
        self.db.execute.side_effect = [
            self.result(),
            self.result(one=project),
            self.result(many=[module]),
            self.result(many=[head]),
            self.result(many=[assessment]),
            self.result(many=[document]),
            self.result(many=[issue]),
            self.result(one={"id": 3}),
        ]

        snapshot = self.manager.get_project_snapshot("project-1")

        self.assertIsInstance(snapshot, ProjectSnapshot)
        self.assertEqual(snapshot.project.id, "project-1")
        self.assertEqual(snapshot.modules[0].module_title, "Computing")
        self.assertEqual(snapshot.assessments[0]["facts"]["week"], 4)
        self.assertEqual(snapshot.documents[0]["filename"], "brief.pdf")
        self.assertEqual(snapshot.issues[0]["code"], "source_warning")
        self.assertEqual(snapshot.revision_id, 3)
        self.assertFalse(snapshot.stale)
        self.assertEqual(snapshot.event_cursor, 12)
        self.db.transaction.assert_called_once_with()
        self.assertIn(
            "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY",
            self.db.execute.call_args_list[0].args[0],
        )
        self.assertEqual(self.checkouts, 0)

    def test_missing_project_raises_not_found_without_reading_related_rows(self):
        self.db.execute.side_effect = [
            self.result(),
            self.result(one=None),
        ]

        with self.assertRaises(ProcessingError) as raised:
            self.manager.get_project_snapshot("missing")

        self.assertEqual(raised.exception.code, error_codes.NOT_FOUND)
        self.assertEqual(self.db.execute.call_count, 2)
        self.db.transaction.assert_called_once_with()
        self.assertEqual(self.checkouts, 0)

    def test_snapshot_without_job_has_empty_related_records(self):
        project = {
            "id": "project-1",
            "name": "Trimester 1",
            "week_count": 14,
            "status": "Created",
            "job_id": None,
            "event_sequence": 0,
        }
        self.db.execute.side_effect = [
            self.result(),
            self.result(one=project),
            self.result(one={"id": None}),
        ]

        snapshot = self.manager.get_project_snapshot("project-1")

        self.assertEqual(snapshot.modules, ())
        self.assertEqual(snapshot.assessments, ())
        self.assertEqual(snapshot.issues, ())
        self.assertEqual(snapshot.documents, ())
        self.assertIsNone(snapshot.revision_id)
        self.assertEqual(snapshot.event_cursor, 0)
        self.assertEqual(self.db.execute.call_count, 3)


if __name__ == "__main__":
    unittest.main()
