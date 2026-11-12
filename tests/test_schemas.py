"""Tests for HTTP request and response data shapes."""

from dataclasses import FrozenInstanceError, asdict
import json
import unittest

from src.schemas import (
    CreateProjectRequest,
    ErrorResponse,
    JobStatusResponse,
    ProjectResponse,
    SubmitModuleRequest,
)


class RequestSchemaTests(unittest.TestCase):
    def test_create_project_request_keeps_validated_values(self):
        request = CreateProjectRequest("Trimester 1", 13)
        self.assertEqual(asdict(request), {"name": "Trimester 1", "week_count": 13})

    def test_submit_module_request_keeps_titles_credit_and_fields(self):
        request = SubmitModuleRequest("INF1103 DevOps", "inf1103 devops", 6, ("file_0", "file_1"))
        self.assertEqual(request.normalized_title, "inf1103 devops")
        self.assertEqual(request.file_fields, ("file_0", "file_1"))


class ResponseSchemaTests(unittest.TestCase):
    def test_error_response_serialises_issues(self):
        issue = {"code": "invalid_request", "message": "Bad input.", "scope": "request"}
        self.assertEqual(json.loads(json.dumps(asdict(ErrorResponse([issue])))), {"issues": [issue]})

    def test_job_status_response_fields(self):
        response = JobStatusResponse("j1", "p1", "Processing", "parsing", [], {"done": 1, "total": 3})
        self.assertEqual(asdict(response)["progress"], {"done": 1, "total": 3})

    def test_project_response_defaults_describe_an_unprocessed_project(self):
        response = ProjectResponse("p1", "T1", 13, "Created", None, [], None, [])
        self.assertEqual(
            {
                key: value
                for key, value in asdict(response).items()
                if key
                in (
                    "processing_status",
                    "coverage",
                    "documents",
                    "schedule_revision_id",
                    "stale",
                    "event_cursor",
                )
            },
            {
                "processing_status": "idle",
                "coverage": "none",
                "documents": None,
                "schedule_revision_id": None,
                "stale": False,
                "event_cursor": 0,
            },
        )
        json.dumps(asdict(response))

    def test_schemas_are_immutable(self):
        shapes = (
            CreateProjectRequest("T1", 13),
            SubmitModuleRequest("A", "a", 6, ()),
            ErrorResponse([]),
            JobStatusResponse("j", "p", "Created", "queued", [], {}),
            ProjectResponse("p", "T1", 13, "Created", None, [], None, []),
        )
        for shape in shapes:
            with self.subTest(schema=type(shape).__name__):
                with self.assertRaises(FrozenInstanceError):
                    setattr(shape, "extra", 1)


if __name__ == "__main__":
    unittest.main()
