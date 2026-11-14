"""Verify the project persistence boundary with an injected pool."""

from contextlib import contextmanager
import unittest
from unittest.mock import Mock
from uuid import UUID

from src.errors import error_codes
from src.errors.processing_error import ProcessingError
from src.managers import DataManager
from src.models.projects.project import Project


class ProjectPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.db = Mock()
        self.checkouts = 0
        self.manager = DataManager(self)

    @contextmanager
    def connection(self):
        self.checkouts += 1
        try:
            yield self.db
        finally:
            self.checkouts -= 1

    def test_get_health_checks_the_applied_migration_ledger(self):
        self.db.execute.return_value.fetchone.return_value = {
            "version": "007_lifecycle_consistency.sql"
        }

        self.assertEqual(self.manager.get_health(), {"status": "ok"})
        sql = self.db.execute.call_args.args[0]
        self.assertIn("SELECT version FROM stackplan.schema_migrations", sql)
        self.assertEqual(self.checkouts, 0)

    def test_get_health_rejects_an_unmigrated_database(self):
        self.db.execute.return_value.fetchone.return_value = None

        with self.assertRaisesRegex(RuntimeError, "migrations have not been applied"):
            self.manager.get_health()

        self.assertEqual(self.checkouts, 0)

    def test_create_project_persists_initial_identity(self):
        project = self.manager.create_project("Trimester 1", 14)

        self.assertEqual(str(UUID(project.id)), project.id)
        self.assertEqual(project, Project(project.id, "Trimester 1", 14))
        sql, params = self.db.execute.call_args.args
        self.assertIn("INSERT INTO stackplan.projects", sql)
        self.assertEqual(params, (project.id, "Trimester 1", 14))
        self.assertEqual(self.checkouts, 0)

    def test_get_project_preserves_status_and_job(self):
        row = dict(id="project", name="Trimester 1", week_count=14, status="Ready", job_id="job")
        self.db.execute.return_value.fetchone.return_value = row

        self.assertEqual(self.manager.get_project("project"), Project(**row))
        sql, params = self.db.execute.call_args.args
        self.assertIn("WHERE id = %s", sql)
        self.assertEqual(params, ("project",))
        self.assertEqual(self.checkouts, 0)

    def test_missing_project_raises_domain_error(self):
        self.db.execute.return_value.fetchone.return_value = None

        with self.assertRaises(ProcessingError) as raised:
            self.manager.get_project("missing")

        self.assertEqual(raised.exception.code, error_codes.NOT_FOUND)
        self.assertEqual(self.checkouts, 0)

    def test_get_projects_returns_bounded_newest_first_summaries(self):
        row = dict(id="project", name="Trimester 1", week_count=14, status="Created", job_id=None)
        self.db.execute.return_value.fetchall.return_value = [row]

        self.assertEqual(self.manager.get_projects(), [row])
        self.assertIn("ORDER BY created_at DESC, id DESC LIMIT 100", self.db.execute.call_args.args[0])
        self.assertEqual(self.checkouts, 0)
