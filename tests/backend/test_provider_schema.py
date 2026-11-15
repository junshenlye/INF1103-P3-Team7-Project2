"""Provider wire contracts reject bad citations without relaxing domain rules."""

import asyncio
import json
from uuid import uuid4

import httpx
from jsonschema import Draft202012Validator, ValidationError
import pytest

from src.config import limits
from src.config.settings import Settings
from src.errors.processing_error import ProcessingError
from src.managers.ai_manager import AIManager
from src.managers.logic_manager import LogicManager
from src.models.documents.source_element import SourceElement
from src.models.projects.module import Module


def source():
    return SourceElement(
        str(uuid4()), "document", "parse", "Final exam in Week 12", [], "paragraph"
    ).to_record()


def manager(tmp_path, **settings):
    return AIManager(
        None,
        LogicManager(),
        None,
        None,
        Settings("postgresql://local/schema_test", tmp_path, **settings),
    )


def candidate(source_id):
    facts = {
        "key": "exam",
        "name": "Final exam",
        "kind": "assessment",
        "weight_percent": 60,
        "weight_scope": "module",
        "week": 12,
        "end_week": None,
        "parent_key": None,
    }
    return {
        "module_title": "INF1103",
        "assessments": [
            {
                **facts,
                "evidence": {
                    field: [source_id] if facts[field] is not None else []
                    for field in limits.FACT_FIELDS
                },
            }
        ],
        "uncertainties": [],
    }


def test_schema_accepts_complete_facts_and_explicit_unknowns(tmp_path):
    element = source()
    response_format = manager(tmp_path)._extraction_response_format([element])
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True
    schema = response_format["json_schema"]["schema"]
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    result = candidate(element['id'])
    validator.validate(result)
    for field in ("weight_percent", "week", "end_week", "parent_key"):
        result["assessments"][0][field] = None
        result["assessments"][0]["evidence"][field] = []
    result["assessments"][0]["weight_scope"] = "unknown"
    validator.validate(result)
    result[
        "assessments"
    ] = []  # A chunk without assessments is a valid provider response.
    validator.validate(result)


@pytest.mark.parametrize(
    "fault",
    [
        "citation_string",
        "citation_object",
        "foreign_id",
        "numeric_id",
        "extra_evidence",
        "missing_evidence_field",
        "missing_fact",
        "extra_fact",
        "invalid_kind",
        "missing_root",
    ],
)
def test_schema_rejects_malformed_or_foreign_citations(tmp_path, fault):
    element = source()
    schema = manager(tmp_path)._extraction_response_format([element])["json_schema"][
        "schema"
    ]
    result = candidate(element['id'])
    fact = result["assessments"][0]
    if fault == "citation_string":
        fact["evidence"]["name"] = element['id']
    elif fault == "citation_object":
        fact["evidence"]["name"] = [{"id": element['id']}]
    elif fault == "foreign_id":
        fact["evidence"]["name"] = [str(uuid4())]
    elif fault == "numeric_id":
        fact["evidence"]["name"] = [1]
    elif fault == "extra_evidence":
        fact["evidence"]["page"] = [element['id']]
    elif fault == "missing_evidence_field":
        del fact["evidence"]["end_week"]
    elif fault == "missing_fact":
        del fact["week"]
    elif fault == "extra_fact":
        fact["qualification"] = "tentative"
    elif fault == "invalid_kind":
        fact["kind"] = "other"
    else:
        del result["module_title"]
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(result)


@pytest.mark.parametrize("fault", ["missing_support", "invalid_week", "invalid_weight"])
def test_strict_wire_shape_does_not_replace_domain_validation(tmp_path, fault):
    element = source()
    schema = manager(tmp_path)._extraction_response_format([element])["json_schema"][
        "schema"
    ]
    result = candidate(element['id'])
    fact = result["assessments"][0]
    if fault == "missing_support":
        fact["evidence"]["name"] = []
    elif fault == "invalid_week":
        fact["week"] = 99
    else:
        fact["weight_percent"] = 150
    Draft202012Validator(schema).validate(result)
    logic = LogicManager()
    module = logic.validate_submission(
        [{"module_title": "INF1103", "credit": 6, "file_fields": ["file"]}],
        {"file": object()},
    )[0]
    module = Module('m', 'p', 'j', module['module_title'], module['normalized_title'], module['credit'], 0)
    with pytest.raises(ProcessingError):
        logic.validate_extraction(result, module, {element['id']}, 14)


def test_chunking_respects_provider_enum_budget_at_maximum_byte_bound(tmp_path):
    ai = manager(tmp_path, chunk_bytes=limits.MAX_CHUNK_BYTES)
    elements = [source() for _ in range(600)]
    chunks = ai._make_chunks(elements)
    assert len(chunks) > 1
    assert [e['id'] for chunk in chunks for e in chunk] == [e['id'] for e in elements]
    for chunk in chunks:
        schema = ai._extraction_response_format(chunk)["json_schema"]["schema"]
        ids = schema["$defs"]["source_id"]["enum"]
        assert set(ids) == {e['id'] for e in chunk}
        assert sum(map(len, ids)) <= limits.GPT_SOURCE_ID_CHARACTERS
        assert len(ids) + 5 <= 1000  # Source IDs plus kind and scope enum values.
        Draft202012Validator.check_schema(schema)
        # Shared definitions avoid repeating the UUID enum for every evidence field.
        assert json.dumps(schema).count(ids[0]) == 1


def test_refusal_is_safe_and_never_retried(tmp_path):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "refusal": "private provider reason",
                            "content": json.dumps(candidate(element['id'])),
                        },
                    }
                ]
            },
        )

    element = source()

    async def run():
        async with httpx.AsyncClient(
            base_url="http://provider", transport=httpx.MockTransport(respond)
        ) as client:
            ai = manager(tmp_path, gpt_api_key="fake", gpt_model="fake")
            ai._gpt = client
            with pytest.raises(ProcessingError) as error:
                await ai._call_gpt("INF1103", [element])
            assert error.value.code == "invalid_extraction"
            assert "private" not in error.value.message

    asyncio.run(run())
    assert len(calls) == 1


def test_schema_rejection_does_not_fall_back_to_unconstrained_json(tmp_path):
    calls = []

    def respond(request):
        calls.append(json.loads(request.content))
        return httpx.Response(400, json={"error": {"message": "unsupported schema"}})

    async def run():
        async with httpx.AsyncClient(
            base_url="http://provider", transport=httpx.MockTransport(respond)
        ) as client:
            ai = manager(tmp_path, gpt_api_key="fake", gpt_model="fake")
            ai._gpt = client
            with pytest.raises(httpx.HTTPStatusError):
                await ai._call_gpt("INF1103", [source()])

    asyncio.run(run())
    assert len(calls) == 1 and calls[0]["response_format"]["type"] == "json_schema"
