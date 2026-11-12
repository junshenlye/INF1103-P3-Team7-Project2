"""Build the provider response schema for assessment extraction."""

from src.config import limits
from src.errors import error_codes
from src.errors.processing_error import ProcessingError


def extraction_response_format(chunk):
    """Provider wire shape; domain validation remains authoritative."""
    source_ids = sorted({element.id for element in chunk})
    if (
        not source_ids
        or sum(map(len, source_ids)) > limits.GPT_SOURCE_ID_CHARACTERS
    ):
        raise ProcessingError(
            error_codes.DOCUMENT_PARSE_FAILED,
            "Source citations exceed the supported extraction bounds.",
            "document",
        )
    evidence = {
        field: {"type": "array", "items": {"$ref": "#/$defs/source_id"}}
        for field in sorted(limits.FACT_FIELDS)
    }
    facts = {
        "key": {"type": "string"},
        "name": {"type": "string"},
        "kind": {"type": "string", "enum": ["assessment", "group"]},
        "weight_percent": {"type": ["number", "null"]},
        "weight_scope": {"type": "string", "enum": ["module", "group", "unknown"]},
        "week": {"type": ["integer", "null"]},
        "end_week": {"type": ["integer", "null"]},
        "parent_key": {"type": ["string", "null"]},
        "evidence": {
            "type": "object",
            "properties": evidence,
            "required": list(evidence),
            "additionalProperties": False,
        },
    }
    result = {
        "module_title": {"type": "string"},
        "assessments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": facts,
                "required": list(facts),
                "additionalProperties": False,
            },
        },
        "uncertainties": {"type": "array", "items": {"type": "string"}},
    }
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "assessment_extraction",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": result,
                "required": list(result),
                "additionalProperties": False,
                "$defs": {"source_id": {"type": "string", "enum": source_ids}},
            },
        },
    }
