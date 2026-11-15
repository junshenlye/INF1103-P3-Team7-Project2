import asyncio
from dataclasses import replace
import json
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from src.config import limits
from src.main import create_app
from src.managers.ai_manager import AIManager
from src.managers.logic_manager import LogicManager
from test_api import create, submit
from test_storage import image_bytes


def parsed(text="Final exam in Week 12, worth 60% of the module."):
    return {
        "status": "success",
        "document": {
            "json_content": {
                "pages": {"1": {"size": {"width": 100, "height": 100}}},
                "texts": [
                    {
                        "text": text,
                        "label": "paragraph",
                        "prov": [
                            {
                                "page_no": 1,
                                "bbox": {
                                    "l": 0,
                                    "t": 10,
                                    "r": 100,
                                    "b": 0,
                                    "coord_origin": "BOTTOMLEFT",
                                },
                            }
                        ],
                    }
                ],
                "tables": [],
            }
        },
    }


def parsed_table():
    """A real table-shaped provider payload, with separately addressable fields."""
    from test_logic import table_parse

    result = parsed()
    content = table_parse()
    cells = content["tables"][0]["data"]["table_cells"]
    replacements = {"Task": "Assessment", "Weight": "Weight (% of module)",
                    "Quiz": "Final exam", "25%": "60%", "Week 4": "Week 12"}
    for cell in cells:
        cell["text"] = replacements.get(cell["text"], cell["text"])
    result["document"]["json_content"] = content
    return result


def extraction(request, mode="success"):
    payload = json.loads(request.content)
    user = json.loads(payload["messages"][1]["content"])
    sources = user["source_elements"]
    source_id = sources[0]["id"]
    fact = {
        "key": "exam",
        "name": "Final exam",
        "kind": "assessment",
        "weight_percent": 60,
        "weight_scope": "module",
        "week": 12,
        "end_week": None,
        "parent_key": None,
    }
    evidence = {
        field: [source_id] if fact[field] is not None else []
        for field in limits.FACT_FIELDS
    }
    if mode == "table":
        by_text = {element["text"]: element["id"] for element in sources}
        evidence.update({
            "name": [by_text["Final exam"]],
            "kind": [by_text["Final exam"]],
            "week": [by_text["Week 12"]],
            "weight_percent": [by_text["60%"]],
            "weight_scope": [by_text["Weight (% of module)"]],
        })
    if mode == "missing_evidence":
        evidence["week"] = [str(uuid4())]
    if mode == "invalid_week":
        fact["week"] = 99
    result = {
        "module_title": user["module_title"],
        "assessments": [{**fact, "evidence": evidence}],
        "uncertainties": [],
    }
    if mode == "empty":
        result["assessments"] = []
    if mode == "invalid_shape":
        result = {"secret": "/tmp/credential"}
    return httpx.Response(
        200,
        json={
            "choices": [
                {"finish_reason": "stop", "message": {"content": json.dumps(result)}}
            ]
        },
    )


async def process(data, settings, mode="success", doc_mode="success", counter=None):
    settings = replace(
        settings, gpt_api_key="test-only-not-a-secret", gpt_model="fake-extractor"
    )

    def doc(request):
        if counter is not None:
            counter["doc"] += 1
        if doc_mode == "failure":
            return httpx.Response(
                200, json={"status": "failure", "errors": ["secret /tmp/provider"]}
            )
        if doc_mode == "unavailable":
            return httpx.Response(503, text="password-secret")
        if doc_mode == "oversized":
            return httpx.Response(
                200, json=parsed("X" * (settings.chunk_bytes * settings.max_chunks + 1))
            )
        return httpx.Response(200, json=parsed_table() if mode == "table" else parsed())

    def gpt(request):
        if counter is not None:
            counter["gpt"] += 1
        if mode == "unavailable":
            return httpx.Response(503, text="credentials-secret")
        if mode == "malformed":
            return httpx.Response(200, content=b"not JSON /tmp/secret")
        return extraction(request, mode)

    async with (
        httpx.AsyncClient(
            base_url="http://docling", transport=httpx.MockTransport(doc)
        ) as dc,
        httpx.AsyncClient(
            base_url="http://gpt/v1", transport=httpx.MockTransport(gpt)
        ) as gc,
    ):
        return await AIManager(
            data, LogicManager(), dc, gc, settings
        ).process_next_job()


def test_end_to_end_upload_storage_worker_schedule_and_evidence(data, settings):
    client = TestClient(create_app(settings, data))
    pid = create(client)
    key = str(uuid4())
    accepted = submit(client, pid, key)
    jid = accepted.json()["job_id"]
    counter = {"doc": 0, "gpt": 0}
    assert asyncio.run(process(data, settings, counter=counter)) is True
    assert client.get(f"/api/jobs/{jid}").json()["status"] == "Ready"
    project = client.get(f"/api/projects/{pid}").json()
    assert project["status"] == "Ready"
    item = project["schedule"]["weeks"][11]["items"][0]
    assert item["name"] == "Final exam" and item["weight_percent"] == 60
    result = client.get(f"/api/results/{item['result_id']}").json()
    assert len(result["assessments"]) == 1
    document = data.get_module_documents(jid, item["module_id"])[0]
    trace = client.get(f"/api/documents/{document.id}/trace").json()
    assert item["evidence"]["week"][0] in {e["id"] for e in trace["elements"]}
    original = client.get(f"/api/documents/{document.id}/original")
    assert (
        original.content == image_bytes()
        and original.headers["x-content-type-options"] == "nosniff"
    )
    assert "storage_key" not in json.dumps(project) and str(
        data.root
    ) not in json.dumps(project)
    assert submit(client, pid, key).json()["job_id"] == jid
    assert asyncio.run(process(data, settings, counter=counter)) is False
    assert counter == {"doc": 1, "gpt": 1}
    assert client.get(f"/api/projects/{pid}").json() == project


def test_cell_evidence_survives_upload_storage_worker_and_schedule(data, settings):
    client = TestClient(create_app(settings, data))
    pid = create(client)
    submit(client, pid, str(uuid4()))
    counter = {"doc": 0, "gpt": 0}
    assert asyncio.run(process(data, settings, mode="table", counter=counter))
    project = client.get(f"/api/projects/{pid}").json()
    assert project["status"] == "Ready"
    item = project["schedule"]["weeks"][11]["items"][0]
    doc = data.get_module_documents(project["job_id"], item["module_id"])[0]
    trace = client.get(f"/api/documents/{doc.id}/trace").json()
    sources = {e["id"]: e for e in trace["elements"]}
    expected = {"name": "Final exam", "week": "Week 12", "weight_percent": "60%"}
    cited = [item["evidence"][field][0] for field in expected]
    assert len(set(cited)) == 3
    assert len(sources) == 6
    for field, value in expected.items():
        source = sources[item["evidence"][field][0]]
        assert source["text"] == value
        assert source["regions"][0]["granularity"] == "cell"
    assert client.get(f"/api/documents/{doc.id}/original").content == image_bytes()
    assert counter == {"doc": 1, "gpt": 1}


@pytest.mark.parametrize(
    "mode,doc_mode,expected",
    [
        ("unavailable", "success", "provider_unavailable"),
        ("malformed", "success", "invalid_extraction"),
        ("missing_evidence", "success", "invalid_extraction"),
        ("invalid_week", "success", "invalid_extraction"),
        ("empty", "success", "no_assessments"),
        ("invalid_shape", "success", "invalid_extraction"),
        ("success", "failure", "document_parse_failed"),
        ("success", "unavailable", "provider_unavailable"),
        ("success", "oversized", "document_parse_failed"),
    ],
)
def test_failures_are_terminal_safe_and_publish_nothing(
    data, settings, mode, doc_mode, expected
):
    client = TestClient(create_app(settings, data))
    pid = create(client)
    accepted = submit(client, pid)
    assert accepted.status_code == 202
    counter = {"doc": 0, "gpt": 0}
    asyncio.run(process(data, settings, mode, doc_mode, counter))
    response = client.get(f"/api/projects/{pid}")
    project = response.json()
    assert project["status"] == "Failed" and project["schedule"] is None
    assert project["issues"][0]["code"] == expected, response.text
    assert "secret" not in response.text and "/tmp" not in response.text
    assert project["issues"][0]["module_id"] is not None
    assert asyncio.run(process(data, settings, counter=counter)) is False
    assert submit(client, pid).status_code == 409
    assert counter['doc'] == (3 if doc_mode == 'unavailable' else 1)
    expected_gpt = 0 if doc_mode != 'success' else 3 if mode == 'unavailable' else 1 if mode == 'empty' else 2
    assert counter['gpt'] == expected_gpt
    assert data.get_published_results(pid) == []


def test_missing_original_before_processing_fails(data, settings):
    client = TestClient(create_app(settings, data))
    pid = create(client)
    jid = submit(client, pid).json()["job_id"]
    doc = data.get_module_documents(jid, data.get_job_modules(jid)[0].id)[0]
    (data.root / doc.storage_key).unlink()
    asyncio.run(process(data, settings))
    project = client.get(f"/api/projects/{pid}").json()
    assert (
        project["status"] == "Failed"
        and project["issues"][0]["code"] == "source_missing"
    )


def test_ready_integrity_warning_keeps_schedule_and_parsed_evidence(data, settings):
    client = TestClient(create_app(settings, data))
    pid = create(client)
    jid = submit(client, pid).json()["job_id"]
    asyncio.run(process(data, settings))
    before = client.get(f"/api/projects/{pid}").json()
    doc = data.get_module_documents(jid, data.get_job_modules(jid)[0].id)[0]
    (data.root / doc.storage_key).unlink()
    after = client.get(f"/api/projects/{pid}").json()
    assert after["status"] == "Ready" and after["schedule"] == before["schedule"]
    assert (
        len(after["issues"]) == 1
        and after["issues"][0]["code"] == "source_missing"
        and after["issues"][0]["severity"] == "warning"
    )
    assert client.get(f"/api/projects/{pid}").json()["issues"] == after["issues"]
    assert client.get(f"/api/documents/{doc.id}/original").status_code == 422
    assert client.get(f"/api/documents/{doc.id}/trace").status_code == 200


def test_worker_cancellation_is_terminal(data, settings):
    client = TestClient(create_app(settings, data))
    pid = create(client)
    submit(client, pid)

    async def run():
        started = asyncio.Event()

        async def doc(request):
            started.set()
            await asyncio.Future()

        cfg = replace(settings, gpt_api_key="fake", gpt_model="fake")
        async with (
            httpx.AsyncClient(
                base_url="http://doc", transport=httpx.MockTransport(doc)
            ) as dc,
            httpx.AsyncClient(base_url="http://gpt") as gc,
        ):
            task = asyncio.create_task(
                AIManager(data, LogicManager(), dc, gc, cfg).process_next_job()
            )
            await started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    asyncio.run(run())
    project = client.get(f"/api/projects/{pid}").json()
    assert project["status"] == "Interrupted" and project["schedule"] is None
    assert data.claim_next_job() is None


def test_review_is_append_only_and_schedule_is_derived(data, settings):
    client = TestClient(create_app(settings, data))
    pid = create(client)
    submit(client, pid)
    asyncio.run(process(data, settings))
    before = client.get(f"/api/projects/{pid}").json()
    item = before["schedule"]["weeks"][11]["items"][0]
    endpoint = (
        f"/api/results/{item['result_id']}/assessments/{item['assessment_id']}/reviews"
    )
    response = client.post(
        endpoint, json={"expected_revision": 0, "changes": {"week": 10}}
    )
    assert response.status_code == 201, response.text
    after = client.get(f"/api/projects/{pid}").json()
    assert (
        not after["schedule"]["weeks"][11]["items"]
        and after["schedule"]["weeks"][9]["items"][0]["revision"] == 1
    )
    assert (
        client.post(
            endpoint, json={"expected_revision": 0, "changes": {"week": 9}}
        ).status_code
        == 409
    )
    with data.pool.connection() as c:
        original = c.execute(
            "SELECT facts FROM assessments WHERE id=%s", (item["assessment_id"],)
        ).fetchone()
        assert original["facts"]["week"] == 12
        assert (
            c.execute("SELECT count(*) AS n FROM review_revisions").fetchone()["n"] == 1
        )


def test_unknown_fact_review_requires_registered_evidence_and_no_processing_retry(
    data, settings
):
    client = TestClient(create_app(settings, data))
    pid = create(client)
    accepted = submit(client, pid)

    async def run():
        def doc(_request):
            return httpx.Response(200, json=parsed())

        def gpt(request):
            response = extraction(request)
            wire = json.loads(response.content)
            raw = json.loads(wire["choices"][0]["message"]["content"])
            raw["assessments"][0]["week"] = None
            raw["assessments"][0]["evidence"].pop("week")
            wire["choices"][0]["message"]["content"] = json.dumps(raw)
            return httpx.Response(200, json=wire)

        async with (
            httpx.AsyncClient(
                base_url="http://doc", transport=httpx.MockTransport(doc)
            ) as dc,
            httpx.AsyncClient(
                base_url="http://gpt", transport=httpx.MockTransport(gpt)
            ) as gc,
        ):
            await AIManager(
                data,
                LogicManager(),
                dc,
                gc,
                replace(settings, gpt_api_key="fake", gpt_model="fake"),
            ).process_next_job()

    asyncio.run(run())
    before = client.get(f"/api/projects/{pid}").json()
    item = before["schedule"]["unscheduled"][0]
    endpoint = (
        f"/api/results/{item['result_id']}/assessments/{item['assessment_id']}/reviews"
    )
    assert (
        client.post(
            endpoint, json={"expected_revision": 0, "changes": {"week": 12}}
        ).status_code
        == 422
    )
    source_id = item["evidence"]["name"][0]
    response = client.post(
        endpoint,
        json={
            "expected_revision": 0,
            "changes": {"week": 12},
            "evidence": {"week": [source_id]},
        },
    )
    assert response.status_code == 201, response.text
    after = client.get(f"/api/projects/{pid}").json()
    assert not after["schedule"]["unscheduled"]
    assert after["schedule"]["weeks"][11]["items"][0]["evidence"]["week"] == [source_id]
    assert (
        after["job_id"] == accepted.json()["job_id"] and data.claim_next_job() is None
    )


def test_provider_deadline_ends_job_without_holding_a_transaction_or_retry(
    data, settings
):
    client = TestClient(create_app(settings, data))
    pid = create(client)
    submit(client, pid)
    calls = 0

    async def run():
        async def slow_doc(_request):
            nonlocal calls
            calls += 1
            with data.pool.connection() as conn:
                rows = conn.execute(
                    "SELECT count(*) AS n FROM pg_stat_activity WHERE datname=current_database() AND state='idle in transaction'"
                ).fetchone()
                assert rows["n"] == 0
            await asyncio.sleep(1)
            return httpx.Response(200, json=parsed())

        async with (
            httpx.AsyncClient(
                base_url="http://doc", transport=httpx.MockTransport(slow_doc)
            ) as dc,
            httpx.AsyncClient(base_url="http://gpt") as gc,
        ):
            await AIManager(
                data,
                LogicManager(),
                dc,
                gc,
                replace(
                    settings, provider_timeout=0.1, gpt_api_key="fake", gpt_model="fake"
                ),
            ).process_next_job()

    asyncio.run(run())
    project = client.get(f"/api/projects/{pid}").json()
    assert project["status"] == "Failed" and project["schedule"] is None
    assert project["issues"][0]["code"] == "provider_unavailable" and calls == 3


@pytest.mark.parametrize("changes", [{"week": 0}, {"weight_percent": 101}])
def test_postgresql_rejects_invalid_primitive_review_values(data, settings, changes):
    import psycopg
    from psycopg.types.json import Jsonb

    client = TestClient(create_app(settings, data))
    pid = create(client)
    submit(client, pid)
    asyncio.run(process(data, settings))
    item = client.get(f"/api/projects/{pid}").json()["modules"][0]["assessments"][0]
    with data.pool.connection() as conn:
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                "INSERT INTO review_revisions(id,result_id,assessment_id,module_id,revision,facts) VALUES(%s,%s,%s,%s,1,%s)",
                (
                    str(uuid4()),
                    item["result_id"],
                    item["id"],
                    item["module_id"],
                    Jsonb({**item["facts"], **changes}),
                ),
            )
