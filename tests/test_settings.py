"""Regression tests for validated runtime settings and environment loading."""

from dataclasses import FrozenInstanceError
from pathlib import Path
import unittest

from src.config import limits
from src.config.settings import Settings, load_settings


class RuntimeSettingsTests(unittest.TestCase):
    def test_environment_defaults_match_shared_limits(self):
        settings = load_settings({"DATABASE_URL": "postgresql://localhost/project"})

        self.assertEqual(settings.database_url, "postgresql://localhost/project")
        self.assertEqual(settings.document_directory, Path("/data/documents"))
        self.assertEqual(settings.pool_size, limits.POOL_SIZE)
        self.assertEqual(settings.provider_timeout, limits.PROVIDER_TIMEOUT)
        self.assertEqual(settings.lease_seconds, limits.LEASE_SECONDS)
        self.assertEqual(settings.chunk_bytes, limits.CHUNK_BYTES)
        self.assertEqual(settings.max_chunks, limits.CHUNK_COUNT)
        self.assertEqual(settings.gpt_base_url, "https://api.openai.com/v1")

    def test_environment_overrides_and_legacy_provider_aliases(self):
        settings = load_settings({
            "DATABASE_URL": "postgres://db/project",
            "DOCUMENT_DIRECTORY": "/srv/documents",
            "DATABASE_POOL_SIZE": "3",
            "PROVIDER_TIMEOUT": "45.5",
            "JOB_LEASE_SECONDS": "90",
            "CHUNK_BYTES": str(limits.MIN_CHUNK_BYTES),
            "MAX_CHUNKS": "2",
            "OPENAI_API_KEY": "legacy-key",
            "OPENAI_MODEL": "legacy-model",
            "GPT_CONCURRENCY": "4",
            "DOCUMENT_WORKERS": "5",
            "DOCLING_URL": "https://docling.example.test",
        })

        self.assertEqual(settings.document_directory, Path("/srv/documents"))
        self.assertEqual(settings.pool_size, 3)
        self.assertEqual(settings.provider_timeout, 45.5)
        self.assertEqual(settings.lease_seconds, 90)
        self.assertEqual(settings.chunk_bytes, limits.MIN_CHUNK_BYTES)
        self.assertEqual(settings.max_chunks, 2)
        self.assertEqual(settings.gpt_api_key, "legacy-key")
        self.assertEqual(settings.gpt_model, "legacy-model")
        self.assertEqual(settings.gpt_concurrency, 4)
        self.assertEqual(settings.document_workers, 5)
        self.assertEqual(settings.docling_url, "https://docling.example.test")

    def test_explicit_provider_values_take_precedence_over_legacy_aliases(self):
        settings = load_settings({
            "DATABASE_URL": "postgresql://localhost/project",
            "GPT_API_KEY": "current-key",
            "GPT_MODEL": "current-model",
            "OPENAI_API_KEY": "legacy-key",
            "OPENAI_MODEL": "legacy-model",
        })

        self.assertEqual(settings.gpt_api_key, "current-key")
        self.assertEqual(settings.gpt_model, "current-model")

    def test_invalid_configuration_is_rejected(self):
        invalid_values = (
            {"database_url": "https://localhost/project"},
            {"document_directory": Path("relative/documents")},
            {"pool_size": 0},
            {"pool_size": limits.MAX_POOL_SIZE + 1},
            {"lease_seconds": limits.MIN_LEASE_SECONDS - 1},
            {"chunk_bytes": limits.MIN_CHUNK_BYTES - 1},
            {"max_chunks": 0},
            {"provider_timeout": 0},
            {"gpt_concurrency": 9},
            {"document_workers": 0},
            {"gpt_base_url": "ftp://provider.example.test"},
            {"docling_url": "not-a-url"},
        )
        for override in invalid_values:
            with self.subTest(override=override):
                values = {"database_url": "postgresql://localhost/project"}
                values.update(override)
                with self.assertRaises(ValueError):
                    Settings(**values)

    def test_upload_bounds_must_be_positive_and_ordered(self):
        with self.assertRaises(ValueError):
            Settings(
                database_url="postgresql://localhost/project",
                document_bytes=20,
                request_bytes=10,
            )

    def test_settings_are_immutable(self):
        settings = load_settings({"DATABASE_URL": "postgresql://localhost/project"})

        with self.assertRaises(FrozenInstanceError):
            settings.pool_size = 2


if __name__ == "__main__":
    unittest.main()
