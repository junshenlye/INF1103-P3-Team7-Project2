import tempfile
import unittest
from pathlib import Path

from src.errors.error_codes import INVALID_STORAGE_KEY
from src.errors.processing_error import ProcessingError
from src.storage.document_keys import resolve_document_key


class DocumentStorageKeyTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve() / "storage"
        self.root.mkdir()

    def test_resolves_known_storage_directories_and_nested_keys(self):
        for key in (".staging", "originals/module-1/source.pdf", "generated/output"):
            with self.subTest(key=key):
                self.assertEqual(resolve_document_key(self.root, key), self.root / key)

    def test_rejects_malformed_keys(self):
        for key in (
            None,
            "",
            "unknown/source.pdf",
            "/originals/source.pdf",
            "originals/../../source.pdf",
            "originals/./source.pdf",
            "originals//source.pdf",
            "originals\\source.pdf",
            "C:/originals/source.pdf",
            "originals/source.pdf:stream",
            "originals/source\x00.pdf",
        ):
            with self.subTest(key=key):
                with self.assertRaises(ProcessingError) as error:
                    resolve_document_key(self.root, key)
                self.assertEqual(error.exception.code, INVALID_STORAGE_KEY)
                self.assertEqual(error.exception.scope, "document")

    def test_rejects_symlink_escaping_storage_root(self):
        outside = self.root.parent / "outside"
        outside.mkdir()
        try:
            (self.root / "originals").symlink_to(outside, target_is_directory=True)
        except (NotImplementedError, OSError):
            self.skipTest("Creating directory symlinks is unavailable")

        with self.assertRaises(ProcessingError) as error:
            resolve_document_key(self.root, "originals/source.pdf")
        self.assertEqual(error.exception.code, INVALID_STORAGE_KEY)
