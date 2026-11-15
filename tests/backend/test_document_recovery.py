"""Recovery behaviour across actual SQL, API, evidence and concurrent providers."""
import asyncio
from dataclasses import replace
import json
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from src.main import create_app
from src.managers.ai_manager import AIManager
from src.managers.logic_manager import LogicManager
from src.errors.processing_error import ProcessingError
from test_api import create, submit
from test_pipeline import parsed, extraction, process
from test_storage import image_bytes


def submission(data, settings, titles=('A', 'B', 'C')):
    client = TestClient(create_app(settings, data))
    pid = create(client)
    result = submit(client, pid, modules=[{'module_title': title, 'credit': 6, 'file_fields': [f'f{i}']} for i, title in enumerate(titles)],
                    files={f'f{i}': (f'{title}.png', image_bytes(), 'image/png') for i, title in enumerate(titles)})
    assert result.status_code == 202, result.text
    return client, pid, result.json()['job_id']


async def execute(data, settings, gpt, doc=None):
    async with (httpx.AsyncClient(base_url='http://doc', transport=httpx.MockTransport(doc or (lambda _: httpx.Response(200, json=parsed())))) as dc,
                httpx.AsyncClient(base_url='http://gpt', transport=httpx.MockTransport(gpt)) as gc):
        return await AIManager(data, LogicManager(), dc, gc, replace(settings, gpt_api_key='fake', gpt_model='fake')).process_next_job()


def title(request):
    return json.loads(json.loads(request.content)['messages'][1]['content'])['module_title']


def test_partial_results_survive_and_only_failed_document_retries(data, settings):
    client, pid, jid = submission(data, settings)
    calls = {'A': 0, 'B': 0, 'C': 0, 'ocr': 0}
    fail = True

    def doc(_):
        calls['ocr'] += 1
        return httpx.Response(200, json=parsed())

    def gpt(request):
        name = title(request)
        calls[name] += 1
        return extraction(request, 'invalid_week' if fail and name == 'B' else 'success')

    asyncio.run(execute(data, settings, gpt, doc))
    before = client.get(f'/api/projects/{pid}').json()
    assert before['status'] == 'Partial' and before['coverage'] == 'partial'
    assert {i['module_title'] for i in before['schedule']['weeks'][11]['items']} == {'A', 'C'}
    failed = next(d for d in before['documents'] if d['module_title'] == 'B')
    assert failed['inference'] == 'unknown' and failed['retryable']
    assert 'week:' in failed['issues'][0]['message']
    assert client.get(failed['trace_url']).json()['elements']
    with data.pool.connection() as conn:
        assert conn.execute('SELECT count(*) AS n FROM extraction_attempts').fetchone()['n'] == 2
    key = str(uuid4())
    retry = lambda: client.post(f"/api/documents/{failed['document_id']}/retry", headers={'Idempotency-Key': key}, json={'expected_generation': 1})
    assert retry().status_code == 202
    assert retry().json()['generation'] == 2
    during = client.get(f'/api/projects/{pid}').json()
    assert during['schedule'] == before['schedule']
    fail = False
    asyncio.run(execute(data, settings, gpt, doc))
    after = client.get(f'/api/projects/{pid}').json()
    assert after['status'] == 'Ready' and after['coverage'] == 'complete'
    assert calls == {'A': 1, 'B': 3, 'C': 1, 'ocr': 3}
    assert not after['issues']
    assert after['schedule_revision_id'] > before['schedule_revision_id']
    assert {i['module_title'] for i in after['schedule']['weeks'][11]['items']} == {'A', 'B', 'C'}
    assert retry().json()['generation'] == 2  # Lost response recovery never requeues again.
    assert not asyncio.run(execute(data, settings, gpt, doc))
    events = data.get_processing_events(pid)
    assert [e['sequence'] for e in events] == sorted({e['sequence'] for e in events})
    assert events[-1]['kind'] == 'processing.settled'
    assert data.get_processing_events(pid, events[-2]['sequence']) == events[-1:]


def test_corrective_retry_keeps_rule_diagnostics_and_publishes_once(data, settings):
    client, pid, _ = submission(data, settings, ('HTM2211',))
    calls = []
    def gpt(request):
        calls.append(json.loads(request.content)['messages'][0]['content'])
        return extraction(request, 'invalid_week' if len(calls) == 1 else 'success')
    asyncio.run(execute(data, settings, gpt))
    assert client.get(f'/api/projects/{pid}').json()['status'] == 'Ready'
    assert len(calls) == 2 and 'week:' in calls[1]
    with data.pool.connection() as conn:
        attempt = conn.execute('SELECT * FROM extraction_attempts').fetchone()
        assert attempt['rejected']['assessments'][0]['week'] == 99
        assert conn.execute('SELECT count(*) AS n FROM assessments').fetchone()['n'] == 1


def test_concurrent_gpt_and_global_provider_limits(data, settings):
    client, pid, jid = submission(data, settings)
    active = {'gpt': 0, 'doc': 0}
    maximum = {'gpt': 0, 'doc': 0}
    async def provider(request, kind):
        active[kind] += 1
        maximum[kind] = max(maximum[kind], active[kind])
        await asyncio.sleep(.1 if kind == 'gpt' else .02)
        active[kind] -= 1
        return extraction(request) if kind == 'gpt' else httpx.Response(200, json=parsed())
    asyncio.run(execute(data, settings, lambda r: provider(r, 'gpt'), lambda r: provider(r, 'doc')))
    assert maximum == {'gpt': 2, 'doc': 1}
    assert client.get(f'/api/projects/{pid}').json()['status'] == 'Ready'
    with data.pool.connection() as conn:
        assert not conn.execute('SELECT 1 FROM provider_permits WHERE owner_token IS NOT NULL').fetchone()


def test_unreadable_and_unknown_fields_have_distinct_citable_outcomes(data, settings):
    client, pid, _ = submission(data, settings, ('Unknown',))
    def gpt(request):
        result = extraction(request)
        wire = json.loads(result.content)
        raw = json.loads(wire['choices'][0]['message']['content'])
        raw['assessments'][0]['week'] = None
        raw['assessments'][0]['evidence']['week'] = []
        wire['choices'][0]['message']['content'] = json.dumps(raw)
        return httpx.Response(200, json=wire)
    asyncio.run(execute(data, settings, gpt))
    project = client.get(f'/api/projects/{pid}').json()
    assert project['status'] == 'Partial'
    assert project['documents'][0]['inference'] == 'partially_understood'
    assert project['documents'][0]['uncertainties']
    assert project['schedule']['unscheduled'][0]['week'] is None
    client, pid, _ = submission(data, settings, ('Unreadable',))
    asyncio.run(execute(data, settings, extraction, lambda _: httpx.Response(200, json={'status': 'failure'})))
    doc = client.get(f'/api/projects/{pid}').json()['documents'][0]
    assert doc['inference'] == 'cannot_infer'
    assert client.get(doc['trace_url']).json()['parse'] is None
    assert client.get(doc['original_url']).status_code == 200


def test_empty_extraction_can_be_retried_without_repeating_ocr(data, settings):
    client, pid, _ = submission(data, settings, ('Empty',))
    asyncio.run(execute(data, settings, lambda r: extraction(r, 'empty')))
    doc = client.get(f'/api/projects/{pid}').json()['documents'][0]
    assert doc['inference'] == 'no_assessment_content'
    assert client.post(f"/api/documents/{doc['document_id']}/retry", headers={'Idempotency-Key': str(uuid4())}, json={'expected_generation': 1}).status_code == 202
    def no_ocr(_):
        pytest.fail('Successful parse must be reused')
    asyncio.run(execute(data, settings, extraction, no_ocr))
    assert client.get(f'/api/projects/{pid}').json()['status'] == 'Ready'


def test_replacement_preserves_original_and_recomputes_only_affected_module(data, settings):
    client, pid, _ = submission(data, settings, ('A', 'B'))
    asyncio.run(execute(data, settings, extraction))
    before = client.get(f'/api/projects/{pid}').json()
    old = before['documents'][0]
    response = client.post(f"/api/documents/{old['document_id']}/replacement", content=image_bytes('blue'), headers={
        'X-Filename': 'clearer.png', 'Expected-Generation': '1', 'Idempotency-Key': str(uuid4())})
    assert response.status_code == 202, response.text
    during = client.get(f'/api/projects/{pid}').json()
    assert during['stale'] and during['schedule'] == before['schedule']
    assert client.get(old['original_url']).status_code == 200
    calls = []
    def gpt(request):
        calls.append(title(request))
        return extraction(request)
    asyncio.run(execute(data, settings, gpt))
    after = client.get(f'/api/projects/{pid}').json()
    assert after['status'] == 'Ready' and not after['stale'], after
    assert len(after['documents']) == 2 and calls == [old['module_title']]
    assert old['document_id'] not in {d['document_id'] for d in after['documents']}


def test_expired_owner_cannot_commit_after_task_recovery(data, settings):
    client, pid, jid = submission(data, settings, ('A',))
    old = data.claim_next_job()
    task = data.claim_document_task(old)
    with data.pool.connection() as conn:
        conn.execute("UPDATE processing_jobs SET lease_expires_at=now()-interval '1 second' WHERE id=%s", (jid,))
    data.cleanup_interrupted_jobs()
    new = data.claim_next_job()
    assert new.lease_token != old.lease_token
    with pytest.raises(ProcessingError):
        data.save_document_chunk(old, task, 0, str(uuid4()), [], [])
    assert data.claim_document_task(new)['document']['id'] == task['document']['id']


def test_module_conflict_can_retry_candidates_without_deleting_old_evidence(data, settings):
    client, pid, _ = submission(data, settings, ('A',))
    # One chunk can pass field checks but fail whole-module relationship checks.
    def conflicting(request):
        response = extraction(request)
        wire = json.loads(response.content)
        raw = json.loads(wire['choices'][0]['message']['content'])
        raw['assessments'][0]['parent_key'] = 'missing-group'
        raw['assessments'][0]['evidence']['parent_key'] = raw['assessments'][0]['evidence']['name']
        wire['choices'][0]['message']['content'] = json.dumps(raw)
        return httpx.Response(200, json=wire)
    asyncio.run(execute(data, settings, conflicting))
    failed = client.get(f'/api/projects/{pid}').json()
    assert failed['status'] == 'Failed'
    doc = failed['documents'][0]
    assert doc['retryable']
    result = client.post(f"/api/documents/{doc['document_id']}/retry", headers={'Idempotency-Key': str(uuid4())}, json={'expected_generation': 1})
    assert result.status_code == 202
    asyncio.run(execute(data, settings, extraction))
    assert client.get(f'/api/projects/{pid}').json()['status'] == 'Ready'
    with data.pool.connection() as conn:
        assert conn.execute('SELECT count(*) AS n FROM document_chunks').fetchone()['n'] == 2
