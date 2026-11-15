"""Progress is observed through the real API and SQL at actual worker checkpoints."""
import asyncio
from dataclasses import replace
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from src.main import create_app
from src.managers.ai_manager import AIManager
from src.managers.data_manager import DataManager
from src.managers.logic_manager import LogicManager
from src.errors.processing_error import ProcessingError
from test_api import create, submit
from test_pipeline import parsed, extraction, process
from test_storage import image_bytes


def submit_documents(client):
    pid = create(client)
    response = submit(client, pid, modules=[
        {"module_title": "INF1103", "credit": 6, "file_fields": ["a", "b"]},
        {"module_title": "INF1104", "credit": 6, "file_fields": ["c"]},
    ], files={key: ("brief.png", image_bytes(colour), "image/png")
              for key, colour in [("a", "red"), ("b", "green"), ("c", "blue")]})
    assert response.status_code == 202, response.text
    return pid, response.json()["job_id"]


@pytest.mark.parametrize("fail_at", [None, 2])
def test_checkpoints_counts_and_failure_are_real_and_persistent(data, settings, fail_at):
    client = TestClient(create_app(settings, data))
    pid, jid = submit_documents(client)
    status = lambda: client.get(f"/api/jobs/{jid}").json()
    initial = status()["progress"]
    assert initial["total_documents"] == 3 and initial["extracted_documents"] == 0
    assert [doc["state"] for doc in initial["documents"]] == ["waiting"] * 3
    assert len({doc["document_id"] for doc in initial["documents"]}) == 3
    snapshots = []
    calls = {"reading": 0, "extracting": 0}

    def doc(_request):
        calls['reading'] += 1
        snapshots.append(status())
        return httpx.Response(200, json=parsed())

    def gpt(request):
        import json
        calls['extracting'] += 1
        snapshots.append(status())
        module = json.loads(json.loads(request.content)['messages'][1]['content'])['module_title']
        if fail_at and module == 'INF1104':
            return httpx.Response(503)
        return extraction(request)

    async def run():
        async with (
            httpx.AsyncClient(base_url="http://doc", transport=httpx.MockTransport(doc)) as dc,
            httpx.AsyncClient(base_url="http://gpt", transport=httpx.MockTransport(gpt)) as gc,
        ):
            await AIManager(data, LogicManager(), dc, gc,
                            replace(settings, gpt_api_key="fake", gpt_model="fake")).process_next_job()
    asyncio.run(run())
    terminal = status()
    assert calls == {'reading': 3, 'extracting': 5 if fail_at else 3}
    assert terminal['status'] == ('Partial' if fail_at else 'Ready')
    assert sum(d['state'] == 'extracted' for d in terminal['progress']['documents']) == (2 if fail_at else 3)
    assert terminal['progress']['extracted_documents'] == (2 if fail_at else 3)
    assert 'storage_key' not in str(terminal) and 'lease_token' not in terminal
    fresh = DataManager(data.pool, settings.document_directory, logic_manager=LogicManager())
    assert fresh.get_job(jid)['progress'] == terminal['progress']
    assert client.get(f'/api/projects/{pid}').json()['schedule'] is not None


def test_progress_rejects_wrong_job_stale_claim_and_backwards_updates(data, settings):
    client = TestClient(create_app(settings, data))
    _, jid = submit_documents(client)
    job = data.claim_next_job()
    doc = data.get_job(jid)["progress"]["documents"][0]["document_id"]
    other = submit(client, create(client)).json()["job_id"]
    other_doc = data.get_job(other)["progress"]["documents"][0]["document_id"]
    for document_id, state in [(other_doc, "parsing"), (doc, "extracted")]:
        with pytest.raises(ProcessingError):
            data.save_document_progress(job, document_id, state)
    with pytest.raises(ProcessingError):
        data.save_document_progress(replace(job, lease_token=str(uuid4())), doc, "parsing")
    for state in ["parsing", "extracting", "extracting", "extracted", "extracted"]:
        data.save_document_progress(job, doc, state)
    for state in ["parsing", "extracting"]:
        with pytest.raises(ProcessingError):
            data.save_document_progress(job, doc, state)
    assert data.get_job(jid)["progress"]["extracted_documents"] == 1
    with data.pool.connection() as conn:
        conn.execute("UPDATE processing_jobs SET lease_expires_at=now()-interval '1 second' WHERE id=%s", (jid,))
    with pytest.raises(ProcessingError):
        data.save_document_progress(job, doc, "extracted")


def test_lease_expiry_stops_active_document_without_claiming_it_finished(data, settings):
    client = TestClient(create_app(settings, data))
    _, jid = submit_documents(client)
    job = data.claim_next_job()
    docs = data.get_job(jid)["progress"]["documents"]
    for state in ["parsing", "extracting", "extracted"]:
        data.save_document_progress(job, docs[0]["document_id"], state)
    data.save_document_progress(job, docs[1]["document_id"], "parsing")
    with data.pool.connection() as conn:
        conn.execute("UPDATE processing_jobs SET lease_expires_at=now()-interval '1 second' WHERE id=%s", (jid,))
    assert data.cleanup_interrupted_jobs() == 1
    result = client.get(f"/api/jobs/{jid}").json()
    assert result["status"] == "queued"
    assert [d["state"] for d in result["progress"]["documents"]] == ["waiting", "waiting", "waiting"]
    assert result["progress"]["extracted_documents"] == 0


def test_migration_preserves_legacy_results_without_inventing_checkpoints(data, settings):
    client = TestClient(create_app(settings, data))
    ready = submit(client, create(client)).json()["job_id"]
    asyncio.run(process(data, settings))
    queued = submit(client, create(client)).json()["job_id"]
    job = data.claim_next_job()
    data.fail_job(job, [], interrupted=True)
    waiting = submit(client, create(client)).json()["job_id"]
    with data.pool.connection() as conn:
        conn.execute("DROP TABLE document_progress")
        conn.execute("DELETE FROM schema_migrations WHERE version='005_document_progress.sql'")
    data.create_schema()
    data.create_schema()  # Reapplying migrations is safe.
    assert data.get_job(ready)["progress"]["documents"][0]["state"] == "extracted"
    assert data.get_job(queued)["progress"]["documents"][0]["state"] == "unknown"
    assert data.get_job(waiting)["progress"]["documents"][0]["state"] == "waiting"
