"""Tests for the assessment extraction response schema."""

import unittest
from unittest.mock import patch

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
