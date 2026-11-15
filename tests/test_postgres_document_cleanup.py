"""Verify removal of stored document files that no record refers to."""

from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from src.storage.postgres_document_cleanup import ORIGINALS_LOCK, PostgresDocumentCleanup

NOW = datetime.now(timezone.utc)
CUTOFF = NOW - timedelta(hours=2)
OLD = (NOW - timedelta(hours=3)).timestamp()
RECENT = (NOW - timedelta(minutes=5)).timestamp()


class FakeConnection:
    def __init__(self, keys):
        self.keys = keys
        self.statements = []

    def transaction(self):
        return nullcontext()

    def execute(self, sql, params=()):
        self.statements.append((sql, params))
        return [{"storage_key": key} for key in self.keys] if "storage_key" in sql else Mock()


class DocumentCleanupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def write(self, key, modified=OLD, content=b"x"):
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        os.utime(path, (modified, modified))
        return path

    def age(self, path, modified=OLD):
        os.utime(path, (modified, modified))

    def cleanup(self, registered=(), cutoff=CUTOFF):
        self.connection = FakeConnection(set(registered))
        pool = Mock()
        pool.connection.return_value = nullcontext(self.connection)
        return PostgresDocumentCleanup(pool, self.root).cleanup_orphaned_files(cutoff)

    def test_removes_only_old_unregistered_originals(self):
        kept = self.write("originals/kept.pdf")
        orphan = self.write("originals/orphan.pdf")
        recent = self.write("originals/recent.pdf", RECENT)

        removed = self.cleanup({"originals/kept.pdf"})

        self.assertEqual(removed, ["originals/orphan.pdf"])
        self.assertTrue(kept.exists())
        self.assertFalse(orphan.exists())
        self.assertTrue(recent.exists())

    def test_removes_only_old_staging_directories(self):
        self.write(".staging/abandoned/upload")
        self.age(self.root / ".staging" / "abandoned")
        self.write(".staging/active/old-part")
        self.write(".staging/active/new-part", RECENT)
        self.age(self.root / ".staging" / "active")

        removed = self.cleanup()

        self.assertEqual(removed, [".staging/abandoned"])
        self.assertFalse((self.root / ".staging" / "abandoned").exists())
        self.assertTrue((self.root / ".staging" / "active" / "old-part").exists())

    def test_other_directories_and_nested_folders_are_left_alone(self):
        generated = self.write("generated/report.json")
        nested = self.root / "originals" / "folder"
        nested.mkdir(parents=True)
        self.age(nested)
        stray = self.write(".staging/stray-file")

        self.assertEqual(self.cleanup(), [])
        self.assertTrue(generated.exists())
        self.assertTrue(nested.exists())
        self.assertTrue(stray.exists())

    def test_symbolic_link_is_removed_without_touching_its_target(self):
        target = self.write("outside/secret.pdf")
        link = self.root / "originals" / "link.pdf"
        link.parent.mkdir(parents=True)
        try:
            link.symlink_to(target)
        except OSError:
            self.skipTest("Symbolic links are not available.")
        os.utime(link, (OLD, OLD), follow_symlinks=False)

        self.assertEqual(self.cleanup(), ["originals/link.pdf"])
        self.assertFalse(link.is_symlink())
        self.assertTrue(target.exists())

    def test_missing_storage_directories_are_not_an_error(self):
        self.assertEqual(self.cleanup(), [])

    def test_cleanup_holds_the_originals_lock_exclusively(self):
        self.cleanup()
        self.assertEqual(self.connection.statements[0], ("SELECT pg_advisory_xact_lock(%s)", (ORIGINALS_LOCK,)))

    def test_recent_or_naive_cutoffs_are_rejected_before_connecting(self):
        orphan = self.write("originals/orphan.pdf")
        for cutoff in (NOW - timedelta(minutes=30), datetime.now() - timedelta(hours=2)):
            with self.subTest(cutoff=cutoff):
                pool = Mock()
                with self.assertRaises(ValueError):
                    PostgresDocumentCleanup(pool, self.root).cleanup_orphaned_files(cutoff)
                pool.connection.assert_not_called()
        self.assertTrue(orphan.exists())


if __name__ == "__main__":
    unittest.main()
