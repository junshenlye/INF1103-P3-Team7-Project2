"""Tests for project and module identity objects."""

import dataclasses
import unittest

from src.models.processing.lifecycle import CREATED, PROCESSING
from src.models.projects import Module, Project


class ProjectTests(unittest.TestCase):
    def test_new_project_starts_created_without_a_job(self):
        project = Project("p1", "Trimester 1", 13)
        self.assertEqual(project.status, CREATED)
        self.assertIsNone(project.job_id)

    def test_accepts_stored_status_and_job(self):
        project = Project("p1", "Trimester 1", 13, PROCESSING, "j1")
        self.assertEqual((project.status, project.job_id), (PROCESSING, "j1"))

    def test_can_be_rebuilt_from_stored_fields(self):
        row = {"id": "p1", "name": "T1", "week_count": 13, "status": CREATED, "job_id": None}
        self.assertEqual(dataclasses.asdict(Project(**row)), row)

    def test_is_immutable(self):
        with self.assertRaises(dataclasses.FrozenInstanceError):
            Project("p1", "T1", 13).status = PROCESSING


class ModuleTests(unittest.TestCase):
    def test_keeps_submission_fields(self):
        module = Module("m1", "p1", "j1", "INF1103 DevOps", "inf1103 devops", 6, 0)
        self.assertEqual(module.project_id, "p1")
        self.assertEqual(module.normalized_title, "inf1103 devops")
        self.assertEqual((module.credit, module.position), (6, 0))

    def test_equal_fields_compare_equal(self):
        self.assertEqual(
            Module("m1", "p1", "j1", "A", "a", 6, 0),
            Module("m1", "p1", "j1", "A", "a", 6, 0),
        )

    def test_is_immutable(self):
        module = Module("m1", "p1", "j1", "A", "a", 6, 0)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            module.credit = 4


if __name__ == "__main__":
    unittest.main()
