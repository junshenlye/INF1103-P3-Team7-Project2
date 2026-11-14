"""Keep the runtime dependency and environment template aligned with the app."""

from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]


class RuntimeDependencyTests(unittest.TestCase):
    def test_runtime_requirements_cover_the_configured_services(self):
        requirements = (ROOT / "requirements.txt").read_text().splitlines()

        for dependency in ("fastapi", "psycopg[binary,pool]", "httpx"):
            with self.subTest(dependency=dependency):
                self.assertTrue(any(line.startswith(dependency) for line in requirements))

    def test_environment_template_contains_required_database_and_provider_settings(self):
        values = (ROOT / ".env.example").read_text()

        for name in ("DATABASE_URL", "DOCUMENT_DIRECTORY", "GPT_BASE_URL", "DOCLING_URL"):
            with self.subTest(name=name):
                self.assertIn(f"{name}=", values)


if __name__ == "__main__":
    unittest.main()
