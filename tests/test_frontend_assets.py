"""Verify the browser workspace ships its entry pages and static modules."""

from pathlib import Path
import unittest


FRONTEND = Path(__file__).parents[1] / "frontend"


class FrontendAssetTests(unittest.TestCase):
    def test_workspace_pages_and_modules_are_present(self):
        for path in ("templates/index.html", "templates/documents.html", "static/app.js", "static/api.js", "static/styles.css"):
            with self.subTest(path=path):
                self.assertTrue((FRONTEND / path).is_file())

    def test_container_files_expose_the_application_port(self):
        root = FRONTEND.parent
        self.assertIn("src.main:create_app", (root / "Dockerfile").read_text())
        self.assertIn("5173", (root / "compose.yaml").read_text())


if __name__ == "__main__":
    unittest.main()
