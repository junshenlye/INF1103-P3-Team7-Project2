"""Refactor regression gates for ownership, injected rules and durable retries."""
import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from src.errors import error_codes
from src.errors.issues import make_issue
from src.errors.processing_error import ProcessingError
from src.managers.ai_manager import AIManager
from src.main import create_app
from test_api import create, submit
from test_document_recovery import submission, execute
from test_pipeline import parsed, extraction
from test_storage import image_bytes


@pytest.mark.parametrize('fault', ['foreign_document', 'foreign_parse', 'duplicate_source'])
def test_parse_ownership_rejection_is_atomic_and_does_not_poison_the_claim(data, settings, fault):
    _, _, jid = submission(data, settings, ('Ownership',))
    job = data.claim_next_job()
    task = data.claim_document_task(job)
    document_id, parse_id = task['document']['id'], str(uuid4())
    data.save_document_progress(job, document_id, 'parsing')
    record = {'id': str(uuid4()), 'document_id': document_id, 'parse_id': parse_id,
              'text': 'Quiz in Week 4', 'regions': [], 'context': 'paragraph'}
    invalid = {**record, **({'document_id': str(uuid4())} if fault == 'foreign_document'
                            else {'parse_id': str(uuid4())} if fault == 'foreign_parse' else {})}
    records = [invalid, dict(invalid)] if fault == 'duplicate_source' else [invalid]
    with pytest.raises(ProcessingError) as failure:
        data.save_parse_snapshot(job, document_id, parse_id, 'ownership-test', records, 1, 1024)
    assert failure.value.code == error_codes.INVALID_EXTRACTION
    checkpoint = data.get_document_checkpoint(document_id)
    assert checkpoint['parse_id'] is None and checkpoint['elements'] == ()
    assert data.get_job(jid)['status'] == 'running'

    # The rejection rolls back the entire parse, leaving the same live claim usable.
    data.save_parse_snapshot(job, document_id, parse_id, 'ownership-test', [record], 1, 1024)
    document = data.get_document(document_id)
    source, = document.get_sources()
    assert source.document_id == document.id and source.parse_id == parse_id
    assert source.to_record() == record
    assert data.get_document_checkpoint(document_id)['elements'] == (record,)
    assert 'storage_key' not in task['document']


def test_injected_retry_rule_is_checked_before_generation_or_events_change(data, settings, monkeypatch):
    client, pid, jid = submission(data, settings, ('Retry policy',))
    asyncio.run(execute(data, settings, lambda request: extraction(request, 'invalid_week')))
    before = client.get(f'/api/projects/{pid}').json()
    document = before['documents'][0]
    assert before['status'] == 'Failed' and document['generation'] == 1
    calls = []

    def deny(*args):
        calls.append(args)
        return False

    key = str(uuid4())
    arguments = {'headers': {'Idempotency-Key': key}, 'json': {'expected_generation': 1}}
    with monkeypatch.context() as patch:
        patch.setattr(data.logic_manager, 'can_retry_document', deny)
        response = client.post(f"/api/documents/{document['document_id']}/retry", **arguments)
        assert response.status_code == 409
        assert calls and calls[0][:2] == ('Failed', 'failed')
        after = client.get(f'/api/projects/{pid}').json()
        assert after['event_cursor'] == before['event_cursor']
        assert after['documents'][0]['generation'] == 1
        assert data.get_job(jid)['status'] == 'Failed'

    # A rejected request did not consume its idempotency key or mutate the task.
    accepted = client.post(f"/api/documents/{document['document_id']}/retry", **arguments)
    assert accepted.status_code == 202 and accepted.json()['generation'] == 2
    assert client.post(f"/api/documents/{document['document_id']}/retry", **arguments).json() == accepted.json()
    assert data.get_job(jid)['status'] == 'queued'


def test_retry_preserves_saved_chunk_bounds_when_worker_configuration_changes(data, settings):
    original_settings = replace(settings, chunk_bytes=1024, max_chunks=20)
    client, pid, _ = submission(data, original_settings, ('Checkpoint bounds',))
    document_text = 'Final exam in Week 12, worth 60 percent. ' * 45
    asyncio.run(execute(data, original_settings, lambda request: extraction(request, 'empty'),
                        lambda _: httpx.Response(200, json=parsed(document_text))))
    before = client.get(f'/api/projects/{pid}').json()
    document = before['documents'][0]
    saved = data.get_document_checkpoint(document['document_id'])
    assert saved['chunk_count'] > 1 and saved['chunk_bytes'] == 1024
    assert client.post(f"/api/documents/{document['document_id']}/retry",
                       headers={'Idempotency-Key': str(uuid4())},
                       json={'expected_generation': 1}).status_code == 202
    runtime = replace(settings, chunk_bytes=8192, max_chunks=1, gpt_api_key='fake', gpt_model='fake')
    sent = []

    def no_ocr(_):
        pytest.fail('A saved immutable parse must not be sent through OCR again.')

    def gpt(request):
        sent.append(json.loads(json.loads(request.content)['messages'][1]['content'])['source_elements'])
        return extraction(request)

    async def run():
        async with (httpx.AsyncClient(base_url='http://doc', transport=httpx.MockTransport(no_ocr)) as doc,
                    httpx.AsyncClient(base_url='http://gpt', transport=httpx.MockTransport(gpt)) as provider):
            worker = AIManager(data, data.logic_manager, doc, provider, runtime)
            assert await worker.process_next_job()
            assert worker._settings is runtime and runtime.chunk_bytes == 8192 and runtime.max_chunks == 1

    asyncio.run(run())
    assert len(sent) == saved['chunk_count']
    assert all(len(json.dumps(chunk, ensure_ascii=False).encode()) <= saved['chunk_bytes'] for chunk in sent)
    current = data.get_document_checkpoint(document['document_id'])
    assert current['parse_id'] == saved['parse_id'] and current['elements'] == saved['elements']
    assert client.get(f'/api/projects/{pid}').json()['status'] == 'Ready'


@pytest.mark.parametrize('operation', ['complete', 'attempt', 'parse'])
def test_recovered_task_rejects_all_stale_owner_writes(data, settings, operation):
    _, _, jid = submission(data, settings, ('Fencing',))
    old = data.claim_next_job()
    old_task = data.claim_document_task(old)
    with data.pool.connection() as conn:
        conn.execute("UPDATE processing_jobs SET lease_expires_at=now()-interval '1 second' WHERE id=%s", (jid,))
    assert data.cleanup_interrupted_jobs() == 1
    current = data.claim_next_job()
    task = data.claim_document_task(current)
    assert current.lease_token != old.lease_token
    assert task['document']['id'] == old_task['document']['id']
    issue = make_issue(error_codes.PROVIDER_UNAVAILABLE, 'Failed provider', 'document')
    writes = {
        'complete': lambda: data.finish_document_task(old, old_task, data.logic_manager.build_document_outcome([], [issue])),
        'attempt': lambda: data.record_extraction_attempt(old, old_task, 'extracting', 0, 1, issue['code'], issue['message']),
        'parse': lambda: data.save_parse_snapshot(old, task['document']['id'], str(uuid4()), 'stale', [], 0),
    }
    with pytest.raises(ProcessingError) as failure:
        writes[operation]()
    assert failure.value.code == error_codes.PROCESSING_INTERRUPTED
    data.fail_job(old, [issue])  # A stale worker's finalizer cannot stop the new owner.
    with data.pool.connection() as conn:
        state = conn.execute('SELECT state,owner_token FROM document_tasks WHERE document_id=%s', (task['document']['id'],)).fetchone()
        assert state['state'] == 'running' and str(state['owner_token']) == current.lease_token
        for table in ('extraction_attempts', 'parse_snapshots', 'processing_issues'):
            assert conn.execute(f'SELECT count(*) AS n FROM {table}').fetchone()['n'] == 0
    assert data.get_job(jid)['status'] == 'running'


def test_replacement_retains_exclusive_source_ownership_for_historical_original(data, settings):
    client, pid, _ = submission(data, settings, ('Original',))
    asyncio.run(execute(data, settings, extraction))
    before = client.get(f'/api/projects/{pid}').json()
    old_id = before['documents'][0]['document_id']
    original = data.get_document(old_id)
    old_sources = {source.id for source in original.get_sources()}
    assert old_sources
    response = client.post(f'/api/documents/{old_id}/replacement', content=image_bytes('blue'), headers={
        'X-Filename': 'replacement.png', 'Expected-Generation': '1', 'Idempotency-Key': str(uuid4())})
    assert response.status_code == 202
    new_id = response.json()['document_id']
    assert data.get_document(new_id).get_sources() == ()
    asyncio.run(execute(data, settings, extraction))
    replacement = data.get_document(new_id)
    assert all(source.document_id == new_id for source in replacement.get_sources())
    assert old_sources.isdisjoint(source.id for source in replacement.get_sources())
    historical = data.get_document(old_id)
    assert {source.id for source in historical.get_sources()} == old_sources
    assert all(source.document_id == old_id for source in historical.get_sources())
    assert client.get(before['documents'][0]['original_url']).status_code == 200
    assert client.get(f'/api/projects/{pid}').json()['status'] == 'Ready'


def test_replacing_reviewed_evidence_retains_the_review_and_marks_the_head_stale(data, settings):
    client, pid, _ = submission(data, settings, ('Reviewed original',))
    asyncio.run(execute(data, settings, extraction))
    before = client.get(f'/api/projects/{pid}').json()
    assessment = before['modules'][0]['assessments'][0]
    response = client.post(f"/api/results/{assessment['result_id']}/assessments/{assessment['id']}/reviews",
                           json={'expected_revision': 0, 'changes': {'week': 10}})
    assert response.status_code == 201
    old_document = before['documents'][0]
    replacement = client.post(f"/api/documents/{old_document['document_id']}/replacement",
                              content=image_bytes('blue'), headers={
                                  'X-Filename': 'clearer.png', 'Expected-Generation': '1',
                                  'Idempotency-Key': str(uuid4())})
    assert replacement.status_code == 202
    asyncio.run(execute(data, settings, extraction))
    after = client.get(f'/api/projects/{pid}').json()
    assert after['status'] == 'Partial' and after['stale'] and after['coverage'] == 'partial'
    retained = after['modules'][0]['assessments'][0]
    assert retained['id'] == assessment['id'] and retained['facts']['week'] == 10 and retained['revision'] == 1
    assert after['schedule']['weeks'][9]['items'] and not after['schedule']['weeks'][11]['items']
    assert any(issue['code'] == error_codes.REVISION_CONFLICT for issue in after['issues'])
    assert after['documents'][0]['retryable']
    assert client.get(old_document['original_url']).status_code == 200
    with data.pool.connection() as conn:
        original_facts = conn.execute('SELECT facts FROM assessments WHERE id=%s', (assessment['id'],)).fetchone()['facts']
        assert original_facts['week'] == 12
        assert conn.execute('SELECT count(*) AS n FROM extraction_results WHERE published').fetchone()['n'] == 1


def test_records_a_real_partial_retry_to_ready_transition_trace(data, settings, tmp_path):
    settings = replace(settings, document_workers=1, gpt_concurrency=1)
    client = TestClient(create_app(settings, data))
    pid = create(client)
    snapshots = []

    def capture(label):
        project = client.get(f'/api/projects/{pid}').json()
        snapshots.append({
            'label': label, 'project_status': project['status'], 'coverage': project['coverage'],
            'job_status': data.get_job(project['job_id'])['status'] if project['job_id'] else None,
            'event_cursor': project['event_cursor'], 'schedule_revision_id': project['schedule_revision_id'],
            'documents': [{key: document[key] for key in (
                'module_title', 'state', 'execution', 'inference', 'generation', 'retryable')}
                for document in project['documents']],
        })
        return project

    capture('project created')
    accepted = submit(client, pid, modules=[
        {'module_title': name, 'credit': 6, 'file_fields': [name.lower()]} for name in ('A', 'B')
    ], files={name.lower(): (name + '.png', image_bytes(), 'image/png') for name in ('A', 'B')})
    assert accepted.status_code == 202
    capture('submission accepted')

    def doc(_):
        capture('OCR in progress')
        return httpx.Response(200, json=parsed())

    def first_attempt(request):
        capture('extraction in progress')
        title = json.loads(json.loads(request.content)['messages'][1]['content'])['module_title']
        return extraction(request, 'invalid_week' if title == 'B' else 'success')

    asyncio.run(execute(data, settings, first_attempt, doc))
    partial = capture('first generation settled')
    assert partial['status'] == 'Partial' and partial['coverage'] == 'partial'
    failed = next(document for document in partial['documents'] if document['module_title'] == 'B')
    response = client.post(f"/api/documents/{failed['document_id']}/retry",
                           headers={'Idempotency-Key': str(uuid4())}, json={'expected_generation': 1})
    assert response.status_code == 202
    capture('targeted retry queued')

    def no_ocr(_):
        pytest.fail('Targeted retry should reuse B’s parse and leave A untouched.')

    def retry_attempt(request):
        capture('retry extraction in progress')
        return extraction(request)

    asyncio.run(execute(data, settings, retry_attempt, no_ocr))
    ready = capture('retry settled')
    assert ready['status'] == 'Ready' and ready['coverage'] == 'complete'
    observed_b = {(snapshot['job_status'], document['execution'], document['generation'])
                  for snapshot in snapshots for document in snapshot['documents']
                  if document['module_title'] == 'B'}
    assert {('queued', 'queued', 1), ('running', 'running', 1), ('Partial', 'failed', 1),
            ('queued', 'queued', 2), ('running', 'running', 2), ('Ready', 'succeeded', 2)} <= observed_b
    cursors = [snapshot['event_cursor'] for snapshot in snapshots]
    assert cursors == sorted(cursors)
    events = data.get_processing_events(pid)
    assert events[-1]['kind'] == 'processing.settled' and events[-1]['payload']['status'] == 'Ready'
    artifact = {'scenario': 'partial publication, targeted retry, saved parse reuse, complete result',
                'snapshots': snapshots, 'events': events}
    directory = Path(os.environ.get('STACKPLAN_TEST_ARTIFACT_DIR', str(tmp_path)))
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'uml-state-transitions.json').write_text(json.dumps(artifact, indent=2) + '\n')
