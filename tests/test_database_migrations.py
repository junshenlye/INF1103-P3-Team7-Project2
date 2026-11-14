"""Regression checks for the versioned PostgreSQL schema."""

from pathlib import Path
import unittest


MIGRATIONS = Path(__file__).parents[1] / "database" / "migrations"


class DatabaseMigrationTests(unittest.TestCase):
    def test_migrations_cover_the_processing_lifecycle_in_order(self):
        files = sorted(path.name for path in MIGRATIONS.glob("*.sql"))

        self.assertEqual(
            files,
            [
                "001_initial.sql",
                "002_integrity.sql",
                "003_review_evidence.sql",
                "004_fact_values.sql",
                "005_document_progress.sql",
                "006_document_recovery.sql",
                "007_lifecycle_consistency.sql",
            ],
        )

    def test_schema_protects_published_facts_and_evidence(self):
        initial = (MIGRATIONS / "001_initial.sql").read_text()
        integrity = (MIGRATIONS / "002_integrity.sql").read_text()
        review_evidence = (MIGRATIONS / "003_review_evidence.sql").read_text()
        fact_values = (MIGRATIONS / "004_fact_values.sql").read_text()

        self.assertIn("CREATE TABLE processing_jobs", initial)
        self.assertIn("CREATE TABLE assessments", initial)
        self.assertIn("CREATE TABLE assessment_evidence", initial)
        self.assertIn("CREATE TRIGGER immutable_assessments", initial)
        self.assertIn("CREATE TRIGGER evidence_owner", integrity)
        self.assertIn("CREATE TRIGGER review_evidence_owner", review_evidence)
        self.assertIn("CREATE FUNCTION valid_assessment_facts", fact_values)

    def test_schema_tracks_document_progress_without_mutating_sources(self):
        progress = (MIGRATIONS / "005_document_progress.sql").read_text()

        self.assertIn("CREATE TABLE document_progress", progress)
        self.assertIn("INSERT INTO document_progress", progress)
        self.assertIn("'waiting'", progress)
        self.assertIn("'extracted'", progress)

    def test_schema_supports_resumable_document_tasks(self):
        recovery = (MIGRATIONS / "006_document_recovery.sql").read_text()

        for table in (
            "document_tasks",
            "document_chunks",
            "extraction_attempts",
            "module_result_heads",
            "processing_events",
            "retry_requests",
            "provider_permits",
            "document_replacements",
        ):
            with self.subTest(table=table):
                self.assertIn(f"CREATE TABLE {table}", recovery)
        self.assertIn("CREATE TRIGGER document_enqueue", recovery)
        self.assertIn("CREATE TRIGGER immutable_chunks", recovery)
        self.assertIn("'Partial'", recovery)
        self.assertIn("INSERT INTO document_tasks", recovery)
        self.assertIn("INSERT INTO module_result_heads", recovery)

    def test_lifecycle_migration_guards_transitions_and_repairs_unfinished_tasks(self):
        lifecycle = (MIGRATIONS / "007_lifecycle_consistency.sql").read_text()

        self.assertIn("CREATE TABLE assessment_review_lineage", lifecycle)
        self.assertIn("CREATE TRIGGER immutable_review_lineage", lifecycle)
        self.assertIn("CREATE OR REPLACE FUNCTION enforce_project_transition()", lifecycle)
        self.assertIn("CREATE OR REPLACE FUNCTION enforce_job_transition()", lifecycle)
        self.assertIn("OLD.status IN ('Ready', 'Partial', 'Failed', 'Interrupted')", lifecycle)
        self.assertIn("NEW.status IN ('Ready', 'Partial', 'Failed')", lifecycle)
        self.assertIn("UPDATE document_tasks AS task", lifecycle)
        self.assertIn("job.status IN ('Failed', 'Interrupted')", lifecycle)
        self.assertIn("task.state IN ('queued', 'running')", lifecycle)


if __name__ == "__main__":
    unittest.main()
