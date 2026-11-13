"""Tests for the command that applies pending database migrations."""

from contextlib import contextmanager, redirect_stderr, redirect_stdout
import io
from pathlib import Path
import unittest

from src.migrate import main
from src.storage.postgres_migrations import MIGRATIONS

SECRET_URL = "postgresql://admin:s3cret@db.internal/project2"


def environment(**overrides):
    absolute = str(Path(__file__).resolve().parent)
    return {"DATABASE_URL": SECRET_URL, "DOCUMENT_DIRECTORY": absolute, **overrides}


class MigrateCommandTests(unittest.TestCase):
    def setUp(self):
        self.events = []

    @contextmanager
    def open_pool(self, settings):
        self.events.append(("open", settings.database_url, settings.pool_size))
        try:
            yield "pool"
        finally:
            self.events.append(("close",))

    def run_main(self, env, migrate=None):
        def record(pool, directory):
            self.events.append(("migrate", pool, directory))

        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(env, open_pool=self.open_pool, migrate=migrate or record)
        return code, out.getvalue(), err.getvalue()

    def test_applies_migrations_with_a_pool_from_settings(self):
        code, out, err = self.run_main(environment(DATABASE_POOL_SIZE="3"))
        self.assertEqual(code, 0)
        self.assertEqual(
            self.events,
            [("open", SECRET_URL, 3), ("migrate", "pool", MIGRATIONS), ("close",)],
        )
        self.assertIn("up to date", out)
        self.assertEqual(err, "")

    def test_missing_database_url_fails_without_connecting(self):
        env = environment()
        del env["DATABASE_URL"]
        code, out, err = self.run_main(env)
        self.assertEqual(code, 1)
        self.assertIn("DATABASE_URL", err)
        self.assertEqual(self.events, [])

    def test_invalid_settings_fail_without_connecting(self):
        code, out, err = self.run_main(environment(DATABASE_URL="mysql://localhost/db"))
        self.assertEqual(code, 1)
        self.assertIn("Invalid settings", err)
        self.assertEqual(self.events, [])

    def test_failed_migration_closes_the_pool_and_reports_without_the_url(self):
        def fail(pool, directory):
            raise ValueError("Applied migration 001_initial.sql has changed.")

        code, out, err = self.run_main(environment(), migrate=fail)
        self.assertEqual(code, 1)
        self.assertEqual(self.events[-1], ("close",))
        self.assertIn("001_initial.sql has changed", err)
        self.assertNotIn("s3cret", err + out)
        self.assertEqual(out, "")


if __name__ == "__main__":
    unittest.main()
