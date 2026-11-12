import unittest
from src.errors.processing_error import ProcessingError
from src.managers import LogicManager


class LogicManagerTests(unittest.TestCase):
    def setUp(self): self.logic = LogicManager()
    def test_normalizes_valid_project_and_submission(self):
        project = self.logic.validate_project({"name": "  Trimester  ", "week_count": 14})
        modules = self.logic.validate_submission([{"module_title": "  Software   Engineering ", "credit": 4, "file_fields": ["brief"]}], ["brief"])
        self.assertEqual((project.name, modules[0].normalized_title), ("Trimester", "software engineering"))
    def test_rejects_duplicate_titles_and_unassigned_uploads(self):
        with self.assertRaises(ProcessingError): self.logic.validate_submission([{"module_title": "A", "credit": 1, "file_fields": ["one"]}, {"module_title": " a ", "credit": 1, "file_fields": ["two"]}], ["one", "two"])
        with self.assertRaises(ProcessingError): self.logic.validate_submission([{"module_title": "A", "credit": 1, "file_fields": ["one"]}], ["two"])
