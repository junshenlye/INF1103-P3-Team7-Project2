"""Regression coverage for confirmed lifecycle and correction failures."""
import asyncio
import json
from uuid import uuid4
import httpx
import pytest
from fastapi.testclient import TestClient
from src.main import create_app
from src.errors.issues import make_issue
from src.errors import error_codes
from test_api import create, submit
from test_storage import image_bytes
from test_pipeline import parsed, extraction
from test_document_recovery import execute, submission


def get_project(client, pid):
    return client.get(f'/api/projects/{pid}').json()


@pytest.mark.parametrize('interruption', ['before_claim', 'recovery_budget_exhausted'])
def test_interrupted_work_must_offer_a_retry(data, settings, interruption):
    client, pid, jid = submission(data, settings, ('A',))
    job = data.claim_next_job()
    if interruption == 'before_claim':
        data.fail_job(job, [make_issue(error_codes.PROCESSING_INTERRUPTED, 'Stopped')], True)
    else:
        data.claim_document_task(job)
        with data.pool.connection() as c:
            c.execute("UPDATE processing_jobs SET recoveries=3,lease_expires_at=now()-interval '1 second' WHERE id=%s", (jid,))
        data.cleanup_interrupted_jobs()
    p = get_project(client, pid)
    assert p['status'] == 'Interrupted'
    assert any(d['retryable'] for d in p['documents']), {
        'status': p['status'], 'documents': [(d['execution'], d['state'], d['retryable']) for d in p['documents']]}


def two_sources(data, settings):
    client = TestClient(create_app(settings, data))
    pid = create(client)
    r = submit(client, pid, modules=[{'module_title': 'Module', 'credit': 6, 'file_fields':['a','b']}], files={
        'a': ('a.png', image_bytes(), 'image/png'), 'b': ('b.png', image_bytes('blue'), 'image/png')})
    assert r.status_code == 202
    def doc(request):
        name = 'B' if image_bytes('blue') in request.content else 'A'
        return httpx.Response(200, json=parsed(f'Assessment {name}: due in Week 10 or Week 12, 20 percent'))
    return client, pid, doc


def assessment_response(request, fail_b=False, conflicting_a=False, unknown_week=False):
    body = json.loads(request.content)
    user = json.loads(body['messages'][1]['content'])
    is_b = 'Assessment B:' in user['source_elements'][0]['text']
    wire = json.loads(extraction(request).content)
    raw = json.loads(wire['choices'][0]['message']['content'])
    fact = raw['assessments'][0]
    fact.update(key='b' if is_b else 'a', name='B' if is_b else 'A', weight_percent=20)
    if fail_b and is_b: fact['week'] = 99
    if conflicting_a and not is_b:
        fact['parent_key'] = 'missing-parent'
        fact['evidence']['parent_key'] = fact['evidence']['name']
    if unknown_week:
        fact['week'] = None
        fact['evidence']['week'] = []
    wire['choices'][0]['message']['content'] = json.dumps(raw)
    return httpx.Response(200, json=wire)


def retry(client, d):
    r = client.post(f"/api/documents/{d['document_id']}/retry", headers={'Idempotency-Key':str(uuid4())}, json={'expected_generation':d['generation']})
    assert r.status_code == 202, r.text


def test_retry_of_other_source_must_preserve_user_correction(data, settings):
    client, pid, doc = two_sources(data, settings)
    asyncio.run(execute(data, settings, lambda r: assessment_response(r, fail_b=True), doc))
    p = get_project(client, pid)
    a = next(a for m in p['modules'] for a in m.get('assessments',[]) if a['facts']['key'] == 'a')
    r = client.post(f"/api/results/{a['result_id']}/assessments/{a['id']}/reviews", json={'expected_revision':0, 'changes':{'week':10}})
    assert r.status_code == 201, r.text
    assert get_project(client, pid)['schedule']['weeks'][9]['items']
    b = next(d for d in p['documents'] if d['filename']=='b.png')
    retry(client,b)
    asyncio.run(execute(data, settings, assessment_response, doc))
    after = get_project(client, pid)
    current = next(a for m in after['modules'] for a in m.get('assessments',[]) if a['facts']['key'] == 'a')
    assert current['facts']['week'] == 10, {'expected_user_week':10, 'actual_week':current['facts']['week'], 'revision':current['revision']}


def test_resolved_module_conflict_must_clear_sibling_failure_state(data, settings):
    client, pid, doc = two_sources(data, settings)
    asyncio.run(execute(data, settings, lambda r: assessment_response(r, conflicting_a=True), doc))
    p = get_project(client, pid)
    a = next(d for d in p['documents'] if d['filename']=='a.png')
    assert a['retryable']
    retry(client,a)
    asyncio.run(execute(data, settings, assessment_response, doc))
    after = get_project(client, pid)
    assert not after['issues']
    assert len(after['schedule']['weeks'][11]['items']) == 2
    assert after['status'] == 'Ready', {'status':after['status'], 'documents':[(d['filename'], d['inference'], d['issues']) for d in after['documents']]}


def test_correcting_unknown_fact_must_update_coverage(data, settings):
    client, pid, _ = submission(data, settings, ('A',))
    asyncio.run(execute(data, settings, lambda r: assessment_response(r, unknown_week=True)))
    p = get_project(client,pid)
    a = p['modules'][0]['assessments'][0]
    r=client.post(f"/api/results/{a['result_id']}/assessments/{a['id']}/reviews", json={
        'expected_revision':0, 'changes':{'week':12}, 'evidence':{'week':a['evidence']['name']}})
    assert r.status_code == 201, r.text
    after=get_project(client,pid)
    assert not after['schedule']['unscheduled']
    assert after['coverage']=='complete', {'coverage':after['coverage'], 'status':after['status'], 'inference':after['documents'][0]['inference']}


def test_project_snapshot_must_not_call_stale_replacement_complete(data, settings, monkeypatch):
    client, pid, _=submission(data, settings, ('A',))
    asyncio.run(execute(data, settings, extraction))
    p=get_project(client,pid)
    d=p['documents'][0]
    original_get=data.get_project
    armed=True
    def concurrent_get(project_id):
        nonlocal armed
        value=original_get(project_id)
        if armed:
            armed=False
            request_id=str(uuid4())
            descriptor=data.stage_document(request_id,'replacement.png')
            data.save_staged_chunk(descriptor['document_id'],image_bytes('blue'))
            descriptor=data.complete_staged_document(descriptor['document_id'])
            data.replace_document(d['document_id'],descriptor,str(uuid4()),1)
        return value
    monkeypatch.setattr(data,'get_project',concurrent_get)
    after=get_project(client,pid)
    assert not (after['coverage']=='complete' and after['stale']), {
        'coverage':after['coverage'], 'stale':after['stale'], 'status':after['status'],
        'actual_status':original_get(pid).status, 'document_execution':after['documents'][0]['execution']}


def test_snapshot_is_consistent_when_replacement_commits_between_reads(data, settings, monkeypatch):
    client, pid, _ = submission(data, settings, ('A',))
    asyncio.run(execute(data, settings, extraction))
    before = get_project(client, pid)
    old_document = before['documents'][0]
    load_assessments = data._load_assessments
    armed = True

    def interleave(conn, result_ids):
        nonlocal armed
        result = load_assessments(conn, result_ids)
        if armed:
            armed = False
            descriptor = data.stage_document(str(uuid4()), 'clearer.png')
            data.save_staged_chunk(descriptor['document_id'], image_bytes('blue'))
            descriptor = data.complete_staged_document(descriptor['document_id'])
            data.replace_document(old_document['document_id'], descriptor, str(uuid4()), 1)
        return result

    monkeypatch.setattr(data, '_load_assessments', interleave)
    snapshot = get_project(client, pid)
    assert snapshot['status'] == 'Ready' and snapshot['coverage'] == 'complete'
    assert not snapshot['stale']
    assert snapshot['documents'][0]['document_id'] == old_document['document_id']
    assert snapshot['documents'][0]['execution'] == 'succeeded'
    current = get_project(client, pid)
    assert current['status'] == 'Processing' and current['coverage'] == 'partial'
    assert current['stale'] and current['event_cursor'] > snapshot['event_cursor']


def test_review_committing_during_publication_is_reconciled_again(data, settings, monkeypatch):
    client, pid, doc = two_sources(data, settings)
    asyncio.run(execute(data, settings, lambda r: assessment_response(r, fail_b=True), doc))
    before = get_project(client, pid)
    a = next(a for m in before['modules'] for a in m.get('assessments', []) if a['facts']['key'] == 'a')
    b = next(d for d in before['documents'] if d['filename'] == 'b.png')
    retry(client, b)
    publish = data.save_extraction_result
    interleaved = False

    def reviewed_publication(*args, **kwargs):
        nonlocal interleaved
        if not interleaved:
            interleaved = True
            response = client.post(f"/api/results/{a['result_id']}/assessments/{a['id']}/reviews",
                                   json={'expected_revision': 0, 'changes': {'week': 10}})
            assert response.status_code == 201, response.text
        return publish(*args, **kwargs)

    monkeypatch.setattr(data, 'save_extraction_result', reviewed_publication)
    asyncio.run(execute(data, settings, assessment_response, doc))
    after = get_project(client, pid)
    current = next(a for m in after['modules'] for a in m['assessments'] if a['facts']['key'] == 'a')
    assert interleaved and current['facts']['week'] == 10 and current['revision'] == 1
    assert after['status'] == 'Ready'
    with data.pool.connection() as conn:
        lineage = conn.execute('SELECT previous_assessment_id FROM assessment_review_lineage WHERE assessment_id=%s', (current['id'],)).fetchone()
        assert str(lineage['previous_assessment_id']) == a['id']
        raw = conn.execute('SELECT facts FROM assessments WHERE id=%s', (current['id'],)).fetchone()['facts']
        assert raw['week'] == 12


def test_review_preserves_independent_source_uncertainties(data, settings):
    client, pid, _ = submission(data, settings, ('A',))
    def uncertain(request):
        wire = json.loads(assessment_response(request, unknown_week=True).content)
        raw = json.loads(wire['choices'][0]['message']['content'])
        raw['uncertainties'] = ['Confirm whether another assessment exists.']
        wire['choices'][0]['message']['content'] = json.dumps(raw)
        return httpx.Response(200, json=wire)
    asyncio.run(execute(data, settings, uncertain))
    before = get_project(client, pid)
    a = before['modules'][0]['assessments'][0]
    response = client.post(f"/api/results/{a['result_id']}/assessments/{a['id']}/reviews", json={
        'expected_revision': 0, 'changes': {'week': 12}, 'evidence': {'week': a['evidence']['name']}})
    assert response.status_code == 201
    after = get_project(client, pid)
    assert after['coverage'] == 'partial'
    assert after['documents'][0]['uncertainties'] == ['Confirm whether another assessment exists.']


def test_review_cannot_hide_a_missing_extraction_chunk(data, settings):
    from dataclasses import replace
    settings = replace(settings, chunk_bytes=1024)
    client, pid, _ = submission(data, settings, ('A',))
    calls = 0
    def gpt(request):
        nonlocal calls
        calls += 1
        return assessment_response(request, fail_b=False) if calls == 1 else extraction(request, 'invalid_week')
    def doc(_):
        return httpx.Response(200, json=parsed('Assessment A due Week 12, worth 20 percent. ' * 20))
    asyncio.run(execute(data, settings, gpt, doc))
    before = get_project(client, pid)
    assert calls > 1
    a = before['modules'][0]['assessments'][0]
    response = client.post(f"/api/results/{a['result_id']}/assessments/{a['id']}/reviews", json={
        'expected_revision': 0, 'changes': {'week': 10}})
    assert response.status_code == 201
    after = get_project(client, pid)
    assert after['coverage'] == 'partial' and after['documents'][0]['retryable']
    assert after['documents'][0]['issues']


def test_review_transfer_keeps_new_unreviewed_values():
    from copy import deepcopy
    from test_logic import record
    from src.managers.logic_manager import LogicManager
    original = record(week=12, weight_percent=60, weight_scope='module')
    reviewed = {**original, 'week': 10}
    prior = {'id': str(uuid4()), 'revision': 1,
             'original_facts': {k: v for k, v in original.items() if k != 'evidence'},
             'original_evidence': deepcopy(original['evidence']),
             'facts': {k: v for k, v in reviewed.items() if k != 'evidence'},
             'evidence': deepcopy(reviewed['evidence'])}
    new = record(week=12, weight_percent=40, weight_scope='module')
    transfer, = LogicManager().reconcile_reviews([new], [prior], {'source'}, 14)
    assert transfer['facts']['week'] == 10 and transfer['facts']['weight_percent'] == 40
    assert new['week'] == 12  # Domain reconciliation does not mutate raw evidence.


def test_upgrade_repair_clears_obsolete_metadata_without_changing_facts(data, settings):
    from psycopg.types.json import Jsonb
    client, pid, jid = submission(data, settings, ('A',))
    asyncio.run(execute(data, settings, extraction))
    before = get_project(client, pid)
    issue = make_issue(error_codes.INVALID_EXTRACTION, 'Old resolved module error.', 'module',
                       module_id=before['modules'][0]['id'])
    with data.pool.connection() as conn, conn.transaction():
        conn.execute("UPDATE document_tasks SET inference='partially_understood',issues=%s WHERE job_id=%s", (Jsonb([issue]), jid))
        data._finish_job(conn, jid, pid, 'Partial')
    assert get_project(client, pid)['status'] == 'Partial'
    data.repair_completed_outcomes()
    once = get_project(client, pid)
    data.repair_completed_outcomes()
    twice = get_project(client, pid)
    assert once['status'] == 'Ready' and twice == once
    assert once['schedule'] == before['schedule']
    assert once['event_cursor'] > before['event_cursor']
