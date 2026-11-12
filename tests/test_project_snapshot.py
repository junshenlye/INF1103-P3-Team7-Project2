"""Tests for the immutable project snapshot value object."""

import unittest
from dataclasses import FrozenInstanceError

from src.models.processing import ProjectSnapshot
from src.models.projects.module import Module
from src.models.projects.project import Project


class ProjectSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.project = Project("project-1", "Trimester 1", 14)
        self.module = Module(
            "module-1", "project-1", "job-1", "Computing", "computing", 6, 0
        )

    def test_captures_project_records_and_revision_metadata(self):
        snapshot = ProjectSnapshot(
            project=self.project,
            modules=(self.module,),
            assessments=(),
            issues=(),
            documents=(),
            revision_id=3,
            stale=False,
            event_cursor=12,
        )

        self.assertIs(snapshot.project, self.project)
        self.assertEqual(snapshot.modules, (self.module,))
        self.assertEqual(snapshot.revision_id, 3)
        self.assertFalse(snapshot.stale)
        self.assertEqual(snapshot.event_cursor, 12)

    def test_supports_snapshot_without_a_published_revision(self):
        snapshot = ProjectSnapshot(self.project, (), (), (), (), None, False, 0)

        self.assertIsNone(snapshot.revision_id)
        self.assertEqual(snapshot.event_cursor, 0)

    def test_snapshot_fields_are_immutable(self):
        snapshot = ProjectSnapshot(self.project, (), (), (), (), 1, True, 4)

        with self.assertRaises(FrozenInstanceError):
            snapshot.stale = False


if __name__ == "__main__":
    unittest.main()
