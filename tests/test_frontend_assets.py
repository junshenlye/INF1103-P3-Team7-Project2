"""Verify the browser workspace ships its entry pages and static modules."""

from pathlib import Path
import unittest


FRONTEND = Path(__file__).parents[1] / "frontend"


class FrontendAssetTests(unittest.TestCase):
    def test_workspace_pages_and_modules_are_present(self):
        paths = (
            "templates/index.html",
            "templates/documents.html",
            "static/app.js",
            "static/api.js",
            "static/styles.css",
            "static/schedule.css",
        )
        for path in paths:
            with self.subTest(path=path):
                self.assertTrue((FRONTEND / path).is_file())

    def test_schedule_stylesheet_is_loaded_by_the_workspace(self):
        html = (FRONTEND / "templates/index.html").read_text()
        self.assertIn("/static/schedule.css", html)

    def test_container_files_expose_the_application_port(self):
        root = FRONTEND.parent
        self.assertIn("src.main:create_app", (root / "Dockerfile").read_text())
        self.assertIn("5173", (root / "compose.yaml").read_text())


if __name__ == "__main__":
    unittest.main()
