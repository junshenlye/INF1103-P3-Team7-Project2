"""Verify migration ordering, ledger checks and transactional rollback."""

from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

from src.storage.postgres_migrations import apply_migrations


class MigrationConnection:
    def __init__(self):
        self.ledger = {}
        self.statements = []
        self.scripts = []
        self.mapping_rows = False

    @contextmanager
    def transaction(self):
        ledger_before = self.ledger.copy()
        scripts_before = self.scripts.copy()
        try:
            yield
        except Exception:
            self.ledger = ledger_before
            self.scripts = scripts_before
            raise

    def execute(self, statement, params=()):
        self.statements.append(statement)
        if statement.startswith("SELECT checksum"):
            checksum = self.ledger.get(params[0])
            row = {"checksum": checksum} if self.mapping_rows else (checksum,)
            return Mock(fetchone=Mock(return_value=row if checksum is not None else None))
        if statement.startswith("INSERT INTO stackplan.schema_migrations"):
            self.ledger[params[0]] = params[1]
        if statement.startswith("CREATE TABLE sample"):
            self.scripts.append(statement)
        if statement == "INVALID SQL":
            raise RuntimeError("Migration SQL failed")


class PostgresMigrationTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.connection = MigrationConnection()
        self.pool = Mock()
        self.pool.connection.side_effect = self.checkout

    @contextmanager
    def checkout(self):
        yield self.connection

    def write(self, filename, contents):
        (self.directory / filename).write_text(contents, encoding="utf-8")

    def test_applies_in_order_and_skips_matching_scripts_on_rerun(self):
        first = "CREATE TABLE sample_one (id int)"
        second = "CREATE TABLE sample_two (id int)"
        self.write("002_second.sql", second)
        self.write("001_first.sql", first)

        apply_migrations(self.pool, self.directory)
        self.connection.mapping_rows = True
        apply_migrations(self.pool, self.directory)

        self.assertEqual(self.connection.statements[0], "SELECT pg_advisory_xact_lock(719231)")
        self.assertEqual(self.connection.scripts, [first, second])
        self.assertEqual(list(self.connection.ledger), ["001_first.sql", "002_second.sql"])
        for script in (first, second):
            index = self.connection.statements.index(script)
            self.assertEqual(self.connection.statements[index - 1], "SET LOCAL search_path TO stackplan")

    def test_rejects_a_modified_applied_migration(self):
        filename = "001_first.sql"
        first = "CREATE TABLE sample_one (id int)"
        self.write(filename, first)
        apply_migrations(self.pool, self.directory)
        ledger = self.connection.ledger.copy()

        self.write(filename, "CREATE TABLE sample_one (id bigint)")
        with self.assertRaisesRegex(ValueError, filename):
            apply_migrations(self.pool, self.directory)

        self.assertEqual(self.connection.ledger, ledger)
        self.assertEqual(self.connection.scripts, [first])

    def test_rolls_back_earlier_migrations_if_a_later_script_fails(self):
        self.write("001_first.sql", "CREATE TABLE sample_one (id int)")
        self.write("002_second.sql", "INVALID SQL")

        with self.assertRaisesRegex(RuntimeError, "Migration SQL failed"):
            apply_migrations(self.pool, self.directory)

        self.assertEqual(self.connection.ledger, {})
        self.assertEqual(self.connection.scripts, [])

    def test_missing_migrations_fails_before_opening_a_connection(self):
        with self.assertRaisesRegex(ValueError, "No SQL migrations"):
            apply_migrations(self.pool, self.directory)

        self.pool.connection.assert_not_called()
