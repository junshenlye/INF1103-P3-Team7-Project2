"""Each model package must import cleanly on its own, in a fresh interpreter.

Tests in this process share already-imported modules, so a circular import
can stay hidden by whichever test happens to load first. A subprocess starts
with nothing imported.
"""

from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = (
    "src.config",
    "src.models.assessments",
    "src.models.documents",
    "src.models.processing",
    "src.models.projects",
    "src.serialization",
)


class ImportOrderTests(unittest.TestCase):
    def test_each_package_imports_first_without_a_cycle(self):
        for package in PACKAGES:
            with self.subTest(package=package):
                result = subprocess.run(
                    [sys.executable, "-B", "-c", f"import {package}"],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
