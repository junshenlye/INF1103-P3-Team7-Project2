"""Tests for environment-backed runtime configuration."""

import unittest
from pathlib import Path

from src.config import Settings, load_settings


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.env = {"DATABASE_URL": "postgresql://user:pass@localhost/app"}

    def test_loads_defaults(self):
        settings = load_settings(self.env)
        self.assertEqual(settings.document_directory, Path("/data/documents"))
        self.assertEqual(settings.database_pool_size, 4)
        self.assertEqual(settings.gpt_concurrency, 2)
        self.assertEqual(settings.document_workers, 3)

    def test_supports_legacy_and_current_provider_variable_names(self):
        settings = load_settings({**self.env, "OPENAI_API_KEY": "legacy-key", "GPT_MODEL": "current"})
        self.assertEqual(settings.gpt_api_key, "legacy-key")
        self.assertEqual(settings.gpt_model, "current")

    def test_current_provider_variables_take_precedence(self):
        settings = load_settings({**self.env, "OPENAI_API_KEY": "old", "GPT_API_KEY": "new", "OPENAI_MODEL": "old-model", "GPT_MODEL": "new-model"})
        self.assertEqual(settings.gpt_api_key, "new")
        self.assertEqual(settings.gpt_model, "new-model")

    def test_reads_worker_and_storage_overrides(self):
        settings = load_settings({**self.env, "DOCUMENT_DIRECTORY": "/tmp/docs", "DATABASE_POOL_SIZE": "8", "GPT_CONCURRENCY": "4", "DOCUMENT_WORKERS": "5"})
        self.assertEqual(settings.document_directory, Path("/tmp/docs"))
        self.assertEqual(settings.database_pool_size, 8)
        self.assertEqual(settings.gpt_concurrency, 4)
        self.assertEqual(settings.document_workers, 5)

    def test_rejects_non_postgres_database_url(self):
        with self.assertRaisesRegex(ValueError, "PostgreSQL"):
            Settings(database_url="sqlite:///app.db")

    def test_rejects_relative_document_directory(self):
        with self.assertRaisesRegex(ValueError, "absolute path"):
            Settings(database_url=self.env["DATABASE_URL"], document_directory=Path("docs"))

    def test_rejects_out_of_range_worker_counts(self):
        for field in ("database_pool_size", "gpt_concurrency", "document_workers"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                Settings(database_url=self.env["DATABASE_URL"], **{field: 0})

    def test_rejects_non_http_provider_urls(self):
        with self.assertRaisesRegex(ValueError, "absolute HTTP"):
            Settings(database_url=self.env["DATABASE_URL"], docling_url="ftp://docling:5001")


if __name__ == "__main__":
    unittest.main()
