"""Tests for the assessment extraction response schema."""

import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator, ValidationError

from src.config import limits
from src.errors.error_codes import DOCUMENT_PARSE_FAILED
from src.errors.processing_error import ProcessingError
from src.models.documents.source_element import SourceElement
from src.processing.extraction_schema import extraction_response_format


def source(source_id):
    return SourceElement(source_id, "document", "parse", "An assessment", [], "paragraph")


class ExtractionSchemaTests(unittest.TestCase):
    def test_requires_known_fields_and_only_accepts_citations_from_the_chunk(self):
        response_format = extraction_response_format([source("b"), source("a"), source("a")])
        self.assertEqual(response_format["type"], "json_schema")
        self.assertTrue(response_format["json_schema"]["strict"])

        schema = response_format["json_schema"]["schema"]
        self.assertEqual(schema["$defs"]["source_id"], {"type": "string", "enum": ["a", "b"]})
        self.assertEqual(set(schema["required"]), {"module_title", "assessments", "uncertainties"})

        assessment = schema["properties"]["assessments"]["items"]
        self.assertEqual(set(assessment["required"]), limits.FACT_FIELDS | {"key", "evidence"})
        self.assertIn("null", assessment["properties"]["week"]["type"])
        evidence = assessment["properties"]["evidence"]
        self.assertEqual(set(evidence["required"]), limits.FACT_FIELDS)
        for node in (schema, assessment, evidence):
            self.assertFalse(node["additionalProperties"])
        for field in evidence["properties"].values():
            self.assertEqual(field, {"type": "array", "items": {"$ref": "#/$defs/source_id"}})

    def test_generated_schema_is_valid_and_rejects_foreign_citations(self):
        schema = extraction_response_format([source("source-a")])["json_schema"]["schema"]
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        result = {
            "module_title": "INF1103",
            "assessments": [{
                "key": "exam",
                "name": "Final exam",
                "kind": "assessment",
                "weight_percent": 60,
                "weight_scope": "module",
                "week": 12,
                "end_week": None,
                "parent_key": None,
                "evidence": {
                    "name": ["source-a"],
                    "kind": ["source-a"],
                    "weight_percent": ["source-a"],
                    "weight_scope": ["source-a"],
                    "week": ["source-a"],
                    "end_week": [],
                    "parent_key": [],
                },
            }],
            "uncertainties": [],
        }
        validator.validate(result)
        result["assessments"][0]["evidence"]["name"] = ["not-in-this-chunk"]
        with self.assertRaises(ValidationError):
            validator.validate(result)

    def test_enforces_citation_budget_after_deduplicating_ids(self):
        with patch.object(limits, "GPT_SOURCE_ID_CHARACTERS", 4):
            extraction_response_format([source("abcd"), source("abcd")])
            with self.assertRaises(ProcessingError) as caught:
                extraction_response_format([source("ab"), source("cde")])
        self.assertEqual(caught.exception.code, DOCUMENT_PARSE_FAILED)
        self.assertEqual(caught.exception.scope, "document")

    def test_rejects_empty_source_chunks(self):
        with self.assertRaises(ProcessingError) as caught:
            extraction_response_format([])
        self.assertEqual(caught.exception.code, DOCUMENT_PARSE_FAILED)
